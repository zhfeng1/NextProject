# Python Vue Starter

离线优先的 NextProject 默认站点模板。

## 启动

```bash
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8080
```

或使用 Docker：

```bash
docker compose up --build
```

## 结构

- `backend/app.py`: FastAPI 后端入口
- `frontend/`: 静态前端资源
- `docs/`: 需求和设计文档
- `.np/`: NextProject 工作流状态目录

该模板不依赖 Cloudflare Worker、Sites 托管或 OpenAI 托管元数据。
