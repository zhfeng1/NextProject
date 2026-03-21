#!/bin/bash
set -euo pipefail

PROJECT_ROOT="/Users/zhfeng/IdeaProjects/NextProject"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "NextProject v2.0.0 快速修复脚本"
echo "=========================================="
echo ""
echo "该脚本不会在本地安装任何工具。"
echo "它只会创建配置文件、目录结构，并补齐依赖声明。"
echo ""

mkdir -p backend/tests
touch backend/tests/__init__.py

mkdir -p monitoring/grafana/provisioning/datasources
mkdir -p monitoring/grafana/provisioning/dashboards
mkdir -p k8s/base
mkdir -p k8s/overlays/dev
mkdir -p k8s/overlays/prod

if ! grep -q '^minio==' main_service/requirements.txt; then
  echo 'minio==7.2.10' >> main_service/requirements.txt
fi

cat > pytest.ini <<'EOF'
[pytest]
testpaths = backend/tests
python_files = test_*.py
asyncio_mode = auto
addopts =
    --strict-markers
    --cov=backend
    --cov-report=term-missing
markers =
    unit: Unit tests
    integration: Integration tests
EOF

cat > monitoring/grafana/provisioning/datasources/prometheus.yml <<'EOF'
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
EOF

cat > monitoring/grafana/provisioning/dashboards/dashboard.yml <<'EOF'
apiVersion: 1

providers:
  - name: 'NextProject Dashboards'
    orgId: 1
    folder: ''
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    allowUiUpdates: true
    options:
      path: /etc/grafana/provisioning/dashboards
EOF

cat > k8s/overlays/dev/kustomization.yaml <<'EOF'
resources:
  - ../../base
namespace: nextproject-dev
EOF

cat > k8s/overlays/prod/kustomization.yaml <<'EOF'
resources:
  - ../../base
namespace: nextproject-prod
EOF

echo "已完成："
echo "1. 测试目录与 pytest 配置"
echo "2. Grafana provisioning 配置"
echo "3. K8s 目录骨架"
echo "4. MinIO 依赖声明"
echo ""
echo "下一步："
echo "1. 生成并写入 SECRET_KEY："
echo "   python3 -c 'import secrets; print(secrets.token_urlsafe(32))'"
echo "2. 重新构建镜像："
echo "   docker compose build main-service"
echo "3. 运行测试："
echo "   docker compose run --rm test"
echo "4. 启动服务："
echo "   docker compose up -d"
