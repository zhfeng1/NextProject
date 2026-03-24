#!/usr/bin/env bash
# 使用 Docker Compose 启动所有服务
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
BUILD_FLAG=""
DETACH_FLAG="-d"
PROFILE=""

for arg in "$@"; do
    case "$arg" in
        --build|-b)   BUILD_FLAG="--build" ;;
        --no-detach)  DETACH_FLAG="" ;;
        --attach|-a)  DETACH_FLAG="" ;;
        *)            ;;
    esac
done

# ── 3. 启动 ───────────────────────────────────────────────────
log_info "启动服务 (docker compose up $BUILD_FLAG $DETACH_FLAG)..."

# 排除 test 服务（按需运行）
docker compose up $BUILD_FLAG $DETACH_FLAG \
    --scale test=0 \
    postgres redis minio codex-mcp main-service celery-worker celery-beat flower frontend

if [ -n "$DETACH_FLAG" ]; then
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  服务已在后台启动${NC}"
    echo -e "${GREEN}  前端:         http://localhost:20100${NC}"
    echo -e "${GREEN}  Flower:       http://localhost:20101${NC}"
    echo -e "${GREEN}  MinIO 控制台: http://localhost:20102${NC}"
    echo -e "${GREEN}  Grafana:      http://localhost:20103${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "查看日志: ${BLUE}docker compose logs -f${NC}"
    echo -e "停止服务: ${BLUE}docker compose down${NC}"
fi
