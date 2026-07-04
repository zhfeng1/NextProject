# syntax=docker/dockerfile:1.7
FROM node:22-slim AS node-runtime

FROM python:3.12-slim

ARG TOOL_ID=codex
ENV TOOL_ID=${TOOL_ID}
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV NPM_CONFIG_AUDIT=false
ENV NPM_CONFIG_FUND=false
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/bin/npm /usr/local/bin/npm
COPY --from=node-runtime /usr/local/bin/npx /usr/local/bin/npx
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git jq ripgrep tini \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.npm \
    case "${TOOL_ID}" in \
      codex) package='@openai/codex@0.144.4' ;; \
      claude_code) package='@anthropic-ai/claude-code@2.1.210' ;; \
      codebuddy) package='@tencent-ai/codebuddy-code@2.121.2' ;; \
      opencode) package='opencode-ai@1.18.1' ;; \
      kimi_code) package='@moonshot-ai/kimi-code@0.27.0' ;; \
      *) echo "Unsupported TOOL_ID: ${TOOL_ID}" >&2; exit 1 ;; \
    esac \
    && npm install -g "${package}" --prefer-online

COPY programming_tool_adapter/requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /app/requirements.txt

COPY programming_tool_adapter/app /app/app

EXPOSE 8090 8091 8092 8093 8094
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app.server"]
