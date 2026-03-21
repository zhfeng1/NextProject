# NextProject

## 启动

```bash
docker compose up -d --build
```

## 端口

- 主服务（配置页 + 首页）：`http://localhost:18080`
- 新网站（自动部署的网站）：`http://localhost:18081`

## 功能对应

- 容器启动时自动拉取主流 `AGENTS.md` 到 `./data/agents`（已存在则跳过不覆盖）。
- 首次打开是配置页，可配置：
  - OpenAI 兼容 API（`responses` / `chat_completions`）
  - Codex OAuth / MCP 相关配置
- 保存后进入首页：
  - 输入网站需求
  - 选择 `LLM` 或 `Codex` 制作
  - 默认生成 Python 后端 + Vue 前端的新网站
- 生成后自动部署并在首页 iframe 预览。
- 右下角浮动按钮可输入调整要求，提交后自动重启新网站。
- 首页按钮可触发 Chrome DevTools MCP 测试（需先配置 MCP URL）。
