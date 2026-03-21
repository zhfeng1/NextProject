# Dockerfile 修改建议（v2.0.0 修复）

**目标**: 在 Docker 容器中安装所有依赖，避免在本地机器安装

---

## 1. 更新 requirements.txt

**文件**: `main_service/requirements.txt`（添加以下依赖）

```txt
# 现有依赖...
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.29.0
alembic>=1.12.0
redis>=5.0.0
celery>=5.3.0
pydantic>=2.4.0
pydantic-settings>=2.0.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.6
prometheus-client>=0.18.0

# 新增依赖
minio>=7.2.0              # MinIO 对象存储客户端
```

---

## 2. 创建开发依赖文件

**文件**: `main_service/requirements-dev.txt`（新建）

```txt
# 继承生产依赖
-r requirements.txt

# 测试框架
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
pytest-mock>=3.12.0

# HTTP 测试客户端
httpx>=0.24.0

# 数据模拟
faker>=19.0.0

# 代码质量
black>=23.0.0
flake8>=6.0.0
mypy>=1.5.0
isort>=5.12.0

# 调试工具
ipdb>=0.13.13
```

---

## 3. 更新 Dockerfile（多阶段构建）

**文件**: `main_service/Dockerfile`

### 方案 A: 单一镜像（包含测试工具）

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

WORKDIR /app

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# 安装系统依赖
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg docker.io nodejs npm \
        libglib2.0-0t64 libnspr4 libnss3 libatk1.0-0t64 libdbus-1-3 libatspi2.0-0t64 \
        libatk-bridge2.0-0t64 libcups2t64 libcairo2 libpango-1.0-0 \
        libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 \
        libxcb1 libxkbcommon0 libasound2t64 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY main_service/requirements.txt /app/requirements.txt
COPY main_service/requirements-dev.txt /app/requirements-dev.txt

# 根据构建参数选择依赖
ARG INSTALL_DEV=false
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_DEV" = "true" ]; then \
        pip install -r /app/requirements-dev.txt; \
    else \
        pip install -r /app/requirements.txt; \
    fi

# 安装 Node.js 依赖
COPY main_service/package.json /app/package.json
COPY main_service/package-lock.json /app/package-lock.json
COPY scripts/init_agents.py /app/init_agents.py

RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev

RUN npx playwright install chromium

# 复制应用代码
COPY main_service/app /app/app
COPY backend /app/backend
COPY scripts /app/scripts

EXPOSE 8080

# 默认命令（可被 docker-compose 覆盖）
CMD ["sh", "-c", "python /app/init_agents.py && uvicorn backend.main:app --host 0.0.0.0 --port 8080"]
```

### 方案 B: 多阶段构建（生产镜像更小）

```dockerfile
# syntax=docker/dockerfile:1.7

###########################################
# Stage 1: 基础镜像
###########################################
FROM python:3.12-slim AS base

WORKDIR /app

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# 安装系统依赖
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg docker.io nodejs npm \
        libglib2.0-0t64 libnspr4 libnss3 libatk1.0-0t64 libdbus-1-3 libatspi2.0-0t64 \
        libatk-bridge2.0-0t64 libcups2t64 libcairo2 libpango-1.0-0 \
        libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 \
        libxcb1 libxkbcommon0 libasound2t64 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

###########################################
# Stage 2: 开发镜像（带测试工具）
###########################################
FROM base AS development

# 安装开发依赖
COPY main_service/requirements-dev.txt /app/requirements-dev.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /app/requirements-dev.txt

# 安装 Node.js 依赖
COPY main_service/package.json /app/package.json
COPY main_service/package-lock.json /app/package-lock.json
RUN --mount=type=cache,target=/root/.npm \
    npm ci

RUN npx playwright install chromium

# 复制应用代码
COPY main_service/app /app/app
COPY backend /app/backend
COPY scripts /app/scripts
COPY pytest.ini /app/pytest.ini

EXPOSE 8080

# 开发模式命令
CMD ["sh", "-c", "python /app/scripts/init_agents.py && uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload"]

###########################################
# Stage 3: 生产镜像（最小化）
###########################################
FROM base AS production

# 仅安装生产依赖
COPY main_service/requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r /app/requirements.txt

# 安装 Node.js 依赖（仅生产）
COPY main_service/package.json /app/package.json
COPY main_service/package-lock.json /app/package-lock.json
COPY scripts/init_agents.py /app/init_agents.py

RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev

RUN npx playwright install chromium

# 复制应用代码
COPY main_service/app /app/app
COPY backend /app/backend
COPY scripts /app/scripts

EXPOSE 8080

# 生产模式命令
CMD ["sh", "-c", "python /app/init_agents.py && uvicorn backend.main:app --host 0.0.0.0 --port 8080"]
```

---

## 4. 更新 docker-compose.yml

### 4.1 使用方案 A（单一镜像 + ARG）

```yaml
version: '3.8'

