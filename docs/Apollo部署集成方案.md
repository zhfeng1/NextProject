# Apollo 部署系统集成方案

## 文档信息
- **版本**：2.0.0
- **创建日期**：2025-03
- **适用范围**：NextProject v2.0 生产环境部署
- **前置阅读**：[基础设施环境说明.md](./基础设施环境说明.md)

---

## 一、概述

NextProject 采用 Apollo 部署系统进行生产环境（K8s）的自动化部署。本文档基于 ocean-km 项目的部署流程（`update.sh`），详细说明如何将 NextProject 集成到 Apollo 部署系统。

---

## 二、Apollo 部署系统架构

### 2.1 系统组件

```
┌─────────────────────────────────────────────────────────┐
│                    开发者本地环境                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  1. 构建 Docker 镜像                             │  │
│  │  2. 推送到 Harbor (192.168.1.18)                │  │
│  │  3. 调用 Apollo API                              │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│              Apollo 部署系统 (192.168.1.15:90)          │
│  ┌──────────────────────────────────────────────────┐  │
│  │  认证服务 (/apollo/user/login)                   │  │
│  │  部署引擎 (/devops/cicd/v1.0/job/deployByImage)  │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│              Harbor 镜像仓库 (harbor.trscd.com.cn)      │
│  ┌──────────────────────────────────────────────────┐  │
│  │  ocean-km/site-builder:t20250320.1430           │  │
│  │  ocean-km/km-app:t20250320.1400                 │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│          Kubernetes 集群 (Namespace: ocean-km)          │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Deployment: site-builder (replicas: 3)         │  │
│  │  Service: site-builder-svc                       │  │
│  │  Ingress: sites.example.com                      │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 2.2 部署流程

```
开发者提交代码
    ↓
本地构建 Docker 镜像
    ↓
推送镜像到 Harbor (内网)
    ↓
调用 Apollo 登录接口
    ↓
获取 X-User-Token
    ↓
调用 Apollo 部署接口
    ↓
Apollo 从 Harbor 拉取镜像 (公网)
    ↓
更新 K8s Deployment
    ↓
滚动更新 Pod
    ↓
部署完成
```

---

## 三、后端代码集成

### 3.1 数据模型扩展

在现有的 `site_deploy_config` 表基础上，添加 Apollo 相关字段：

```python
# backend/models/site.py

class SiteDeployConfig(Base):
    __tablename__ = "site_deploy_config"

    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"), primary_key=True)

    # 部署目标类型
    target_type = Column(String(20), default="local")  # local / apollo

    # ==================== Apollo K8s 配置 ====================
    # Apollo 系统配置
    apollo_api_base = Column(String(255), default="http://192.168.1.15:90")
    apollo_system_id = Column(String(64), default="B6EF6BD39FE8C3DCA1B5E13AAD516BC3")
    apollo_app_id = Column(Integer, nullable=True)  # Apollo 中的应用 ID

    # Harbor 配置
    harbor_domain_internal = Column(String(255), default="192.168.1.18")
    harbor_domain_public = Column(String(255), default="harbor.trscd.com.cn")
    harbor_namespace = Column(String(100), default="ocean-km")

    # 登录凭据（RSA 加密后的值）
    apollo_login_tel_encrypted = Column(Text)
    apollo_login_password_encrypted = Column(Text)
    apollo_login_random = Column(Integer, default=49356)

    # 部署配置
    module_name = Column(String(100))  # 模块名称（用于镜像命名）
    k8s_namespace = Column(String(100), default="ocean-km")
    k8s_replicas = Column(Integer, default=3)

    # 额外的 HTTP 请求头（JSON 格式）
    apollo_extra_headers = Column(JSONB, default={})

    # 时间戳
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), onupdate=func.now())
```

---

### 3.2 Apollo 部署服务

```python
# backend/services/apollo_deploy_service.py

import time
import subprocess
import httpx
from pathlib import Path
from typing import Dict, Any

from backend.models import Site, SiteDeployConfig
from backend.core.config import settings

