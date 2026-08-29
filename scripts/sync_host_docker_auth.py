#!/usr/bin/env python3
"""Export the host Docker login state for use by the Linux worker container."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _credential(helper: str, registry: str) -> dict[str, str] | None:
    try:
        result = subprocess.run(
            [f"docker-credential-{helper}", "get"],
            input=f"{registry}\n",
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    username = str(value.get("Username") or "")
    secret = str(value.get("Secret") or "")
    if not username or not secret:
        return None
    token = base64.b64encode(f"{username}:{secret}".encode()).decode()
    return {"auth": token}


def _env_value(path: Path, key: str) -> str:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return ""
    prefix = f"{key}="
    for line in reversed(lines):
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return ""


def _export_auths(
    config: dict[str, Any], registries: list[str]
) -> dict[str, dict[str, str]]:
    exported: dict[str, dict[str, str]] = {}
    default_helper = str(config.get("credsStore") or "")
    helpers = config.get("credHelpers") or {}
    source_auths = config.get("auths") or {}
    for registry in registries:
        current = source_auths.get(registry) or {}
        helper = str(helpers.get(registry) or default_helper)
        credential = _credential(helper, registry) if helper else None
        if credential is None and isinstance(current, dict) and current.get("auth"):
            credential = {"auth": str(current["auth"])}
        if credential is not None:
            exported[str(registry)] = credential
    return exported


def main() -> int:
    output_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "data/docker-config")
    host_config_dir = Path(
        os.environ.get("DOCKER_CONFIG") or (Path.home() / ".docker")
    )
    host_config = host_config_dir / "config.json"
    try:
        source = json.loads(host_config.read_text())
    except (OSError, json.JSONDecodeError):
        return 1
    registry = (
        os.environ.get("HARBOR_REGISTRY")
        or _env_value(Path(".env"), "HARBOR_REGISTRY")
        or "harbor.trscd.com.cn"
    )
    auths = _export_auths(source, [registry])
    if not auths:
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.chmod(0o700)
    destination = output_dir / "config.json"
    temporary = output_dir / ".config.json.tmp"
    temporary.write_text(json.dumps({"auths": auths}, separators=(",", ":")) + "\n")
    temporary.chmod(0o600)
    temporary.replace(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