services:
  main-service:
    build:
      context: .
      dockerfile: main_service/Dockerfile
      args:
        INSTALL_DEV: "true"  # 开发环境包含测试工具
    ports:
      - "18080:8080"
    environment:
      - DATABASE_URL=${DATABASE_URL:-postgresql+asyncpg://admin:nextproject2025@postgres:5432/nextproject}
      - REDIS_URL=redis://:${REDIS_PASSWORD:-redis2025}@redis:6379/0
      - SECRET_KEY=${SECRET_KEY}
      - MINIO_ENDPOINT=minio:9000
      - MINIO_ACCESS_KEY=minioadmin
      - MINIO_SECRET_KEY=minioadmin
    volumes:
      - ./shared:/shared
      - ./backend:/app/backend  # 开发时热重载
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      minio:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 40s
    networks:
      - nextproject-network

  # 新增：测试服务
  test:
    build:
      context: .
      dockerfile: main_service/Dockerfile
      args:
        INSTALL_DEV: "true"
    command: pytest backend/tests/ -v --cov=backend --cov-report=html --cov-report=term-missing
    environment:
      - DATABASE_URL=sqlite+aiosqlite:///:memory:
      - SECRET_KEY=test-secret-key-at-least-32-chars-long
    volumes:
      - .:/app
      - ./htmlcov:/app/htmlcov
    depends_on:
      - postgres
      - redis
    networks:
      - nextproject-network
```

### 4.2 使用方案 B（多阶段构建）

```yaml
version: '3.8'

services:
  main-service:
    build:
      context: .
      dockerfile: main_service/Dockerfile
      target: development  # 开发环境使用 development stage
    ports:
      - "18080:8080"
    environment:
      - DATABASE_URL=${DATABASE_URL:-postgresql+asyncpg://admin:nextproject2025@postgres:5432/nextproject}
      - REDIS_URL=redis://:${REDIS_PASSWORD:-redis2025}@redis:6379/0
      - SECRET_KEY=${SECRET_KEY}
      - MINIO_ENDPOINT=minio:9000
      - MINIO_ACCESS_KEY=minioadmin
      - MINIO_SECRET_KEY=minioadmin
    volumes:
      - ./shared:/shared
      - ./backend:/app/backend
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      minio:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 40s
    networks:
      - nextproject-network

  # 测试服务
  test:
    build:
      context: .
      dockerfile: main_service/Dockerfile
      target: development
    command: pytest backend/tests/ -v --cov=backend --cov-report=html --cov-report=term-missing
    environment:
      - DATABASE_URL=sqlite+aiosqlite:///:memory:
      - SECRET_KEY=test-secret-key-at-least-32-chars-long
    volumes:
      - .:/app
      - ./htmlcov:/app/htmlcov
    networks:
      - nextproject-network
```

---

## 5. 使用指南

### 5.1 构建开发镜像

**方案 A**:
```bash
docker-compose build main-service
```

**方案 B**:
```bash
docker-compose build main-service --build-arg target=development
```

### 5.2 构建生产镜像

**方案 A**:
```bash
docker build -t nextproject-main:prod \
  --build-arg INSTALL_DEV=false \
  -f main_service/Dockerfile .
```

**方案 B**:
```bash
docker build -t nextproject-main:prod \
  --target production \
  -f main_service/Dockerfile .
```

### 5.3 运行测试

```bash
# 运行测试容器
docker-compose run --rm test

# 在运行的容器中测试
docker-compose exec main-service pytest backend/tests/ -v

# 查看覆盖率报告
open htmlcov/index.html
```

### 5.4 进入容器调试

```bash
# 进入主服务容器
docker-compose exec main-service bash

# 在容器内手动运行测试
pytest backend/tests/test_auth.py -v -s

# 检查已安装的包
pip list | grep minio
pip list | grep pytest
```

---

## 6. 验证依赖安装

### 6.1 验证 MinIO SDK

```bash
docker-compose exec main-service python -c "
from minio import Minio
print('MinIO SDK installed successfully')
print(f'Version: {Minio.__module__}')
"
```

### 6.2 验证测试工具

```bash
docker-compose exec main-service python -c "
import pytest
import httpx
import faker
print('Test dependencies installed:')
print(f'pytest: {pytest.__version__}')
print(f'httpx: {httpx.__version__}')
print(f'faker: {faker.__version__}')
"
```

---

## 7. 镜像大小对比

| 镜像类型 | 大小估算 | 说明 |
|---------|---------|------|
| **方案 A (INSTALL_DEV=false)** | ~1.2 GB | 生产镜像 |
| **方案 A (INSTALL_DEV=true)** | ~1.5 GB | 开发镜像（含测试工具） |
| **方案 B (production stage)** | ~1.1 GB | 最小化生产镜像 |
| **方案 B (development stage)** | ~1.6 GB | 完整开发镜像 |

---

## 8. 推荐方案

| 场景 | 推荐方案 | 理由 |
|------|---------|------|
| **小型团队/快速迭代** | 方案 A | 简单，单一 Dockerfile，易维护 |
| **生产优化/CI-CD** | 方案 B | 生产镜像更小，部署更快 |
| **初学者** | 方案 A | 易理解，调试友好 |
| **企业级部署** | 方案 B | 安全性更高，资源占用少 |

---

## 9. 常见问题

### Q1: 如何在生产环境禁用测试工具？

**A**: 使用方案 B，构建生产镜像时指定 `--target production`。

### Q2: 测试依赖会影响生产性能吗？

**A**: 不会。方案 A 使用 ARG 控制，生产构建时不安装测试依赖；方案 B 使用多阶段构建，测试工具完全不包含在生产镜像中。

### Q3: 如何在 CI/CD 中使用？

**A**: 示例 GitHub Actions workflow:

```yaml
# .github/workflows/test.yml
name: Test
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build test image
        run: docker-compose build test

      - name: Run tests
        run: docker-compose run --rm test

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: ./htmlcov/coverage.xml
```

---

**文档版本**: v1.0
**最后更新**: 2026-03-20
**适用于**: NextProject v2.0.0
