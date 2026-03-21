import os
from pathlib import Path

import httpx

AGENTS = {
    'openai-codex': 'https://raw.githubusercontent.com/openai/codex/main/AGENTS.md',
    'openhands': 'https://raw.githubusercontent.com/All-Hands-AI/OpenHands/main/AGENTS.md',
    'roo-code': 'https://raw.githubusercontent.com/RooVetGit/Roo-Code/main/AGENTS.md',
}

TARGET_DIR = Path('/shared/agents')


def fetch_if_missing(name: str, url: str) -> None:
    target = TARGET_DIR / f'{name}.md'
    if target.exists():
        print(f'skip existing: {target}')
        return

    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            content = resp.text.strip()
        if not content:
            print(f'empty content: {url}')
            return
        target.write_text(content, encoding='utf-8')
        print(f'downloaded: {name}')
    except Exception as exc:
        print(f'failed: {name} -> {exc}')


def main() -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in AGENTS.items():
        fetch_if_missing(name, url)


if __name__ == '__main__':
    main()
