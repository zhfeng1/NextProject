from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable


class CompatibilityBridge:
    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id
        self.logs: deque[str] = deque(maxlen=400)
        self.mcp_process: subprocess.Popen[str] | None = None
        self.login_process: subprocess.Popen[str] | None = None
        self.mcp_lock = threading.Lock()
        self.login_lock = threading.Lock()
        self.stopping = False
        self.codex_home = Path(os.getenv("CODEX_HOME", "/root/.codex"))
        self.claude_home = Path(os.getenv("CLAUDE_HOME", "/root/.claude"))
        self.claude_config_home = Path(os.getenv("CLAUDE_CONFIG_HOME", "/root/.config/claude-code"))

    def append_log(self, line: str) -> None:
        self.logs.append(f"[{time.strftime('%H:%M:%S')}] {line.rstrip()}")

    def _pump(self, process: subprocess.Popen[str], prefix: str, on_exit: Callable[[], None] | None = None) -> None:
        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                if not line:
                    break
                self.append_log(f"{prefix}{line}")
        process.wait()
        self.append_log(f"{prefix}进程退出，code={process.returncode}")
        if on_exit and not self.stopping:
            on_exit()

    def _env(self) -> dict[str, str]:
        env = {**os.environ, "HOME": "/root"}
        if self.tool_id == "codex":
            env["CODEX_HOME"] = str(self.codex_home)
        if self.tool_id == "claude_code":
            env["CLAUDE_HOME"] = str(self.claude_home)
        return env

    def start(self) -> None:
        if os.getenv("ENABLE_MCP_BRIDGE", "true").lower() not in {"1", "true", "yes"}:
            return
        if self.tool_id == "codex":
            self.codex_home.mkdir(parents=True, exist_ok=True)
            self.start_mcp()
        elif self.tool_id == "claude_code":
            self.claude_home.mkdir(parents=True, exist_ok=True)
            self.claude_config_home.mkdir(parents=True, exist_ok=True)
            self.start_mcp()

    def stop(self) -> None:
        self.stopping = True
        for process in (self.login_process, self.mcp_process):
            if process and process.poll() is None:
                process.terminate()

    def start_mcp(self) -> None:
        command = {
            "codex": ["codex", "mcp-server"],
            "claude_code": ["claude", "mcp", "serve"],
        }.get(self.tool_id)
        if not command:
            return
        with self.mcp_lock:
            if self.mcp_process and self.mcp_process.poll() is None:
                return
            self.append_log(f"正在启动 {' '.join(command)} ...")
            try:
                self.mcp_process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=self._env(),
                )
            except OSError as exc:
                self.append_log(f"MCP 启动失败: {type(exc).__name__}")
                self.mcp_process = None
                return
            threading.Thread(
                target=self._pump,
                args=(self.mcp_process, "[mcp] ", self.start_mcp),
                daemon=True,
            ).start()

    def mcp_status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "available": self.tool_id in {"codex", "claude_code"},
            "running": bool(self.mcp_process and self.mcp_process.poll() is None),
        }

    def _auth_files(self) -> tuple[Path, ...]:
        if self.tool_id == "codex":
            return (self.codex_home / "auth.json",)
        return (
            self.claude_home / ".credentials.json",
            self.claude_home / "credentials.json",
            self.claude_config_home / "auth.json",
            self.claude_config_home / "credentials.json",
        )

    def authenticated(self) -> bool:
        return any(path.exists() and path.stat().st_size > 0 for path in self._auth_files())

    def auth_status(self) -> dict[str, Any]:
        joined_logs = "\n".join(list(self.logs)[-80:])
        url_match = re.search(r"https?://\S+", joined_logs)
        code_match = re.search(r"\b[A-Z0-9]{4,}(?:-[A-Z0-9]{4,})+\b", joined_logs)
        running = bool(self.login_process and self.login_process.poll() is None)
        result = {
            "authenticated": self.authenticated(),
            "login_running": running,
            "verification_url": url_match.group(0) if url_match else "",
            "user_code": code_match.group(0) if code_match else "",
            "recent_logs": list(self.logs)[-20:],
        }
        if self.tool_id == "codex":
            result["auth_file"] = str(self._auth_files()[0])
        else:
            result["auth_files"] = [str(path) for path in self._auth_files()]
        return result

    def start_auth(self) -> dict[str, Any]:
        command = {
            "codex": ["codex", "login", "--device-auth"],
            "claude_code": ["claude", "login"],
        }.get(self.tool_id)
        if not command:
            raise ValueError("authentication is not available for this tool")
        with self.login_lock:
            if self.login_process and self.login_process.poll() is None:
                return {"ok": True, "started": False, "message": "已有登录流程在进行中"}
            self.append_log(f"开始执行 {' '.join(command)}")
            self.login_process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=self._env(),
            )
            prefix = "[oauth] " if self.tool_id == "codex" else "[login] "
            threading.Thread(target=self._pump, args=(self.login_process, prefix), daemon=True).start()
            return {"ok": True, "started": True}

    def cancel_auth(self) -> dict[str, Any]:
        with self.login_lock:
            if self.login_process and self.login_process.poll() is None:
                self.login_process.terminate()
                return {"ok": True, "message": "已停止当前登录流程"}
            return {"ok": True, "message": "当前没有正在进行的登录流程"}
