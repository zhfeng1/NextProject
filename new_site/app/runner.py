import os
import signal
import subprocess
import time
from pathlib import Path

RESTART_FLAG = Path('/shared/restart.flag')
WORKDIR = Path('/generated_site')


def start_server() -> subprocess.Popen:
    return subprocess.Popen(
        [
            'uvicorn',
            'backend.app:app',
            '--host',
            '0.0.0.0',
            '--port',
            '8081',
        ],
        cwd=str(WORKDIR),
    )


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    RESTART_FLAG.parent.mkdir(parents=True, exist_ok=True)
    if not RESTART_FLAG.exists():
        RESTART_FLAG.write_text(str(time.time()), encoding='utf-8')

    proc = start_server()
    last_mtime = RESTART_FLAG.stat().st_mtime

    while True:
        time.sleep(1)
        if proc.poll() is not None:
            proc = start_server()
            continue

        current_mtime = RESTART_FLAG.stat().st_mtime if RESTART_FLAG.exists() else 0
        if current_mtime != last_mtime:
            last_mtime = current_mtime
            stop_server(proc)
            proc = start_server()


if __name__ == '__main__':
    main()
