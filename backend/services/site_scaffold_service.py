from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
STARTERS_ROOT = BASE_DIR / "starters"
PYTHON_VUE_STARTER_ROOT = STARTERS_ROOT / "python-vue-starter"

DEFAULT_DOCS_README = """# Project Docs

本目录用于沉淀需求、设计说明和模块文档。

- 新需求会默认记录到 `requirements.md`
- AI 完成修改任务后，应按模块整理本目录下的文档
"""

DEFAULT_REQUIREMENTS = "# 需求文档\n"

PYTHON_VUE_START_COMMAND = "python -m uvicorn backend.app:app --host 0.0.0.0 --port $PORT"
PYTHON_VUE_BUILD_COMMAND = "python -m py_compile backend/app.py"


def python_vue_site_config(extra: dict | None = None) -> dict:
    config = {
        "source_type": "starter",
        "starter": "python-vue",
        "runtime": "python-fastapi",
        "start_command": PYTHON_VUE_START_COMMAND,
        "build_command": PYTHON_VUE_BUILD_COMMAND,
    }
    if extra:
        config.update(extra)
    return config


class SiteScaffoldService:
    def ensure_support_dirs(self, root: Path) -> None:
        docs_dir = root / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        readme_file = docs_dir / "README.md"
        if not readme_file.exists():
            readme_file.write_text(DEFAULT_DOCS_README, encoding="utf-8")

        requirements_file = docs_dir / "requirements.md"
        if not requirements_file.exists():
            requirements_file.write_text(DEFAULT_REQUIREMENTS, encoding="utf-8")

        legacy_requirements = root / "REQUIREMENTS.md"
        if legacy_requirements.exists():
            if not requirements_file.read_text(encoding="utf-8").strip():
                requirements_file.write_text(legacy_requirements.read_text(encoding="utf-8"), encoding="utf-8")
            legacy_requirements.unlink()

        workflows_root = root / ".np" / "workflows"
        (workflows_root / "runs").mkdir(parents=True, exist_ok=True)
        (workflows_root / "current").mkdir(parents=True, exist_ok=True)
        (workflows_root / "history").mkdir(parents=True, exist_ok=True)

    def initialize_git_repo(self, root: Path, message: str = "Initial python-vue starter") -> None:
        git_bin = shutil.which("git")
        if not git_bin:
            raise RuntimeError("git is required in the runtime image to initialize generated site repositories")
        if (root / ".git").exists():
            return
        subprocess.run([git_bin, "init"], cwd=str(root), capture_output=True, check=True)
        subprocess.run([git_bin, "add", "."], cwd=str(root), capture_output=True, check=True)
        subprocess.run(
            [git_bin, "commit", "-m", message, "--allow-empty"],
            cwd=str(root),
            capture_output=True,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "NextProject",
                "GIT_AUTHOR_EMAIL": "bot@nextproject",
                "GIT_COMMITTER_NAME": "NextProject",
                "GIT_COMMITTER_EMAIL": "bot@nextproject",
            },
        )

    def initialize_python_vue_site(self, root: Path) -> Path:
        if not PYTHON_VUE_STARTER_ROOT.exists():
            raise RuntimeError(f"Python Vue starter not found: {PYTHON_VUE_STARTER_ROOT}")

        root.mkdir(parents=True, exist_ok=True)
        if not any(root.iterdir()):
            shutil.copytree(
                PYTHON_VUE_STARTER_ROOT,
                root,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "node_modules", "dist", ".git"),
            )
        elif not (root / "backend" / "app.py").exists():
            raise RuntimeError(f"Cannot initialize python-vue starter into non-empty directory: {root}")

        self.ensure_support_dirs(root)
        self.initialize_git_repo(root)
        return root

    def ensure_existing_site_support(self, root: Path) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        self.ensure_support_dirs(root)
        return root


site_scaffold_service = SiteScaffoldService()