class ApolloDeployService:
    """Apollo 部署系统集成服务"""

    def __init__(self):
        self.http_client = httpx.Client(timeout=30, verify=False)

    async def deploy_site_to_apollo(
        self,
        site: Site,
        deploy_config: SiteDeployConfig,
        task_id: str  # 用于日志记录
    ) -> Dict[str, Any]:
        """
        将站点部署到 Apollo K8s 集群

        Args:
            site: 站点对象
            deploy_config: 部署配置
            task_id: 任务 ID（用于记录日志）

        Returns:
            部署结果字典
        """
        try:
            # 1. 构建并推送 Docker 镜像
            image_full_name = await self._build_and_push_image(
                site, deploy_config, task_id
            )

            # 2. 登录 Apollo 系统
            token = await self._login_apollo(deploy_config, task_id)

            # 3. 调用部署接口
            deploy_result = await self._trigger_deploy(
                deploy_config, image_full_name, token, task_id
            )

            return {
                "ok": True,
                "image": image_full_name,
                "deploy_response": deploy_result
            }

        except Exception as e:
            return {
                "ok": False,
                "error": str(e)
            }
        finally:
            self.http_client.close()

    async def _build_and_push_image(
        self,
        site: Site,
        deploy_config: SiteDeployConfig,
        task_id: str
    ) -> str:
        """
        构建并推送 Docker 镜像到 Harbor

        Returns:
            完整镜像名称（供 K8s 使用）
        """
        # 生成时间戳标签
        timestamp = time.strftime("%Y%m%d.%H%M")
        tag = f"t{timestamp}"

        module_name = deploy_config.module_name or site.site_id
        image_name = f"{module_name}:{tag}"

        # 内网推送地址
        harbor_internal = deploy_config.harbor_domain_internal
        namespace = deploy_config.harbor_namespace
        image_internal = f"{harbor_internal}/{namespace}/{image_name}"

        # 公网拉取地址（K8s 使用）
        harbor_public = deploy_config.harbor_domain_public
        image_public = f"{harbor_public}/{namespace}/{image_name}"

        site_root = Path(f"/generated_sites/{site.site_id}")

        # 确保 Dockerfile 存在
        dockerfile = site_root / "Dockerfile.deploy"
        if not dockerfile.exists():
            self._ensure_deploy_dockerfile(site_root)

        append_task_log(task_id, f"开始构建镜像：{image_internal}")

        # 构建镜像
        build_cmd = [
            "docker", "build",
            "--force-rm",
            "-t", image_internal,
            "-f", str(dockerfile),
            str(site_root)
        ]

        result = subprocess.run(
            build_cmd,
            capture_output=True,
            text=True,
            check=True
        )
        append_task_log(task_id, "✅ 镜像构建成功")

        # 推送到 Harbor
        append_task_log(task_id, f"推送镜像到 Harbor：{image_internal}")
        push_cmd = ["docker", "push", image_internal]
        subprocess.run(push_cmd, capture_output=True, text=True, check=True)
        append_task_log(task_id, "✅ 镜像推送成功")

        # 清理本地镜像
        time.sleep(3)
        subprocess.run(["docker", "rmi", image_internal], check=False)
        append_task_log(task_id, "🗑️  本地镜像已清理")

        return image_public

    async def _login_apollo(
        self,
        deploy_config: SiteDeployConfig,
        task_id: str
    ) -> str:
        """
        登录 Apollo 系统获取 Token

        Returns:
            X-User-Token
        """
        append_task_log(task_id, "正在登录 Apollo 系统...")

        login_url = f"{deploy_config.apollo_api_base}/apollo/user/login"

        # 构建登录请求体（使用加密凭据）
        payload = {
            "tel": deploy_config.apollo_login_tel_encrypted,
            "password": deploy_config.apollo_login_password_encrypted,
            "rememberMe": True,
            "random": deploy_config.apollo_login_random
        }

        # 请求头
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "System-Id": deploy_config.apollo_system_id,
            "Origin": deploy_config.apollo_api_base,
            "Referer": f"{deploy_config.apollo_api_base}/apollo-web/",
        }

        # 合并额外请求头
        if deploy_config.apollo_extra_headers:
            headers.update(deploy_config.apollo_extra_headers)

        response = self.http_client.post(
            login_url,
            json=payload,
            headers=headers
        )
        response.raise_for_status()

        # 解析 Token
        data = response.json()

        # 支持两种响应格式
        token = None
        if "data" in data and isinstance(data["data"], dict):
            token = data["data"].get("token")
        else:
            token = data.get("token")

        if not token:
            raise RuntimeError(f"获取 Token 失败：{data}")

        append_task_log(task_id, f"✅ 登录成功，Token: {token[:20]}...")
        return token

    async def _trigger_deploy(
        self,
        deploy_config: SiteDeployConfig,
        image_full_name: str,
        token: str,
        task_id: str
    ) -> Dict[str, Any]:
        """
        调用 Apollo 部署接口

        Args:
            deploy_config: 部署配置
            image_full_name: 完整镜像名称
            token: 认证 Token
            task_id: 任务 ID

        Returns:
            部署响应数据
        """
        append_task_log(task_id, f"正在部署镜像：{image_full_name}")

        deploy_url = f"{deploy_config.apollo_api_base}/devops/cicd/v1.0/job/deployByImage"

        # 生成随机数（防重放）
        random_num = int(time.time()) % 100000

        # 请求体
        payload = {
            "appId": deploy_config.apollo_app_id,
            "image": image_full_name,
            "random": random_num
        }

        # 请求头
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "System-Id": deploy_config.apollo_system_id,
            "X-User-Token": token,
            "Origin": deploy_config.apollo_api_base,
            "Referer": f"{deploy_config.apollo_api_base}/apollo-web/",
        }

        # 合并额外请求头
        if deploy_config.apollo_extra_headers:
            headers.update(deploy_config.apollo_extra_headers)

        response = self.http_client.post(
            deploy_url,
            json=payload,
            headers=headers
        )
        response.raise_for_status()

        data = response.json()
        append_task_log(task_id, f"部署响应：{data}")

        # 检查部署结果
        code = data.get("code", "")
        if code != "00000":
            raise RuntimeError(f"部署失败：{data.get('message', '未知错误')}")

        append_task_log(task_id, "✅ 部署成功！")
        return data

    def _ensure_deploy_dockerfile(self, site_root: Path):
        """生成部署用的 Dockerfile"""
        dockerfile = site_root / "Dockerfile.deploy"
        dockerfile.write_text("""
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --production
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend
COPY --from=frontend-build /build/dist ./frontend

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \\
  CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8080"]
""")
```

---

### 3.3 Celery 任务集成

```python
# backend/tasks/deploy.py

