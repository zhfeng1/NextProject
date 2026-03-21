import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path("/shared")
DB_PATH = DATA_DIR / "app.db"
GENERATED_SITE_PATH = Path("/generated_site")
RESTART_FLAG = DATA_DIR / "restart.flag"

app = FastAPI(title="Site Builder Main Service")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                llm_mode TEXT,
                llm_base_url TEXT,
                llm_api_key TEXT,
                llm_model TEXT,
                codex_client_id TEXT,
                codex_client_secret TEXT,
                codex_redirect_uri TEXT,
                codex_access_token TEXT,
                codex_mcp_url TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("INSERT OR IGNORE INTO app_config (id) VALUES (1)")
        conn.commit()


def load_config() -> Dict[str, str]:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT * FROM app_config WHERE id = 1").fetchone()
        if not row:
            return {}
        columns = [d[0] for d in conn.execute("PRAGMA table_info(app_config)").fetchall()]
        # PRAGMA returns cid,name,type,... so extract name at index 1
        names = [r[1] for r in conn.execute("PRAGMA table_info(app_config)").fetchall()]
        data = dict(zip(names, row))
        data.pop("id", None)
        return {k: (v or "") for k, v in data.items() if k != "updated_at"}


def save_config(data: Dict[str, str]) -> None:
    fields = [
        "llm_mode",
        "llm_base_url",
        "llm_api_key",
        "llm_model",
        "codex_client_id",
        "codex_client_secret",
        "codex_redirect_uri",
        "codex_access_token",
        "codex_mcp_url",
    ]
    values = [data.get(f, "") for f in fields]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            f"""
            UPDATE app_config
            SET {", ".join([f"{f} = ?" for f in fields])}, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            values,
        )
        conn.commit()


def ensure_generated_site_structure() -> None:
    (GENERATED_SITE_PATH / "backend").mkdir(parents=True, exist_ok=True)
    (GENERATED_SITE_PATH / "frontend").mkdir(parents=True, exist_ok=True)
    (GENERATED_SITE_PATH / "backend" / "site_data.json").write_text(
        json.dumps({"title": "New Website", "requirement": "", "notes": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    app_py = GENERATED_SITE_PATH / "backend" / "app.py"
    if not app_py.exists():
        app_py.write_text(
            """import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "backend" / "site_data.json"

app = FastAPI(title="Generated Site")
app.mount("/assets", StaticFiles(directory=str(BASE_DIR / "frontend")), name="assets")


@app.get("/api/info")
def get_info():
    if not DATA_FILE.exists():
        return {"title": "New Website", "requirement": "", "notes": []}
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


@app.get("/{path:path}")
def serve_frontend(path: str):
    return FileResponse(str(BASE_DIR / "frontend" / "index.html"))
