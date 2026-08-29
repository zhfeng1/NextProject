#!/usr/bin/env bash
# 使用 Docker Compose 启动核心服务，可按需启用 profile
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ── 1. 检查 .env ──────────────────────────────────────────────
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp ".env.example" ".env"
        log_warn ".env 已从 .env.example 复制，请填写 SECRET_KEY 后重新运行"
        exit 1
    else
        log_error "找不到 .env 文件，请手动创建"
        exit 1
    fi
fi

# ── 2. 解析参数 ───────────────────────────────────────────────
if python3 scripts/sync_host_docker_auth.py data/docker-config; then
    log_ok "已同步宿主机 Docker 登录状态"
else
    log_warn "未同步宿主机 Docker 登录状态，私有镜像推送可能失败"
fi

BUILD_FLAG=""
DETACH_FLAG="-d"
COMPOSE_PROFILE_FLAGS=()
START_MONITORING=false
START_SCHEDULER=false

for arg in "$@"; do
    case "$arg" in
        --build|-b)   BUILD_FLAG="--build" ;;
        --no-detach)  DETACH_FLAG="" ;;
        --attach|-a)  DETACH_FLAG="" ;;
        --monitoring) START_MONITORING=true ;;
        --scheduler)  START_SCHEDULER=true ;;
        --all)        START_MONITORING=true; START_SCHEDULER=true ;;
        *)            ;;
    esac
done

if [ "$START_MONITORING" = true ]; then
    COMPOSE_PROFILE_FLAGS+=(--profile monitoring)
fi

if [ "$START_SCHEDULER" = true ]; then
    COMPOSE_PROFILE_FLAGS+=(--profile scheduler)
fi

# ── 3. 启动 ───────────────────────────────────────────────────
log_info "启动服务 (docker compose up $BUILD_FLAG $DETACH_FLAG)..."

CORE_SERVICES=(
    postgres redis
    codex-adapter claude-code-adapter codebuddy-adapter opencode-adapter
    main-service celery-worker frontend
)
OPTIONAL_SERVICES=()

if [ "$START_MONITORING" = true ]; then
    OPTIONAL_SERVICES+=(flower prometheus grafana)
fi

if [ "$START_SCHEDULER" = true ]; then
    OPTIONAL_SERVICES+=(celery-beat)
fi

docker compose "${COMPOSE_PROFILE_FLAGS[@]}" up --remove-orphans $BUILD_FLAG $DETACH_FLAG \
    "${CORE_SERVICES[@]}" "${OPTIONAL_SERVICES[@]}"

if [ -n "$DETACH_FLAG" ]; then
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  服务已在后台启动${NC}"
    echo -e "${GREEN}  前端:         http://localhost:20100${NC}"
    if [ "$START_MONITORING" = true ]; then
        echo -e "${GREEN}  Flower:       http://localhost:20101${NC}"
        echo -e "${GREEN}  Grafana:      http://localhost:20103${NC}"
    else
        echo -e "${YELLOW}  监控服务未启动: ./start.sh --monitoring${NC}"
    fi
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "查看日志: ${BLUE}docker compose logs -f${NC}"
    echo -e "停止服务: ${BLUE}docker compose down${NC}"
    echo -e "运行测试: ${BLUE}docker compose run --rm test${NC}"
fi
