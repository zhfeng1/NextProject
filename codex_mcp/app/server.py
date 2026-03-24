import os
import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Codex MCP Bridge")

CODEX_HOME = Path(os.getenv("CODEX_HOME", "/root/.codex"))
AUTH_FILE = CODEX_HOME / "auth.json"

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


def start_mcp_server() -> None:
    global mcp_process
    with mcp_lock:
        if mcp_process and mcp_process.poll() is None:
            return
        append_log("正在启动 codex mcp-server ...")
        mcp_process = subprocess.Popen(
            ["codex", "mcp-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "CODEX_HOME": str(CODEX_HOME)},
        )
        threading.Thread(
            target=pump_output,
            args=(mcp_process, "[mcp] "),
            kwargs={"on_exit": start_mcp_server},
            daemon=True,
        ).start()


def start_device_auth() -> Dict[str, Any]:
    global login_process
    with login_lock:
        if login_process and login_process.poll() is None:
            return {"ok": True, "started": False, "message": "已有登录流程在进行中"}

        CODEX_HOME.mkdir(parents=True, exist_ok=True)
        append_log("开始执行 codex login --device-auth")
        login_process = subprocess.Popen(
            ["codex", "login", "--device-auth"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "CODEX_HOME": str(CODEX_HOME)},
        )
        threading.Thread(target=pump_output, args=(login_process, "[oauth] "), daemon=True).start()
        return {"ok": True, "started": True}


def oauth_status() -> Dict[str, Any]:
    authenticated = AUTH_FILE.exists() and AUTH_FILE.stat().st_size > 0
    running = bool(login_process and login_process.poll() is None)

    joined_logs = "\n".join(list(log_buffer)[-80:])
    url_match = re.search(r"https?://\S+", joined_logs)
    code_match = re.search(r"\b[A-Z0-9]{4,}(?:-[A-Z0-9]{4,})+\b", joined_logs)

    return {
        "authenticated": authenticated,
        "login_running": running,
        "auth_file": str(AUTH_FILE),
        "verification_url": url_match.group(0) if url_match else "",
        "user_code": code_match.group(0) if code_match else "",
        "recent_logs": list(log_buffer)[-20:],
    }


@app.on_event("startup")
def on_startup() -> None:
    CODEX_HOME.mkdir(parents=True, exist_ok=True)
    start_mcp_server()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "mcp_running": bool(mcp_process and mcp_process.poll() is None),
        "authenticated": AUTH_FILE.exists() and AUTH_FILE.stat().st_size > 0,
    }


@app.get("/oauth/status")
def get_oauth_status() -> Dict[str, Any]:
    return oauth_status()


@app.post("/oauth/start")
def post_oauth_start() -> Dict[str, Any]:
    return start_device_auth()


@app.get("/oauth/logs")
def get_oauth_logs() -> Dict[str, Any]:
    return {"ok": True, "logs": list(log_buffer)}


@app.post("/oauth/cancel")
def cancel_oauth() -> Dict[str, Any]:
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

    uvicorn.run(app, host="0.0.0.0", port=8090)
