from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.conversation import Conversation, ConversationMessage
from backend.models.site import Site
from backend.services.site_service import site_service
from backend.services.task_service import task_service
from backend.services.requirement_service import requirement_service


# Simple token estimation: ~4 chars per token for Chinese/English mix
def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


TOKEN_BUDGET = 8000
RECENT_MESSAGE_LIMIT = 10


class ConversationService:

    # ── CRUD ─────────────────────────────────────────────

    async def create_conversation(
        self,
        db: AsyncSession,
        site_id: str,
        current_user: object,
        title: str = "新会话",
    ) -> Conversation:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        conv = Conversation(
            site_id=site.id,
            owner_id=str(getattr(current_user, "id", "")),
            title=title,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        return conv

    async def list_conversations(
        self,
        db: AsyncSession,
        site_id: str,
        current_user: object,
        limit: int = 50,
    ) -> list[Conversation]:
        site = await site_service.get_site_by_public_id(db, site_id, current_user)
        rows = await db.execute(
            select(Conversation)
            .where(
                Conversation.site_id == site.id,
                Conversation.status == "active",
            )
            .order_by(desc(Conversation.last_message_at), desc(Conversation.created_at))
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def get_conversation(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
    ) -> Conversation:
        conv = await db.get(Conversation, conv_id)
        if conv is None:
            raise HTTPException(status_code=404, detail=f"Conversation not found: {conv_id}")
        # Verify access via site ownership
        site = await db.get(Site, conv.site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Conversation site not found")
        await site_service.get_site_by_public_id(db, site.site_id, current_user)
        return conv

    async def archive_conversation(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
    ) -> Conversation:
        conv = await self.get_conversation(db, conv_id, current_user)
        conv.status = "archived"
        await db.commit()
        await db.refresh(conv)
        return conv

    # ── Messages ─────────────────────────────────────────

    async def list_messages(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
        limit: int = 100,
        after_seq: int = 0,
    ) -> list[ConversationMessage]:
        await self.get_conversation(db, conv_id, current_user)
        rows = await db.execute(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conv_id,
                ConversationMessage.seq > after_seq,
            )
            .order_by(ConversationMessage.seq)
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def _next_seq(self, db: AsyncSession, conv_id: str) -> int:
        result = await db.execute(
            select(func.coalesce(func.max(ConversationMessage.seq), 0))
            .where(ConversationMessage.conversation_id == conv_id)
        )
        return (result.scalar() or 0) + 1

    async def add_message(
        self,
        db: AsyncSession,
        conv_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        provider: str = "",
        task_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        seq = await self._next_seq(db, conv_id)
        token_count = _estimate_tokens(content)
        msg = ConversationMessage(
            conversation_id=conv_id,
            seq=seq,
            role=role,
            content=content,
            message_type=message_type,
            provider=provider,
            task_id=task_id,
            token_count=token_count,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        )
        db.add(msg)
        # Update conversation counters
        now = datetime.now(timezone.utc)
        await db.execute(
            update(Conversation)
            .where(Conversation.id == conv_id)
            .values(
                message_count=Conversation.message_count + 1,
                last_message_at=now,
            )
        )
        await db.commit()
        await db.refresh(msg)
        return msg

    # ── Context Assembly ─────────────────────────────────

    async def build_context_prompt(
        self,
        db: AsyncSession,
        conv_id: str,
        user_message: str,
        site_id: str,
    ) -> str:
        """
        Assemble multi-turn context:
        1. System prompt (current site requirement)
        2. Conversation summary (if history exceeds token budget)
        3. Recent K messages
        4. Current user message
        """
        # 1. Load current requirement doc from site
        requirement = await self._get_current_requirement(db, site_id)

        # 2. Load conversation summary
        conv = await db.get(Conversation, conv_id)
        summary = (conv.summary_text or "").strip() if conv else ""

        # 3. Load recent messages
        rows = await db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conv_id)
            .order_by(desc(ConversationMessage.seq))
            .limit(RECENT_MESSAGE_LIMIT)
        )
        recent = list(reversed(list(rows.scalars().all())))

        # 4. Build context with token budget
        context_parts: list[str] = []

        system_prompt = (
            "你是站点开发助手。请根据对话历史和用户最新指令修改站点代码。\n"
        )
        if requirement:
            system_prompt += f"\n当前站点需求如下：\n{requirement}\n"
        context_parts.append(f"[系统提示]\n{system_prompt}")

        if summary:
            context_parts.append(f"[对话摘要]\n{summary}")

        # Trim recent messages to fit token budget
        total_tokens = sum(_estimate_tokens(p) for p in context_parts)
        total_tokens += _estimate_tokens(user_message)
        message_lines: list[str] = []
        for msg in recent:
            line = f"{msg.role}: {msg.content}"
            line_tokens = _estimate_tokens(line)
            if total_tokens + line_tokens > TOKEN_BUDGET:
                break
            message_lines.append(line)
            total_tokens += line_tokens

        if message_lines:
            context_parts.append("[对话历史]\n" + "\n".join(message_lines))

        context_parts.append(f"[本次需求]\n{user_message}")
        return "\n\n".join(context_parts)

    async def _get_current_requirement(self, db: AsyncSession, site_id: str) -> str:
        """Read requirement.md from site's docs directory."""
        try:
            site = await db.get(Site, site_id)
            if site is None:
                return ""
            site_root = site_service.site_root(site.site_id)
            req_path = site_root / "docs" / "requirement.md"
            if req_path.exists():
                return req_path.read_text(encoding="utf-8")[:4000]
        except Exception:
            pass
        return ""

    async def check_and_summarize(
        self,
        db: AsyncSession,
        conv_id: str,
    ) -> bool:
        """
        Check if conversation exceeds token budget.
        If so, generate a rolling summary of older messages.
        Returns True if summary was updated.
        """
        result = await db.execute(
            select(func.coalesce(func.sum(ConversationMessage.token_count), 0))
            .where(ConversationMessage.conversation_id == conv_id)
        )
        total_tokens = result.scalar() or 0
        if total_tokens < TOKEN_BUDGET:
            return False

        # Collect all messages for summary (keep recent ones out)
        rows = await db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conv_id)
            .order_by(ConversationMessage.seq)
        )
        all_msgs = list(rows.scalars().all())
        if len(all_msgs) <= RECENT_MESSAGE_LIMIT:
            return False

        older = all_msgs[:-RECENT_MESSAGE_LIMIT]
        summary_lines = []
        for msg in older:
            summary_lines.append(f"[{msg.role}] {msg.content[:200]}")

        conv = await db.get(Conversation, conv_id)
        if conv:
            prev_summary = (conv.summary_text or "").strip()
            new_summary_parts = []
            if prev_summary:
                new_summary_parts.append(prev_summary)
            new_summary_parts.append("\n".join(summary_lines))
            # Keep summary under 2000 chars
            combined = "\n---\n".join(new_summary_parts)
            if len(combined) > 2000:
                combined = combined[-2000:]
            conv.summary_text = combined
            await db.commit()
        return True

    # ── Send Message (orchestrator) ─────────────────────

    async def send_message(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
        content: str,
        provider: str = "codex",
        current_url: str = "",
        selected_xpath: str = "",
        console_errors: str = "",
    ) -> dict[str, Any]:
        """
        1. Save user message
        2. Build context prompt
        3. Create develop_code task
        4. Save assistant placeholder message (task_ref)
        5. Return both messages + task info
        """
        conv = await self.get_conversation(db, conv_id, current_user)
        site = await db.get(Site, conv.site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Site not found")

        # 1. Save user message
        user_msg = await self.add_message(
            db, conv_id, role="user", content=content, provider=provider,
        )

        # 2. Build context prompt
        prompt = await self.build_context_prompt(db, conv_id, content, conv.site_id)

        # 3. Create develop_code task via task_service
        payload_data = {
            "site_id": site.site_id,
            "task_type": "develop_code",
            "provider": provider,
            "prompt": prompt,
            "conversation_id": conv_id,
            "current_url": current_url,
            "selected_xpath": selected_xpath,
            "console_errors": console_errors,
        }
        task = await task_service.create_task(
            db=db,
            current_user=current_user,
            site_id=site.site_id,
            task_type="develop_code",
            provider=provider,
            payload_data=payload_data,
            enqueue=True,
        )

        # 4. Save assistant placeholder (task_ref type)
        assistant_msg = await self.add_message(
            db,
            conv_id,
            role="assistant",
            content=f"任务已创建，正在处理中...",
            message_type="task_ref",
            provider=provider,
            task_id=str(task.id),
        )

        # 5. Check if summarization needed
        await self.check_and_summarize(db, conv_id)

        return {
            "user_message": self.serialize_message(user_msg),
            "assistant_message": self.serialize_message(assistant_msg),
            "task_id": str(task.id),
            "task": task_service.serialize_task(task),
        }

    # ── Serialization ────────────────────────────────────

    @staticmethod
    def serialize_message(msg: ConversationMessage) -> dict[str, Any]:
        return {
            "id": msg.id,
            "conversation_id": str(msg.conversation_id),
            "seq": msg.seq,
            "role": msg.role,
            "content": msg.content,
            "message_type": msg.message_type,
            "provider": msg.provider,
            "task_id": msg.task_id,
            "token_count": msg.token_count,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }

    @staticmethod
    def serialize_conversation(conv: Conversation) -> dict[str, Any]:
        return {
            "id": str(conv.id),
            "site_id": str(conv.site_id),
            "title": conv.title,
            "status": conv.status,
            "summary_text": conv.summary_text or "",
            "message_count": conv.message_count,
            "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        }


conversation_service = ConversationService()
