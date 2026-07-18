from __future__ import annotations

import os
import subprocess
import sys


def main() -> None:
    port = os.environ.get("PORT", "8080")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