from celery import Task
from backend.core.celery_app import celery_app
from backend.services.apollo_deploy_service import ApolloDeployService
from backend.models import Site, SiteDeployConfig, TaskStatus

@celery_app.task(bind=True, max_retries=1)
def deploy_to_apollo_task(self, task_id: str, site_id: str):
    """
    部署站点到 Apollo K8s 集群

    Args:
        task_id: 任务 ID
        site_id: 站点 ID
    """
    try:
        # 更新任务状态
        update_task_status(task_id, TaskStatus.RUNNING)
        append_task_log(task_id, "开始 Apollo 部署流程")

        # 获取站点和部署配置
        site = get_site(site_id)
        deploy_config = get_site_deploy_config(site_id)

        # 验证配置
        if not deploy_config.apollo_app_id:
            raise ValueError("未配置 Apollo App ID，请联系管理员")

        if not deploy_config.apollo_login_tel_encrypted:
            raise ValueError("未配置 Apollo 登录凭据")

        # 执行部署
        apollo_service = ApolloDeployService()
        result = await apollo_service.deploy_site_to_apollo(
            site, deploy_config, task_id
        )

        if not result["ok"]:
            raise RuntimeError(result.get("error", "部署失败"))

        # 更新任务状态
        update_task_status(task_id, TaskStatus.SUCCESS, result=result)
        append_task_log(task_id, "🎉 Apollo 部署完成！")

        return result

    except Exception as exc:
        append_task_log(task_id, f"❌ 部署失败：{exc}", "ERROR")
        update_task_status(task_id, TaskStatus.FAILED, error=str(exc))
        raise
