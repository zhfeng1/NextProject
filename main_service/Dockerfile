# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

WORKDIR /app

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        # git is required because each generated site must be initialized as a repo for agent edits
        bubblewrap curl ca-certificates gnupg docker.io jq nodejs npm git ripgrep \
        libglib2.0-0t64 libnspr4 libnss3 libatk1.0-0t64 libdbus-1-3 libatspi2.0-0t64 \
        libatk-bridge2.0-0t64 libcups2t64 libcairo2 libpango-1.0-0 \
        libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 \
        libxcb1 libxkbcommon0 libasound2t64 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY main_service/requirements.txt /app/requirements.txt
COPY main_service/requirements-dev.txt /app/requirements-dev.txt
ARG INSTALL_DEV=false
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_DEV" = "true" ]; then \
        pip install -r /app/requirements-dev.txt; \
    else \
        pip install -r /app/requirements.txt; \
    fi

COPY main_service/package.json /app/package.json
COPY main_service/package-lock.json /app/package-lock.json
COPY scripts/init_agents.py /app/init_agents.py
RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev \
    && npm install -g @openai/codex
RUN npx playwright install chromium

COPY main_service/app /app/app
COPY backend /app/backend
COPY scripts /app/scripts

EXPOSE 8080
CMD ["sh", "-c", "python /app/init_agents.py && uvicorn backend.main:app --host 0.0.0.0 --port 8080"]
