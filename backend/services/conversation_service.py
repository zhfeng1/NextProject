from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import HTTPException
import redis.asyncio as aioredis
from redis.exceptions import RedisError
from sqlalchemy import desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.conversation import Conversation, ConversationMessage
from backend.models.site import Site
from backend.models.task import AgentTask
from backend.core.config import get_settings
from backend.services.conversation_git_service import conversation_git_service
from backend.services.project_service import project_service
from backend.services.site_service import site_service
from backend.services.task_service import SUPPORTED_PROVIDERS, task_service


# Simple token estimation: ~4 chars per token for Chinese/English mix
def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def _short_title(content: str) -> str:
    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    return (first_line or "新会话")[:80]


def _is_default_title(title: str | None) -> bool:
    return not title or title.strip() in {"新会话", "多轮对话"}


class ConversationService:
    _memory_lifecycle_locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def _lifecycle_lock(self, conv_id: str) -> AsyncIterator[None]:
        settings = get_settings()
        if settings.auth_session_backend == "memory":
            lock = self._memory_lifecycle_locks.setdefault(conv_id, asyncio.Lock())
            try:
                await asyncio.wait_for(lock.acquire(), timeout=5)
            except asyncio.TimeoutError as exc:
                raise HTTPException(status_code=409, detail="会话正在执行其他操作，请稍后重试") from exc
            try:
                yield
            finally:
                lock.release()
            return

        client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        key = f"nextproject:conversation-lifecycle:{conv_id}"
        token = str(uuid.uuid4())
        release_script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )
        try:
            acquired = await client.set(key, token, nx=True, ex=300)
            if not acquired:
                raise HTTPException(status_code=409, detail="会话正在执行其他操作，请稍后重试")
            yield
        except RedisError as exc:
            raise HTTPException(status_code=503, detail="会话生命周期锁服务不可用") from exc
        finally:
            try:
                await client.eval(release_script, 1, key, token)
            except RedisError:
                pass
            await client.aclose()

    async def _wait_worker_lock_release(self, conv_id: str, timeout_seconds: float = 30.0) -> bool:
        settings = get_settings()
        if settings.auth_session_backend == "memory":
            return True
        client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        worker_key = f"nextproject:site-lock:conversation:{conv_id}"
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        try:
            while asyncio.get_running_loop().time() < deadline:
                if not await client.exists(worker_key):
                    return True
                await asyncio.sleep(0.2)
            return not bool(await client.exists(worker_key))
        except RedisError as exc:
            raise HTTPException(status_code=503, detail="无法确认会话任务是否已停止") from exc
        finally:
            await client.aclose()

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
            project_id=str(site.project_id) if site.project_id else None,
            owner_id=str(getattr(current_user, "id", "")),
            scope_type="site",
            title=title,
            repo_ids_json=[site.site_id],
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
                Conversation.scope_type == "site",
                Conversation.status == "active",
            )
            .order_by(desc(Conversation.last_message_at), desc(Conversation.created_at))
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def create_project_conversation(
        self,
        db: AsyncSession,
        project_id: str,
        current_user: object,
        title: str = "新会话",
        repo_ids: list[str] | None = None,
        provider: str = "codex",
    ) -> Conversation:
        project, sites, selected_repo_ids = await self._resolve_project_repos(
            db, project_id, current_user, repo_ids
        )
        normalized_provider = (provider or "codex").strip().lower()
        if normalized_provider not in SUPPORTED_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"不支持的编程工具: {provider}")
        conv_id = str(uuid.uuid4())
        worktree_root, branch_name, git_repos = conversation_git_service.create_worktrees(
            project_id=str(project.id),
            sites=sites,
            conversation_id=conv_id,
            title=title,
            provider=normalized_provider,
        )
        conv = Conversation(
            id=conv_id,
            site_id=sites[0].id,
            project_id=project_id,
            owner_id=str(getattr(current_user, "id", "")),
            scope_type="project",
            title=title,
            repo_ids_json=selected_repo_ids,
            provider=normalized_provider,
            branch_name=branch_name,
            worktree_root=str(worktree_root),
            git_repos_json=git_repos,
        )
        db.add(conv)
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            conversation_git_service.remove_worktrees(git_repos, str(worktree_root))
            raise
        await db.refresh(conv)
        return conv

    async def list_project_conversations(
        self,
        db: AsyncSession,
        project_id: str,
        current_user: object,
        limit: int = 50,
        status: str = "active",
    ) -> list[Conversation]:
        project = await project_service.get_project(db, project_id, current_user)
        normalized_status = (status or "active").strip().lower()
        if normalized_status not in {"active", "archived"}:
            raise HTTPException(status_code=400, detail="Unsupported conversation status")
        rows = await db.execute(
            select(Conversation)
            .where(
                Conversation.project_id == str(project.id),
                Conversation.scope_type == "project",
                Conversation.status == normalized_status,
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
        scope_type = getattr(conv, "scope_type", "") or "site"
        if scope_type == "project" and getattr(conv, "project_id", None):
            await project_service.get_project(db, str(conv.project_id), current_user)
            return conv
        # Verify access via site ownership for legacy/site conversations.
        site = await db.get(Site, conv.site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Conversation site not found")
        await site_service.get_site_by_public_id(db, site.site_id, current_user)
        return conv

    async def _resolve_project_repos(
        self,
        db: AsyncSession,
        project_id: str,
        current_user: object,
        repo_ids: list[str] | None = None,
    ) -> tuple[object, list[Site], list[str]]:
        project = await project_service.get_project(db, project_id, current_user)
        repos = await project_service.get_project_repos(db, str(project.id))
        if not repos:
            raise HTTPException(status_code=400, detail="Project has no repositories")
        repo_by_public_id = {repo.site_id: repo for repo in repos}
        selected_ids = [str(item).strip() for item in (repo_ids or []) if str(item).strip()]
        if not selected_ids:
            selected_ids = [repo.site_id for repo in repos]
        missing = [repo_id for repo_id in selected_ids if repo_id not in repo_by_public_id]
        if missing:
            raise HTTPException(status_code=404, detail=f"Repo not found in project: {missing[0]}")
        selected_sites = [repo_by_public_id[repo_id] for repo_id in selected_ids]
        return project, selected_sites, selected_ids

    async def archive_conversation(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
    ) -> Conversation:
        async with self._lifecycle_lock(conv_id):
            return await self._archive_conversation_locked(db, conv_id, current_user)

    async def _archive_conversation_locked(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
    ) -> Conversation:
        conv = await self.get_conversation(db, conv_id, current_user)
        if (getattr(conv, "scope_type", "") or "site") != "project":
            conv.status = "archived"
            await db.commit()
            await db.refresh(conv)
            return conv
        if conv.status == "archived":
            return conv
        if conv.status == "archiving":
            raise HTTPException(status_code=409, detail="会话正在归档中")
        completion_status = getattr(conv, "completion_status", "") or "active"
        if completion_status == "merging":
            raise HTTPException(status_code=409, detail="会话正在合并中，不能归档")
        cleanup_status = getattr(conv, "cleanup_status", "") or "retained"
        if completion_status == "completed" and cleanup_status == "cleaned":
            try:
                self._remove_provider_session_state(conv)
                conv.provider_session_id = ""
            except Exception as exc:
                conv.cleanup_status = "warning"
                conv.cleanup_error = f"编程工具会话状态清理失败: {exc}"[:4000]
            conv.status = "archived"
            await db.commit()
            await db.refresh(conv)
            return conv
        git_repos = list(getattr(conv, "git_repos_json", None) or [])
        merged_changes = [conversation_git_service.has_merged_changes(item) for item in git_repos]
        if completion_status != "completed" and any(merged_changes):
            raise HTTPException(status_code=409, detail="已有仓库合并到主分支，请先完成或修复合并后再归档")

        conv.status = "archiving"
        conv.cleanup_status = "cleaning"
        conv.cleanup_error = ""
        await db.commit()

        tasks = await self._conversation_tasks(db, conv)
        for task in tasks:
            status = getattr(task.status, "value", task.status)
            if status in {"queued", "running"}:
                await task_service.cancel_task(db, str(task.id), current_user)
        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline:
            tasks = await self._conversation_tasks(db, conv)
            if all(getattr(task.status, "value", task.status) not in {"queued", "running"} for task in tasks):
                break
            await asyncio.sleep(0.1)
        else:
            conv.status = "active"
            conv.cleanup_status = "warning"
            conv.cleanup_error = "等待进行中的任务停止超时"
            await db.commit()
            raise HTTPException(status_code=409, detail=conv.cleanup_error)
        if not await self._wait_worker_lock_release(str(conv.id), timeout_seconds=30):
            conv.status = "active"
            conv.cleanup_status = "warning"
            conv.cleanup_error = "等待会话任务释放工作区锁超时"
            await db.commit()
            raise HTTPException(status_code=409, detail=conv.cleanup_error)

        if git_repos:
            conv.git_repos_json = conversation_git_service.capture_repository_tips(
                git_repos,
                require_clean=False,
            )
            await db.commit()
            await self._snapshot_git_state(db, conv)
            await self._perform_git_cleanup(
                db,
                conv,
                force=completion_status != "completed",
            )
        else:
            try:
                self._remove_provider_session_state(conv)
                conv.provider_session_id = ""
                conv.cleanup_status = "cleaned"
                conv.cleanup_error = ""
            except Exception as exc:
                conv.cleanup_status = "warning"
                conv.cleanup_error = f"编程工具会话状态清理失败: {exc}"[:4000]
        conv.status = "archived"
        if completion_status != "completed":
            conv.completion_status = "discarded"
            conv.completion_error = ""
        await db.commit()
        await db.refresh(conv)
        return conv

    async def restore_conversation(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
    ) -> Conversation:
        conv = await self.get_conversation(db, conv_id, current_user)
        if (getattr(conv, "scope_type", "") or "site") == "project":
            raise HTTPException(status_code=409, detail="项目开发会话归档后不可恢复，请新建会话")
        conv.status = "active"
        await db.commit()
        await db.refresh(conv)
        return conv

    async def _conversation_tasks(self, db: AsyncSession, conv: Conversation) -> list[AgentTask]:
        message_rows = await db.execute(
            select(ConversationMessage.task_id).where(
                ConversationMessage.conversation_id == str(conv.id),
                ConversationMessage.task_id != "",
            )
        )
        task_ids = {str(value) for value in message_rows.scalars().all() if value}
        if getattr(conv, "completion_task_id", ""):
            task_ids.add(str(conv.completion_task_id))
        filters = [AgentTask.conversation_id == str(conv.id)]
        if task_ids:
            filters.append(AgentTask.id.in_(task_ids))
        rows = await db.execute(select(AgentTask).where(or_(*filters)))
        return list(rows.scalars().unique().all())

    async def _snapshot_git_state(self, db: AsyncSession, conv: Conversation) -> None:
        conv.diff_snapshot_json = self._build_git_diff_snapshot(conv)
        await db.commit()

    @staticmethod
    def _build_git_diff_snapshot(conv: Conversation) -> dict[str, Any]:
        git_repos = list(getattr(conv, "git_repos_json", None) or [])
        state = conversation_git_service.conversation_state(
            branch_name=getattr(conv, "branch_name", "") or "",
            provider=getattr(conv, "provider", "") or "",
            completion_status=getattr(conv, "completion_status", "") or "active",
            worktree_root=getattr(conv, "worktree_root", "") or "",
            git_repos=git_repos,
            diff_snapshot=getattr(conv, "diff_snapshot_json", None) or {},
            cleanup_status=getattr(conv, "cleanup_status", "") or "retained",
            cleanup_error=getattr(conv, "cleanup_error", "") or "",
        )
        metadata_by_id = {
            str(item.get("site_id") or ""): item
            for item in git_repos
        }
        remaining_bytes = 4_000_000
        for repository in state["repositories"]:
            item = metadata_by_id.get(str(repository.get("site_id") or ""))
            file_snapshots: dict[str, Any] = {}
            if item is not None:
                for file_meta in repository.get("files") or []:
                    try:
                        detail = conversation_git_service.file_diff(
                            project_id=str(conv.project_id or ""),
                            conversation_id=str(conv.id),
                            worktree_root=str(conv.worktree_root or ""),
                            item=item,
                            file_meta=dict(file_meta),
                        )
                    except (HTTPException, RuntimeError, OSError):
                        continue
                    size = len(str(detail.get("before") or "").encode("utf-8")) + len(
                        str(detail.get("after") or "").encode("utf-8")
                    )
                    if size > remaining_bytes:
                        continue
                    remaining_bytes -= size
                    file_snapshots[str(detail["path"])] = detail
            repository["file_snapshots"] = file_snapshots
        return {"repositories": state["repositories"]}

    async def _perform_git_cleanup(
        self,
        db: AsyncSession,
        conv: Conversation,
        *,
        force: bool,
    ) -> None:
        conv.cleanup_status = "cleaning"
        conv.cleanup_error = ""
        await db.commit()
        updated, errors = conversation_git_service.cleanup_conversation_worktrees(
            project_id=str(conv.project_id or ""),
            conversation_id=str(conv.id),
            provider=str(conv.provider or ""),
            worktree_root=str(conv.worktree_root or ""),
            git_repos=list(getattr(conv, "git_repos_json", None) or []),
            force=force,
        )
        if not errors:
            try:
                self._remove_provider_session_state(conv)
                conv.provider_session_id = ""
            except Exception as exc:
                errors.append(f"编程工具会话状态清理失败: {exc}")
        conv.git_repos_json = updated
        conv.cleanup_status = "warning" if errors else "cleaned"
        conv.cleanup_error = "\n".join(errors)[:4000]
        await db.commit()

    @staticmethod
    def _remove_provider_session_state(conv: Conversation) -> None:
        provider = str(getattr(conv, "provider", "") or "").strip()
        conversation_id = str(getattr(conv, "id", "") or "").strip()
        if not provider or not conversation_id:
            return
        root = Path(get_settings().programming_session_root).resolve()
        candidate = root / provider / conversation_id
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RuntimeError("编程工具会话状态目录越界") from exc
        if candidate.is_symlink():
            raise RuntimeError("编程工具会话状态目录不能是符号链接")
        if candidate.exists():
            shutil.rmtree(candidate)

    async def cleanup_completed_conversation(self, db: AsyncSession, conv_id: str) -> Conversation:
        conv = await db.get(Conversation, conv_id)
        if conv is None:
            raise RuntimeError("Completion conversation no longer exists")
        if (getattr(conv, "completion_status", "") or "active") != "completed":
            raise RuntimeError("Conversation merge is not completed")
        if getattr(conv, "cleanup_status", "") == "cleaned":
            return conv
        conv.git_repos_json = conversation_git_service.verify_completed_repositories(
            list(getattr(conv, "git_repos_json", None) or [])
        )
        await db.commit()
        if not getattr(conv, "diff_snapshot_json", None):
            await self._snapshot_git_state(db, conv)
        await self._perform_git_cleanup(db, conv, force=False)
        await db.refresh(conv)
        return conv

    async def cleanup_conversation(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
    ) -> Conversation:
        async with self._lifecycle_lock(conv_id):
            return await self._cleanup_conversation_locked(db, conv_id, current_user)

    async def _cleanup_conversation_locked(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
    ) -> Conversation:
        conv = await self.get_conversation(db, conv_id, current_user)
        if (getattr(conv, "scope_type", "") or "site") != "project":
            raise HTTPException(status_code=409, detail="仅项目开发会话需要 Git 清理")
        completion_status = getattr(conv, "completion_status", "") or "active"
        if completion_status == "merging":
            raise HTTPException(status_code=409, detail="会话正在合并中，不能清理")
        if getattr(conv, "cleanup_status", "") == "cleaned":
            return conv
        if completion_status == "completed":
            force = False
            try:
                conv.git_repos_json = conversation_git_service.verify_completed_repositories(
                    list(getattr(conv, "git_repos_json", None) or [])
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            await db.commit()
        elif conv.status == "archived" or completion_status == "discarded":
            force = True
        else:
            raise HTTPException(status_code=409, detail="只能清理已合并或已归档的项目会话")
        await self._snapshot_git_state(db, conv)
        await self._perform_git_cleanup(db, conv, force=force)
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
        del db, conv_id, site_id
        return user_message.strip()

    # ── Send Message (orchestrator) ─────────────────────

    async def send_message(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
        content: str,
        provider: str = "codex",
        repo_ids: list[str] | None = None,
        current_url: str = "",
        selected_xpath: str = "",
        console_errors: str = "",
    ) -> dict[str, Any]:
        async with self._lifecycle_lock(conv_id):
            return await self._send_message_locked(
                db,
                conv_id,
                current_user,
                content,
                provider,
                repo_ids,
                current_url,
                selected_xpath,
                console_errors,
            )

    async def _send_message_locked(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
        content: str,
        provider: str = "codex",
        repo_ids: list[str] | None = None,
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
        conversation_status = str(getattr(conv, "status", "") or "active")
        completion_status = str(getattr(conv, "completion_status", "") or "active")
        if conversation_status in {"archived", "archiving"}:
            raise HTTPException(status_code=409, detail="会话已归档或正在归档，不能继续发送消息")
        if completion_status in {"merging", "completed", "discarded"}:
            raise HTTPException(status_code=409, detail="会话正在合并或已结束，不能继续发送消息")
        scope_type = getattr(conv, "scope_type", "") or "site"
        default_title = _is_default_title(conv.title)

        if scope_type == "project":
            project_id = str(conv.project_id or "")
            conversation_provider = getattr(conv, "provider", "") or "codex"
            if provider != conversation_provider:
                raise HTTPException(
                    status_code=409,
                    detail=f"该会话固定使用 {task_service._provider_label(conversation_provider)}，不能切换编程工具",
                )
            default_repo_ids = list(getattr(conv, "repo_ids_json", None) or [])
            requested_repo_ids = [str(item).strip() for item in (repo_ids or []) if str(item).strip()]
            if requested_repo_ids and set(requested_repo_ids) != set(default_repo_ids):
                raise HTTPException(status_code=409, detail="会话创建后不能更改参与仓库，请新建会话")
            _, sites, selected_repo_ids = await self._resolve_project_repos(
                db,
                project_id,
                current_user,
                default_repo_ids,
            )
            primary_site = sites[0]
            conv.site_id = primary_site.id
            conv.repo_ids_json = selected_repo_ids
            await task_service.require_configured_provider(
                db,
                current_user=current_user,
                provider=provider,
                project_id=project_id,
            )
            if default_title:
                new_title = _short_title(content)
                git_repos = list(getattr(conv, "git_repos_json", None) or [])
                if git_repos:
                    branch_name, git_repos = conversation_git_service.rename_worktree_branch(
                        git_repos=git_repos,
                        conversation_id=str(conv.id),
                        title=new_title,
                        provider=getattr(conv, "provider", "") or provider,
                        current_branch=getattr(conv, "branch_name", "") or "",
                    )
                    conv.branch_name = branch_name
                    conv.git_repos_json = git_repos
                conv.title = new_title
            user_metadata = {
                "scope_type": "project",
                "project_id": project_id,
                "repo_ids": selected_repo_ids,
                "provider": provider,
                "branch_name": getattr(conv, "branch_name", "") or "",
            }
            user_msg = await self.add_message(
                db,
                conv_id,
                role="user",
                content=content,
                provider=provider,
                metadata=user_metadata,
            )

            prompt = await self.build_context_prompt(db, conv_id, content, primary_site.id)
            task_payload = {
                "repo_ids": selected_repo_ids,
                "provider": provider,
                "title": _short_title(content),
                "prompt": prompt,
                "priority": "medium",
                "conversation_id": conv_id,
                "provider_session_id": getattr(conv, "provider_session_id", "") or "",
                "current_url": current_url,
                "selected_xpath": selected_xpath,
                "console_errors": console_errors,
            }
            task = await task_service.create_project_task(
                db=db,
                current_user=current_user,
                project_id=project_id,
                payload_data=task_payload,
                enqueue=True,
            )
            task_detail = await task_service.serialize_task_detail(db, task)
            assistant_msg = await self.add_message(
                db,
                conv_id,
                role="assistant",
                content="任务已创建，正在处理中...",
                message_type="task_ref",
                provider=provider,
                task_id=str(task.id),
                metadata={
                    "scope_type": "project",
                    "project_id": project_id,
                    "repo_ids": selected_repo_ids,
                    "provider": provider,
                    "branch_name": getattr(conv, "branch_name", "") or "",
                    "task_snapshot": task_detail,
                },
            )
            return {
                "user_message": self.serialize_message(user_msg),
                "assistant_message": self.serialize_message(assistant_msg),
                "task_id": str(task.id),
                "task": task_detail,
            }

        if default_title:
            conv.title = _short_title(content)
        site = await db.get(Site, conv.site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Site not found")
        await task_service.require_configured_provider(
            db,
            current_user=current_user,
            provider=provider,
            project_id=str(site.project_id) if site.project_id else None,
        )

        # 1. Save user message
        user_msg = await self.add_message(
            db,
            conv_id,
            role="user",
            content=content,
            provider=provider,
            metadata={
                "scope_type": "site",
                "site_id": site.site_id,
                "repo_ids": [site.site_id],
                "provider": provider,
            },
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
            "provider_session_id": getattr(conv, "provider_session_id", "") or "",
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
            metadata={
                "scope_type": "site",
                "site_id": site.site_id,
                "repo_ids": [site.site_id],
                "provider": provider,
                "task_snapshot": task_service.serialize_task(task),
            },
        )

        return {
            "user_message": self.serialize_message(user_msg),
            "assistant_message": self.serialize_message(assistant_msg),
            "task_id": str(task.id),
            "task": task_service.serialize_task(task),
        }

    # ── Conversation Git lifecycle ──────────────────────

    async def get_git_state(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
    ) -> dict[str, Any]:
        conv = await self.get_conversation(db, conv_id, current_user)
        git_repos = list(getattr(conv, "git_repos_json", None) or [])
        return conversation_git_service.conversation_state(
            branch_name=getattr(conv, "branch_name", "") or "",
            provider=getattr(conv, "provider", "") or "",
            completion_status=getattr(conv, "completion_status", "") or "active",
            worktree_root=getattr(conv, "worktree_root", "") or "",
            git_repos=git_repos,
            diff_snapshot=getattr(conv, "diff_snapshot_json", None) or {},
            cleanup_status=getattr(conv, "cleanup_status", "") or "retained",
            cleanup_error=getattr(conv, "cleanup_error", "") or "",
        )

    async def get_git_file_diff(
        self,
        db: AsyncSession,
        conv_id: str,
        repo_id: str,
        path: str,
        current_user: object,
    ) -> dict[str, Any]:
        conv = await self.get_conversation(db, conv_id, current_user)
        if (getattr(conv, "scope_type", "") or "site") != "project":
            raise HTTPException(status_code=409, detail="仅项目开发会话支持文件对比")
        state = await self.get_git_state(db, conv_id, current_user)
        repository = next(
            (
                repo
                for repo in (state.get("repositories") or [])
                if str(repo.get("site_id") or "") == str(repo_id)
            ),
            None,
        )
        if repository is None:
            raise HTTPException(status_code=404, detail="会话仓库不存在")
        normalized_path = conversation_git_service._validated_relative_path(path)
        file_meta = next(
            (
                dict(item)
                for item in (repository.get("files") or [])
                if str(item.get("path") or "") == normalized_path
            ),
            None,
        )
        if file_meta is None:
            raise HTTPException(status_code=404, detail="该文件不在会话修改列表中")
        snapshot_repository = next(
            (
                repo
                for repo in ((getattr(conv, "diff_snapshot_json", None) or {}).get("repositories") or [])
                if str(repo.get("site_id") or "") == str(repo_id)
            ),
            None,
        )
        snapshot_file = (
            (snapshot_repository.get("file_snapshots") or {}).get(normalized_path)
            if snapshot_repository and repository.get("snapshot")
            else None
        )
        if isinstance(snapshot_file, dict):
            return dict(snapshot_file)
        item = self._conversation_git_repo(conv, repo_id)
        try:
            return conversation_git_service.file_diff(
                project_id=str(conv.project_id or ""),
                conversation_id=str(conv.id),
                worktree_root=str(conv.worktree_root or ""),
                item=item,
                file_meta=file_meta,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @staticmethod
    def _conversation_git_repo(conv: Conversation, repo_id: str) -> dict[str, Any]:
        git_repos = list(getattr(conv, "git_repos_json", None) or [])
        item = next(
            (
                dict(repo)
                for repo in git_repos
                if str(repo.get("site_id") or "") == str(repo_id)
            ),
            None,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Repo not found in this conversation")
        return item

    async def get_git_graph(
        self,
        db: AsyncSession,
        conv_id: str,
        repo_id: str,
        current_user: object,
        *,
        limit: int = 200,
        skip: int = 0,
    ) -> dict[str, Any]:
        from backend.services.git_history_service import git_history_service

        conv = await self.get_conversation(db, conv_id, current_user)
        if (getattr(conv, "scope_type", "") or "site") != "project":
            raise HTTPException(status_code=409, detail="仅项目开发会话支持 Git 图谱")
        item = self._conversation_git_repo(conv, repo_id)
        project_id = str(conv.project_id or "")
        name = str(item.get("name") or "").strip()
        if not project_id or not name:
            raise HTTPException(status_code=409, detail="会话仓库元数据不完整")
        expected_repo = project_service.repo_root(project_id, name)
        repo = git_history_service.ensure_repository_path(
            expected_repo,
            item.get("repo_path"),
            boundary=project_service.project_root(project_id),
        )
        branch = str(item.get("branch_name") or conv.branch_name or "").strip()
        main_branch = str(item.get("main_branch") or "").strip()
        branch_exists = git_history_service.local_branch_exists(repo, branch)
        recorded_tip = str(item.get("branch_tip_sha") or "").strip().lower()
        if not branch_exists and not recorded_tip:
            raise HTTPException(status_code=409, detail="任务分支已删除且没有可用的 Commit 快照")
        revisions = [main_branch, branch if branch_exists else recorded_tip]
        return git_history_service.graph(
            repo=repo,
            site_id=str(item.get("site_id") or repo_id),
            name=name,
            branch=branch,
            default_branch=main_branch,
            scope="conversation",
            revisions=revisions,
            head_revision="" if branch_exists else recorded_tip,
            limit=limit,
            skip=skip,
        )

    async def rollback_repo_to_commit(
        self,
        db: AsyncSession,
        conv_id: str,
        repo_id: str,
        current_user: object,
        *,
        commit_sha: str,
    ) -> tuple[object, dict[str, Any]]:
        from backend.models.repo_git_operation import RepoGitOperation
        from backend.models.task import TaskStatus
        from backend.services.git_history_service import COMMIT_SHA_PATTERN, git_history_service

        if not COMMIT_SHA_PATTERN.fullmatch(commit_sha or ""):
            raise HTTPException(status_code=400, detail="commit_sha 必须是完整的 40 位 Commit SHA")
        async with self._lifecycle_lock(conv_id):
            conv = await self.get_conversation(db, conv_id, current_user)
            if (getattr(conv, "scope_type", "") or "site") != "project":
                raise HTTPException(status_code=409, detail="仅项目开发会话支持任务分支回滚")
            conversation_status = str(getattr(conv, "status", "") or "active")
            completion_status = str(getattr(conv, "completion_status", "") or "active")
            if conversation_status in {"archived", "archiving"}:
                raise HTTPException(status_code=409, detail="已归档或正在归档的会话不能回滚")
            if completion_status in {"merging", "completed", "discarded"}:
                raise HTTPException(status_code=409, detail="正在合并或已结束的会话不能回滚")
            if completion_status == "failed":
                git_repos = list(getattr(conv, "git_repos_json", None) or [])
                try:
                    merged_changes = any(
                        conversation_git_service.has_merged_changes(repo)
                        for repo in git_repos
                    )
                except RuntimeError as exc:
                    raise HTTPException(status_code=409, detail=f"无法确认失败会话的合并状态: {exc}") from exc
                if merged_changes:
                    raise HTTPException(
                        status_code=409,
                        detail="失败会话已有任务分支改动进入主分支，不能再回滚任务分支",
                    )
            tasks = await self._conversation_tasks(db, conv)
            if any(
                getattr(task.status, "value", task.status) in {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value}
                for task in tasks
            ):
                raise HTTPException(status_code=409, detail="会话仍有排队中或运行中的任务，不能回滚")

            item = self._conversation_git_repo(conv, repo_id)
            project_id = str(conv.project_id or "")
            name = str(item.get("name") or "").strip()
            branch = str(item.get("branch_name") or conv.branch_name or "").strip()
            expected_prefix = f"{conversation_git_service._provider_prefix(conv.provider)}/"
            if not branch.startswith(expected_prefix) or branch != str(conv.branch_name or ""):
                raise HTTPException(status_code=409, detail="任务分支与会话元数据不一致")
            expected_repo = project_service.repo_root(project_id, name)
            repo = git_history_service.ensure_repository_path(
                expected_repo,
                item.get("repo_path"),
                boundary=project_service.project_root(project_id),
            )
            expected_root = project_service.project_root(project_id) / ".worktree" / conv_id
            configured_root = Path(str(conv.worktree_root or "")).resolve(strict=False)
            if configured_root != expected_root.resolve(strict=False):
                raise HTTPException(status_code=409, detail="会话 worktree 根目录与项目元数据不一致")
            worktree = git_history_service.ensure_worktree_path(
                expected_root / name,
                str(item.get("worktree_path") or ""),
                boundary=expected_root,
            )

            operation = RepoGitOperation(
                project_id=project_id,
                site_id=str(item.get("site_id") or repo_id),
                conversation_id=conv_id,
                user_id=str(getattr(current_user, "id", "")),
                scope="conversation",
                operation="rollback",
                repo_name=name,
                branch=branch,
                target_sha=commit_sha.lower(),
                status="running",
            )
            db.add(operation)
            await db.commit()
            try:
                before_sha, after_sha = git_history_service.rollback_branch(
                    repo=repo,
                    branch=branch,
                    target_sha=commit_sha,
                    expected_worktree=worktree,
                )
                updated_repos: list[dict[str, Any]] = []
                for original in list(conv.git_repos_json or []):
                    updated = dict(original)
                    if str(updated.get("site_id") or "") == str(repo_id):
                        updated["branch_tip_sha"] = after_sha
                        updated["rollback_before_sha"] = before_sha
                        updated["rollback_target_sha"] = after_sha
                    updated_repos.append(updated)
                conv.git_repos_json = updated_repos
                operation.before_sha = before_sha
                operation.after_sha = after_sha
                operation.status = "success"
                operation.error = ""
                await db.commit()
                await db.refresh(operation)
            except Exception as exc:
                operation.status = "failed"
                operation.error = str(getattr(exc, "detail", exc))[:2000]
                await db.commit()
                raise

            graph = await self.get_git_graph(
                db,
                conv_id,
                repo_id,
                current_user,
            )
            return operation, graph

    @staticmethod
    def _completion_prompt(conv: Conversation, git_repos: list[dict[str, Any]]) -> str:
        repo_lines = []
        for item in git_repos:
            repo_lines.append(
                f"- 仓库 {item['name']}：进入 {item['name']}，将任务分支 "
                f"{item['branch_name']} 合并到主分支 {item['main_branch']}"
            )
        return (
            "这是纯 Git Merge、Push 任务：不要运行任何测试，不要做代码审查，不要修改业务代码，"
            "也不要执行与合并、推送无关的操作。请在每个仓库中切换到指定主分支，"
            "使用 git merge --no-ff 合并任务分支；若有冲突，只做完成 Merge 所需的冲突处理并提交。"
            "系统已经基于最新远端主分支完成 fetch 和 rebase，不要再次 fetch 或 rebase。"
            "Merge 成功后由系统自动 Push 到 origin 并校验远端结果，不要手动 push。"
            "不要删除任务分支或 worktree。最后只向用户说明 Merge、Push 结果。\n\n"
            f"会话：{conv.title}\n"
            + "\n".join(repo_lines)
        )

    async def _git_remote_auth(
        self,
        db: AsyncSession,
        git_repos: list[dict[str, Any]],
    ) -> dict[str, dict[str, str]]:
        site_db_ids = [
            str(item.get("site_db_id") or "").strip()
            for item in git_repos
            if str(item.get("site_db_id") or "").strip()
        ]
        if not site_db_ids:
            return {}
        sites_result = await db.execute(select(Site).where(Site.id.in_(site_db_ids)))
        sites = {str(site.id): site for site in sites_result.scalars().all()}
        clone_result = await db.execute(
            select(AgentTask)
            .where(AgentTask.site_id.in_(site_db_ids), AgentTask.task_type == "clone_repo")
            .order_by(desc(AgentTask.created_at), desc(AgentTask.id))
        )
        latest_clone: dict[str, AgentTask] = {}
        for task in clone_result.scalars().all():
            latest_clone.setdefault(str(task.site_id), task)

        from backend.core.encryption import decrypt_api_key

        result: dict[str, dict[str, str]] = {}
        for site_db_id, site in sites.items():
            config = getattr(site, "config", {}) or {}
            git_source = config.get("git_source") if isinstance(config, dict) else {}
            git_source = git_source if isinstance(git_source, dict) else {}
            clone_task = latest_clone.get(site_db_id)
            clone_payload = getattr(clone_task, "payload_json", None) or {}
            stored_url = str(git_source.get("url") or clone_payload.get("git_url") or "")
            embedded_username, embedded_password = site_service.git_url_credentials(stored_url)
            password = (
                decrypt_api_key(str(clone_payload.get("git_password_encrypted") or ""))
                or embedded_password
            )
            result[site_db_id] = {
                "remote_url": conversation_git_service._strip_url_credentials(
                    stored_url
                ),
                "username": str(
                    git_source.get("username")
                    or clone_payload.get("git_username")
                    or embedded_username
                    or ""
                ),
                "password": password,
            }
            result[str(site.site_id)] = result[site_db_id]
        return result

    async def complete_conversation(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
    ) -> dict[str, Any]:
        async with self._lifecycle_lock(conv_id):
            return await self._complete_conversation_locked(db, conv_id, current_user)

    async def _complete_conversation_locked(
        self,
        db: AsyncSession,
        conv_id: str,
        current_user: object,
    ) -> dict[str, Any]:
        conv = await self.get_conversation(db, conv_id, current_user)
        if (getattr(conv, "scope_type", "") or "site") != "project":
            raise HTTPException(status_code=409, detail="仅项目开发会话支持分支合并")
        if str(getattr(conv, "status", "") or "active") in {"archived", "archiving"}:
            raise HTTPException(status_code=409, detail="已归档或正在归档的会话不能合并")
        completion_status = getattr(conv, "completion_status", "") or "active"
        if completion_status == "merging":
            raise HTTPException(status_code=409, detail="会话正在合并中")
        if completion_status == "completed":
            raise HTTPException(status_code=409, detail="会话已经合并")
        if completion_status == "discarded":
            raise HTTPException(status_code=409, detail="会话已经丢弃")
        git_repos = list(getattr(conv, "git_repos_json", None) or [])
        if not git_repos:
            raise HTTPException(status_code=409, detail="会话没有可合并的 worktree")

        tasks = await self._conversation_tasks(db, conv)
        running = [
            task for task in tasks
            if getattr(task.status, "value", task.status) in {"queued", "running"}
        ]
        if running:
            raise HTTPException(status_code=409, detail="仍有开发任务正在执行，请等待任务结束后再合并会话")
        try:
            remote_auth = await self._git_remote_auth(db, git_repos)
            git_repos = conversation_git_service.prepare_repositories_for_completion(
                git_repos,
                remote_auth=remote_auth,
            )
            git_repos = conversation_git_service.capture_repository_tips(
                git_repos,
                require_clean=True,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        conv.git_repos_json = git_repos

        conv.diff_snapshot_json = self._build_git_diff_snapshot(conv)
        conv.completion_status = "merging"
        conv.completion_error = ""
        conv.cleanup_status = "retained"
        conv.cleanup_error = ""
        await db.commit()

        provider = getattr(conv, "provider", "") or "codex"
        payload = {
            "repo_ids": list(getattr(conv, "repo_ids_json", None) or []),
            "provider": provider,
            "title": f"合并会话：{conv.title}"[:255],
            "prompt": self._completion_prompt(conv, git_repos),
            "priority": "high",
            "conversation_id": conv_id,
            "completion_mode": True,
            "completion_conversation_id": conv_id,
        }
        try:
            task = await task_service.create_project_task(
                db=db,
                current_user=current_user,
                project_id=str(conv.project_id),
                payload_data=payload,
                enqueue=False,
            )
            task.conversation_id = conv_id
            conv.completion_task_id = str(task.id)
            await db.commit()
            task_detail = await task_service.serialize_task_detail(db, task)
            assistant_msg = await self.add_message(
                db,
                conv_id,
                role="assistant",
                content=f"正在使用 {task_service._provider_label(provider)} 合并会话分支，成功后将自动推送到远端...",
                message_type="task_ref",
                provider=provider,
                task_id=str(task.id),
                metadata={
                    "scope_type": "project",
                    "project_id": str(conv.project_id),
                    "repo_ids": list(getattr(conv, "repo_ids_json", None) or []),
                    "provider": provider,
                    "completion_mode": True,
                    "task_snapshot": task_detail,
                },
            )
            if task_service.enqueue_task(task) is False:
                raise RuntimeError("合并任务入队失败，请稍后重试")
        except Exception as exc:
            conv.completion_status = "failed"
            conv.completion_error = str(exc)
            await db.commit()
            raise
        await db.refresh(conv)
        return {
            "conversation": self.serialize_conversation(conv),
            "assistant_message": self.serialize_message(assistant_msg),
            "task_id": str(task.id),
            "task": task_detail,
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
            "metadata": _json_dict(getattr(msg, "metadata_json", "") or "{}"),
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }

    @staticmethod
    def serialize_conversation(conv: Conversation) -> dict[str, Any]:
        return {
            "id": str(conv.id),
            "site_id": str(conv.site_id),
            "scope_type": getattr(conv, "scope_type", "") or "site",
            "project_id": str(getattr(conv, "project_id", "") or ""),
            "repo_ids": list(getattr(conv, "repo_ids_json", None) or []),
            "provider": getattr(conv, "provider", "") or "codex",
            "branch_name": getattr(conv, "branch_name", "") or "",
            "worktree_root": getattr(conv, "worktree_root", "") or "",
            "completion_status": getattr(conv, "completion_status", "") or "active",
            "completion_task_id": getattr(conv, "completion_task_id", "") or "",
            "completion_error": getattr(conv, "completion_error", "") or "",
            "cleanup_status": getattr(conv, "cleanup_status", "") or "retained",
            "cleanup_error": getattr(conv, "cleanup_error", "") or "",
            "completed_at": conv.completed_at.isoformat() if getattr(conv, "completed_at", None) else None,
            "title": conv.title,
            "status": conv.status,
            "summary_text": conv.summary_text or "",
            "message_count": conv.message_count,
            "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        }


conversation_service = ConversationService()