```

---

### 3.4 API 端点

```python
# backend/api/v2/deploy.py

from fastapi import APIRouter, Depends
from backend.tasks.deploy import deploy_to_apollo_task
from backend.schemas.task import TaskCreateRequest

router = APIRouter(prefix="/api/v2/deploy", tags=["Deploy"])

@router.post("/apollo")
async def deploy_to_apollo(
    site_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    部署站点到 Apollo K8s 集群

    **流程：**
    1. 构建 Docker 镜像
    2. 推送到 Harbor
    3. 登录 Apollo 系统
    4. 调用部署 API

    **权限：** 需要 deploy 权限
    """
    # 检查权限
    if not current_user.has_permission("deploy"):
        raise HTTPException(403, "无部署权限")

    # 获取站点
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "站点不存在")

    # 检查站点所属组织
    if site.org_id != current_user.default_org_id:
        raise HTTPException(403, "无权操作此站点")

    # 创建任务
    task = Task(
        id=uuid.uuid4(),
        site_id=site.id,
        task_type="deploy_apollo",
        status=TaskStatus.QUEUED,
        created_by=current_user.id,
    )
    db.add(task)
    await db.commit()

    # 提交到 Celery
    deploy_to_apollo_task.apply_async(
        args=[str(task.id), str(site.id)],
        queue="deploy-tasks",
        priority=8,  # 高优先级
    )

    return {
        "ok": True,
        "task_id": str(task.id),
        "message": "部署任务已创建，请查看任务日志"
    }
```

---

## 四、前端集成

### 4.1 部署配置表单

```vue
<!-- src/views/Sites/components/DeployConfigForm.vue -->
<template>
  <el-form :model="config" label-width="150px">
    <el-divider content-position="left">Apollo 配置</el-divider>

    <el-form-item label="App ID" required>
      <el-input-number v-model="config.apollo_app_id" :min="1" />
      <div class="form-tip">
        Apollo 系统中的应用 ID，需向管理员申请
      </div>
    </el-form-item>

    <el-form-item label="模块名称">
      <el-input v-model="config.module_name" placeholder="site-builder" />
      <div class="form-tip">
        用于 Docker 镜像命名，留空则使用站点 ID
      </div>
    </el-form-item>

    <el-form-item label="K8s 副本数">
      <el-input-number v-model="config.k8s_replicas" :min="1" :max="10" />
    </el-form-item>

    <el-divider content-position="left">Harbor 配置</el-divider>

    <el-form-item label="内网地址">
      <el-input v-model="config.harbor_domain_internal" readonly />
    </el-form-item>

    <el-form-item label="公网地址">
      <el-input v-model="config.harbor_domain_public" readonly />
    </el-form-item>

    <el-form-item label="Namespace">
      <el-input v-model="config.harbor_namespace" readonly />
    </el-form-item>

    <el-divider content-position="left">认证配置</el-divider>

    <el-alert type="warning" :closable="false" style="margin-bottom: 20px">
      <p>登录凭据需使用 RSA 公钥加密后填入</p>
      <p>请联系管理员获取加密后的凭据</p>
    </el-alert>

    <el-form-item label="加密手机号">
      <el-input
        v-model="config.apollo_login_tel_encrypted"
        type="textarea"
        :rows="3"
        placeholder="RSA 加密后的手机号"
      />
    </el-form-item>

    <el-form-item label="加密密码">
      <el-input
        v-model="config.apollo_login_password_encrypted"
        type="textarea"
        :rows="3"
        placeholder="RSA 加密后的密码"
      />
    </el-form-item>

    <el-form-item>
      <el-button type="primary" @click="saveConfig">保存配置</el-button>
      <el-button @click="testConnection">测试连接</el-button>
    </el-form-item>
  </el-form>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { deploysAPI } from '@/api/deploy'

const props = defineProps<{
  siteId: string
}>()

const config = ref({
  apollo_app_id: null,
  module_name: '',
  k8s_replicas: 3,
  harbor_domain_internal: '192.168.1.18',
  harbor_domain_public: 'harbor.trscd.com.cn',
  harbor_namespace: 'ocean-km',
  apollo_login_tel_encrypted: '',
  apollo_login_password_encrypted: '',
})

onMounted(async () => {
  // 加载配置
  const response = await deploysAPI.getConfig(props.siteId)
  Object.assign(config.value, response.deploy_config)
})

const saveConfig = async () => {
  try {
    await deploysAPI.updateConfig(props.siteId, config.value)
    ElMessage.success('配置已保存')
  } catch (error) {
    ElMessage.error('保存失败')
  }
}

const testConnection = async () => {
  try {
    await deploysAPI.testConnection(props.siteId)
    ElMessage.success('连接测试成功')
  } catch (error) {
    ElMessage.error('连接测试失败')
  }
}
</script>
```

### 4.2 部署按钮

```vue
<!-- src/views/Sites/SiteDetail.vue -->
<template>
  <div class="site-detail">
    <!-- ... 其他内容 ... -->

    <el-card>
      <template #header>部署</template>

      <el-radio-group v-model="deployTarget">
        <el-radio-button label="local">本地部署</el-radio-button>
        <el-radio-button label="apollo">生产部署 (K8s)</el-radio-button>
      </el-radio-group>

      <el-button
        type="primary"
        @click="deployToApollo"
        :loading="deploying"
        :disabled="deployTarget !== 'apollo' || !apolloConfigured"
        style="margin-top: 20px"
      >
        <el-icon><Upload /></el-icon>
        部署到 Apollo
      </el-button>

      <div v-if="!apolloConfigured" class="warning-tip">
        ⚠️ 未配置 Apollo 部署参数，请先
        <el-button type="text" @click="showConfigDialog = true">
          配置部署参数
        </el-button>
      </div>
    </el-card>

    <!-- 部署配置对话框 -->
    <el-dialog v-model="showConfigDialog" title="Apollo 部署配置" width="600px">
      <DeployConfigForm :site-id="siteId" @saved="onConfigSaved" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deploysAPI } from '@/api/deploy'
import DeployConfigForm from './components/DeployConfigForm.vue'

const props = defineProps<{
  siteId: string
}>()

const deployTarget = ref('local')
const deploying = ref(false)
const apolloConfigured = ref(false)
const showConfigDialog = ref(false)

const deployToApollo = async () => {
  try {
    await ElMessageBox.confirm(
      '确定部署到生产环境（K8s）吗？',
      '确认部署',
      { type: 'warning' }
    )

    deploying.value = true

    const response = await deploysAPI.deployToApollo(props.siteId)

    ElMessage.success('部署任务已创建')

    // 跳转到任务详情页
    router.push({ name: 'TaskDetail', params: { id: response.task_id } })

  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('部署失败')
    }
  } finally {
    deploying.value = false
  }
}

const onConfigSaved = () => {
  apolloConfigured.value = true
  showConfigDialog.value = false
  ElMessage.success('配置已保存，现在可以部署到 Apollo')
}
</script>
```

---

## 五、安全加固

### 5.1 RSA 加密凭据

**为什么需要加密？**
- Apollo 登录凭据不能明文存储在数据库中
- 需要使用 RSA 公钥加密后存储
- 部署时使用加密后的值直接发送给 Apollo API

**加密工具脚本**

```python
# scripts/encrypt_apollo_credentials.py
"""
Apollo 登录凭据加密工具

使用方法：
  python encrypt_apollo_credentials.py --phone 13800138000 --password mypassword
"""

import argparse
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
import base64

# Apollo 系统的 RSA 公钥（需从 Apollo 管理员处获取）
APOLLO_PUBLIC_KEY = """
-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC...（省略）
-----END PUBLIC KEY-----
"""

def encrypt_with_rsa(plain_text: str, public_key: str) -> str:
    """使用 RSA 公钥加密"""
    key = RSA.importKey(public_key)
    cipher = PKCS1_v1_5.new(key)
    encrypted = cipher.encrypt(plain_text.encode('utf-8'))
    return base64.b64encode(encrypted).decode('utf-8')

def main():
    parser = argparse.ArgumentParser(description='加密 Apollo 登录凭据')
    parser.add_argument('--phone', required=True, help='手机号')
    parser.add_argument('--password', required=True, help='密码')

    args = parser.parse_args()

    encrypted_phone = encrypt_with_rsa(args.phone, APOLLO_PUBLIC_KEY)
    encrypted_password = encrypt_with_rsa(args.password, APOLLO_PUBLIC_KEY)

    print("✅ 加密完成！")
    print("\n加密后的手机号（复制到配置中）：")
    print(encrypted_phone)
    print("\n加密后的密码（复制到配置中）：")
    print(encrypted_password)

if __name__ == '__main__':
    main()
```

**使用示例**

```bash
# 安装依赖
pip install pycryptodome

# 加密凭据
python scripts/encrypt_apollo_credentials.py \
  --phone 13800138000 \
  --password MySecurePassword123

# 输出：
# ✅ 加密完成！
#
# 加密后的手机号：
# G3ZTp9bJygF/6nrTYc+JRSUCNn0GGjfpq92ULDKi0rGRuC4282Iyy8detP5wAPY5...
#
# 加密后的密码：
# g0USWa0498nV3Z3JRuQ2fj58DpOwooIepYYfmjhfz29P8JbAI96lwKLGCjIey6X8...
```

### 5.2 权限控制

```python
# backend/services/permission_service.py

class PermissionService:
    """权限管理服务"""

    @staticmethod
    def can_deploy_to_apollo(user: User, site: Site) -> bool:
        """检查用户是否有 Apollo 部署权限"""

        # 1. 必须是站点所属组织成员
        if site.org_id != user.default_org_id:
            return False

        # 2. 必须有 deploy 角色
        if not user.has_role("deploy"):
            return False

        # 3. 生产环境部署需要额外审批（可选）
        if settings.REQUIRE_DEPLOY_APPROVAL:
            # 检查是否有审批记录
            approval = get_deploy_approval(site.id, user.id)
            if not approval or approval.status != "approved":
                return False

        return True
```

---

## 六、监控与告警

### 6.1 部署事件追踪

```python
# backend/models/deploy_history.py

class DeployHistory(Base):
    """部署历史记录"""
    __tablename__ = "deploy_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"))
    task_id = Column(UUID(as_uuid=True), ForeignKey("agent_tasks.id"))

    # 部署信息
    deploy_type = Column(String(20))  # local / apollo
    image_name = Column(String(255))  # harbor.trscd.com.cn/ocean-km/site:t...
    apollo_app_id = Column(Integer, nullable=True)

    # 状态
    status = Column(String(20))  # deploying / success / failed / rollback
    error_message = Column(Text)

    # 时间
    started_at = Column(TIMESTAMP(timezone=True))
    finished_at = Column(TIMESTAMP(timezone=True))
    duration_seconds = Column(Integer)  # 部署耗时（秒）

    # 元数据
    deployed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    rollback_from = Column(UUID(as_uuid=True), ForeignKey("deploy_history.id"), nullable=True)
```

### 6.2 Prometheus 指标

```python
# backend/core/metrics.py

from prometheus_client import Counter, Histogram

# 部署次数
deploy_total = Counter(
    "deploy_total",
    "Total number of deployments",
    ["deploy_type", "status"]  # local/apollo, success/failed
)

# 部署耗时
deploy_duration_seconds = Histogram(
    "deploy_duration_seconds",
    "Deployment duration in seconds",
    ["deploy_type"],
    buckets=[10, 30, 60, 120, 300, 600, 1800]  # 10s, 30s, 1m, 2m, 5m, 10m, 30m
)

# 使用示例
def track_deployment(deploy_type: str, duration: float, success: bool):
    status = "success" if success else "failed"
    deploy_total.labels(deploy_type=deploy_type, status=status).inc()
    deploy_duration_seconds.labels(deploy_type=deploy_type).observe(duration)
```

---

## 七、故障排查

### 7.1 常见错误

| 错误信息 | 原因 | 解决方案 |
|----------|------|----------|
| `获取 Token 失败` | 登录凭据错误 | 检查加密凭据是否正确 |
| `部署失败：镜像不存在` | Harbor 中找不到镜像 | 检查镜像推送是否成功 |
| `部署失败：应用不存在` | App ID 错误 | 联系 Apollo 管理员确认 App ID |
| `docker push 失败` | Harbor 认证失败 | `docker login 192.168.1.18` |
| `K8s Pod 启动失败` | 镜像拉取失败 | 检查 K8s imagePullSecrets 配置 |

### 7.2 调试命令

```bash
# 1. 检查镜像是否存在
curl -u username:password \
  https://harbor.trscd.com.cn/api/v2.0/projects/ocean-km/repositories/site-builder/artifacts

# 2. 查看 K8s 部署状态
kubectl get pods -n ocean-km -l app=site-builder

# 3. 查看 Pod 日志
kubectl logs -n ocean-km -l app=site-builder --tail=100

# 4. 查看部署事件
kubectl describe deployment site-builder -n ocean-km
```

---

## 八、最佳实践

### 8.1 部署流程规范

1. **开发环境测试** → 确保本地功能正常
2. **提交代码审查** → 通过 Code Review
3. **运行单元测试** → 测试覆盖率 > 80%
4. **运行集成测试** → E2E 测试通过
5. **构建镜像** → Docker 构建成功
6. **推送到 Harbor** → 镜像可访问
7. **部署到 Staging** → 预发布环境验证
8. **生产环境部署** → Apollo 部署
9. **健康检查** → 确认 Pod 运行正常
10. **监控观察** → 观察 15 分钟，无异常

### 8.2 回滚策略

```python
# backend/services/rollback_service.py

class RollbackService:
    """部署回滚服务"""

    async def rollback_to_previous_version(
        self,
        site_id: str,
        deploy_history_id: str
    ):
        """回滚到上一个成功的部署版本"""

        # 1. 查找上一次成功的部署
        previous_deploy = await self._get_previous_successful_deploy(site_id)

        if not previous_deploy:
            raise ValueError("未找到可回滚的版本")

        # 2. 使用上一次的镜像重新部署
        await self._redeploy_with_image(
            site_id,
            previous_deploy.image_name,
            rollback_from=deploy_history_id
        )
```

---

## 九、附录

### 9.1 Apollo API 完整文档

**登录接口**

```
POST /apollo/user/login
Headers:
  - System-Id: B6EF6BD39FE8C3DCA1B5E13AAD516BC3
  - Content-Type: application/json

Body:
{
  "tel": "{RSA加密}",
  "password": "{RSA加密}",
  "rememberMe": true,
  "random": 49356
}

Response:
{
  "code": "00000",
  "data": {
    "token": "eyJhbGci..."
  }
}
```

**部署接口**

```
POST /devops/cicd/v1.0/job/deployByImage
Headers:
  - System-Id: B6EF6BD39FE8C3DCA1B5E13AAD516BC3
  - X-User-Token: {从登录接口获取}
  - Content-Type: application/json

Body:
{
  "appId": 53,
  "image": "harbor.trscd.com.cn/ocean-km/km-app:t20250320.1430",
  "random": 12345
}

Response:
{
  "code": "00000",
  "message": "部署成功"
}
```

---

**文档版本**：2.0.0
**维护者**：DevOps 团队
**最后更新**：2025-03