""",
            encoding="utf-8",
        )

    frontend_html = GENERATED_SITE_PATH / "frontend" / "index.html"
    if not frontend_html.exists():
        frontend_html.write_text(
            """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Generated Website</title>
  <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/axios@1.7.9/dist/axios.min.js"></script>
  <style>
    :root { --bg: #f4f7fb; --card: #ffffff; --text: #213547; --brand: #0e7a7a; }
    body { margin: 0; font-family: "PingFang SC", "Microsoft YaHei", sans-serif; background: linear-gradient(135deg, #eef6ff 0%, #f5fffa 100%); color: var(--text); }
    .wrap { max-width: 980px; margin: 32px auto; padding: 0 16px; }
    .card { background: var(--card); border-radius: 16px; padding: 24px; box-shadow: 0 10px 30px rgba(16, 40, 63, .08); }
    h1 { margin: 0 0 12px; font-size: 30px; }
    .muted { color: #6b7b8f; }
    ul { line-height: 1.8; }
  </style>
</head>
<body>
  <div id="app" class="wrap">
    <div class="card">
      <h1>{{ info.title }}</h1>
      <p class="muted">需求：{{ info.requirement || '未填写' }}</p>
      <h3>迭代记录</h3>
      <ul>
        <li v-for="(n, idx) in info.notes" :key="idx">{{ n }}</li>
      </ul>
    </div>
  </div>
  <script>
    const { createApp } = Vue;
    createApp({
      data() {
        return { info: { title: 'Generated Website', requirement: '', notes: [] } };
      },
      async mounted() {
        const r = await axios.get('/api/info');
        this.info = r.data;
      }
    }).mount('#app');
  </script>
</body>
</html>
""",
            encoding="utf-8",
        )


class ConfigPayload(BaseModel):
    llm_mode: str = "responses"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-mini"
    codex_client_id: str = ""
    codex_client_secret: str = ""
    codex_redirect_uri: str = ""
    codex_access_token: str = ""
    codex_mcp_url: str = ""


class BuildPayload(BaseModel):
    requirement: str
    builder: str = "llm"  # llm | codex


class AdjustPayload(BaseModel):
    instruction: str


class ModelListPayload(BaseModel):
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""


@app.on_event("startup")
def startup() -> None:
    init_db()
    ensure_generated_site_structure()


@app.get("/", response_class=HTMLResponse)
def config_page(request: Request):
    config = load_config()
    return templates.TemplateResponse("config.html", {"request": request, "config": config})


@app.get("/home", response_class=HTMLResponse)
def home_page(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})


@app.get("/api/config")
def get_config():
    return load_config()


@app.post("/api/config")
def post_config(payload: ConfigPayload):
    save_config(payload.model_dump())
    return {"ok": True}


@app.post("/api/llm-models")
def fetch_llm_models(payload: ModelListPayload):
    base_url = payload.llm_base_url.strip().rstrip("/") or "https://api.openai.com/v1"
    models_url = f"{base_url}/models"
    headers = {"Content-Type": "application/json"}
    if payload.llm_api_key.strip():
        headers["Authorization"] = f"Bearer {payload.llm_api_key.strip()}"

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(models_url, headers=headers)
            resp.raise_for_status()
            data = resp.json().get("data", [])
        model_ids = sorted(
            [m.get("id", "") for m in data if isinstance(m, dict) and m.get("id")],
            key=lambda x: x.lower(),
        )
        return {"ok": True, "models": model_ids}
    except Exception as exc:
        return JSONResponse(status_code=502, content={"ok": False, "models": [], "message": f"{exc}"})


def apply_template_generation(requirement: str, builder: str) -> Dict[str, Any]:
    data_file = GENERATED_SITE_PATH / "backend" / "site_data.json"
    data = {"title": "New Website", "requirement": requirement, "notes": [f"初始生成：{builder}"]}

    cfg = load_config()
    if builder == "llm" and cfg.get("llm_api_key"):
        mode = cfg.get("llm_mode", "responses")
        base_url = (cfg.get("llm_base_url") or "https://api.openai.com/v1").rstrip("/")
        model = cfg.get("llm_model") or "gpt-4.1-mini"

        prompt = (
            "你是网站规划助手。给定需求，输出JSON对象，字段: title, summary。"
            "title是网站标题，summary是50字内中文描述。需求:\n" + requirement
        )
        headers = {"Authorization": f"Bearer {cfg.get('llm_api_key')}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=20) as client:
                if mode == "chat_completions":
                    resp = client.post(
                        f"{base_url}/chat/completions",
                        headers=headers,
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": "你是严谨的产品设计助手。"},
                                {"role": "user", "content": prompt},
                            ],
                            "response_format": {"type": "json_object"},
                        },
                    )
                    resp.raise_for_status()
                    content = resp.json()["choices"][0]["message"]["content"]
                else:
                    resp = client.post(
                        f"{base_url}/responses",
                        headers=headers,
                        json={
                            "model": model,
                            "input": prompt,
                            "text": {"format": {"type": "json_object"}},
                        },
                    )
                    resp.raise_for_status()
                    content = resp.json().get("output_text", "{}")

            model_result = json.loads(content)
            data["title"] = model_result.get("title") or data["title"]
            summary = model_result.get("summary")
            if summary:
                data["notes"].append(f"LLM摘要：{summary}")
        except Exception as exc:
            data["notes"].append(f"LLM调用失败，已回退模板生成：{exc}")

    if builder == "codex":
        data["notes"].append("Codex模式：使用本地模板和规则生成，后续可接入codex-mcp")

    data_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    RESTART_FLAG.write_text(str(os.times()), encoding="utf-8")
    return data


@app.post("/api/build-site")
def build_site(payload: BuildPayload):
    if not payload.requirement.strip():
        raise HTTPException(status_code=400, detail="requirement 不能为空")
    result = apply_template_generation(payload.requirement.strip(), payload.builder)
    return {"ok": True, "result": result, "preview_url": "http://localhost:18081"}


@app.post("/api/adjust-site")
def adjust_site(payload: AdjustPayload):
    if not payload.instruction.strip():
        raise HTTPException(status_code=400, detail="instruction 不能为空")

    data_file = GENERATED_SITE_PATH / "backend" / "site_data.json"
    if data_file.exists():
        data = json.loads(data_file.read_text(encoding="utf-8"))
    else:
        data = {"title": "New Website", "requirement": "", "notes": []}
    data.setdefault("notes", []).append(f"调整：{payload.instruction.strip()}")
    data_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    RESTART_FLAG.write_text(str(os.times()), encoding="utf-8")
    return {"ok": True}


@app.post("/api/test-site")
def test_site_via_mcp():
    cfg = load_config()
    mcp_url = cfg.get("codex_mcp_url", "").strip()
    token = cfg.get("codex_access_token", "").strip()
    if not mcp_url:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "message": "未配置 codex_mcp_url，无法触发 Chrome DevTools MCP。",
            },
        )

    try:
        payload = {
            "tool": "chrome-devtools",
            "action": "smoke_test",
            "target": "http://new-site:8081",
        }
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with httpx.Client(timeout=20) as client:
            resp = client.post(mcp_url, headers=headers, json=payload)
            resp.raise_for_status()
            return {"ok": True, "result": resp.json()}
    except Exception as exc:
        return JSONResponse(status_code=502, content={"ok": False, "message": f"MCP调用失败: {exc}"})


@app.get("/api/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)
