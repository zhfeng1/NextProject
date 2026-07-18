from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="NextProject Python Starter")

app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"ok": "true", "service": "python-vue-starter"}


@app.get("/api/info")
def info() -> dict[str, object]:
    return {
        "name": "Python Vue Starter",
        "stack": ["Python", "FastAPI", "Static frontend"],
        "offline_ready": True,
    }


@app.get("/{path:path}")
def serve_frontend(path: str) -> FileResponse:
    target = FRONTEND_DIR / path
    if path and target.exists() and target.is_file():
        return FileResponse(str(target))
    return FileResponse(str(FRONTEND_DIR / "index.html"))
