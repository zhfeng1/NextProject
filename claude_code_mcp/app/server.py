import os
import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI

app = FastAPI(title="Claude Code MCP Bridge")

CLAUDE_HOME = Path(os.getenv("CLAUDE_HOME", "/root/.claude"))
CLAUDE_CONFIG_HOME = Path(os.getenv("CLAUDE_CONFIG_HOME", "/root/.config/claude-code"))
AUTH_CANDIDATES = (
    CLAUDE_HOME / ".credentials.json",
    CLAUDE_HOME / "credentials.json",
    CLAUDE_CONFIG_HOME / "auth.json",
    CLAUDE_CONFIG_HOME / "credentials.json",
)

MAX_LOG_LINES = 400
log_buffer: deque[str] = deque(maxlen=MAX_LOG_LINES)

mcp_process: Optional[subprocess.Popen] = None
login_process: Optional[subprocess.Popen] = None
mcp_lock = threading.Lock()
login_lock = threading.Lock()


def append_log(line: str) -> None:
    log_buffer.append(f"[{time.strftime('%H:%M:%S')}] {line.rstrip()}")


def pump_output(proc: subprocess.Popen, prefix: str, on_exit=None) -> None:
    if not proc.stdout:
        return
    for line in iter(proc.stdout.readline, ""):
        if not line:
            break
        append_log(f"{prefix}{line}")
    proc.wait()
    append_log(f"{prefix}进程退出，code={proc.returncode}")
    if on_exit:
        on_exit()


def bridge_env() -> dict[str, str]:
    return {
        **os.environ,
        "HOME": "/root",
        "CLAUDE_HOME": str(CLAUDE_HOME),
    }


def has_auth_file() -> bool:
    return any(path.exists() and path.stat().st_size > 0 for path in AUTH_CANDIDATES)


def start_mcp_server() -> None:
    global mcp_process
    with mcp_lock:
        if mcp_process and mcp_process.poll() is None:
            return
        append_log("正在启动 claude mcp serve ...")
        mcp_process = subprocess.Popen(
            ["claude", "mcp", "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=bridge_env(),
        )
        threading.Thread(
            target=pump_output,
            args=(mcp_process, "[mcp] "),
            kwargs={"on_exit": start_mcp_server},
            daemon=True,
        ).start()


def start_login() -> Dict[str, Any]:
    global login_process
    with login_lock:
        if login_process and login_process.poll() is None:
            return {"ok": True, "started": False, "message": "已有登录流程在进行中"}

        CLAUDE_HOME.mkdir(parents=True, exist_ok=True)
        CLAUDE_CONFIG_HOME.mkdir(parents=True, exist_ok=True)
        append_log("开始执行 claude login")
        login_process = subprocess.Popen(
            ["claude", "login"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=bridge_env(),
        )
        threading.Thread(target=pump_output, args=(login_process, "[login] "), daemon=True).start()
        return {"ok": True, "started": True}


def auth_status() -> Dict[str, Any]:
    running = bool(login_process and login_process.poll() is None)
    joined_logs = "\n".join(list(log_buffer)[-80:])
    url_match = re.search(r"https?://\S+", joined_logs)
    code_match = re.search(r"\b[A-Z0-9]{4,}(?:-[A-Z0-9]{4,})+\b", joined_logs)

    return {
        "authenticated": has_auth_file(),
        "login_running": running,
        "auth_files": [str(path) for path in AUTH_CANDIDATES],
        "verification_url": url_match.group(0) if url_match else "",
        "user_code": code_match.group(0) if code_match else "",
        "recent_logs": list(log_buffer)[-20:],
    }


@app.on_event("startup")
def on_startup() -> None:
    CLAUDE_HOME.mkdir(parents=True, exist_ok=True)
    CLAUDE_CONFIG_HOME.mkdir(parents=True, exist_ok=True)
    start_mcp_server()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "mcp_running": bool(mcp_process and mcp_process.poll() is None),
        "authenticated": has_auth_file(),
    }


@app.get("/auth/status")
def get_auth_status() -> Dict[str, Any]:
    return auth_status()


@app.post("/auth/start")
def post_auth_start() -> Dict[str, Any]:
    return start_login()


@app.get("/auth/logs")
def get_auth_logs() -> Dict[str, Any]:
    return {"ok": True, "logs": list(log_buffer)}


@app.post("/auth/cancel")
def cancel_auth() -> Dict[str, Any]:
    global login_process
    with login_lock:
        if login_process and login_process.poll() is None:
            login_process.terminate()
            return {"ok": True, "message": "已停止当前登录流程"}
        return {"ok": True, "message": "当前没有正在进行的登录流程"}


@app.get("/mcp/status")
def mcp_status() -> Dict[str, Any]:
    running = bool(mcp_process and mcp_process.poll() is None)
    return {"ok": True, "running": running}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8091)
