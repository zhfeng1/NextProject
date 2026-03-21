import re
import unicodedata

from fastapi import HTTPException

try:
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

SITE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def validate_site_id(site_id: str) -> str:
    normalized = (site_id or "").strip().lower()
    if not normalized or not SITE_ID_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=400, detail=f"site_id 非法: {site_id}")
    return normalized


def ensure_site_id(site_id: str) -> str:
    return validate_site_id(site_id)


def slugify(value: str) -> str:
    text = (value or "").strip()
    if lazy_pinyin and _CJK_RE.search(text):
        text = "-".join(lazy_pinyin(text))
    else:
        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "site"


def generate_site_slug(value: str) -> str:
    base = slugify(value)
    base = re.sub(r"[^a-z0-9-]+", "-", base).strip("-")
    return (base or "site")[:32]


def compact_json_text(value: str) -> str:
    return value.strip() if isinstance(value, str) else ""
