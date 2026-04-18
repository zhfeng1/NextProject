---
status: all_fixed
findings_in_scope: 7
fixed: 7
skipped: 0
iteration: 1
---

# Phase 02 审查修复报告

## 修复的高优先级发现

### R-09: `serialize_site` 缺少 `project_id` 字段输出
- **文件**: `backend/services/site_service.py`
- **修复**: 在序列化字典中增加 `project_id` 字段，值取自 `site.project_id`
- **提交**: `fix(02): serialize_site 补充 project_id 字段输出 (R-09)`

### R-14: 前端 `Site.status` 类型缺少 `'error'` 枚举值
- **文件**: `frontend/src/types/models.ts`, `frontend/src/views/Projects/ProjectDetail.vue`
- **修复**: 将 `'failed'` 替换为 `'error'` 以匹配后端 `SiteStatus` 枚举；ProjectDetail 仓库卡片增加 error 状态红色样式
- **提交**: `fix(02): Site.status 类型补充 'error' 枚举值 (R-14)`

### R-23/R-24: `RepoFileTree` 文件树折叠/嵌套逻辑
- **文件**: `frontend/src/views/Projects/components/RepoFileTree.vue` (重写), `TreeNodeItem.vue` (新建)
- **修复**: 重写为递归树形数据结构 + 递归组件。每个目录节点独立维护 `expanded`/`loaded`/`children` 状态，点击目录仅加载该目录子项而非替换整个列表。折叠时隐藏子节点、展开时递归渲染。增加空目录和加载错误提示 (R-25)
- **提交**: `fix(02): RepoFileTree 重写为递归树形结构 (R-23/R-24)`

### R-22/R-21: `handleOpenFile` 错误处理 + 二进制文件检测
- **文件**: `frontend/src/views/Projects/ProjectEditor.vue`
- **修复**: `getRepoFile` 请求用 try/catch 包裹，失败时 toast 提示并阻止创建空 tab；检测 `res.binary === true` 时弹出警告并 return
- **提交**: `fix(02): handleOpenFile 增加错误处理和二进制文件检测 (R-22/R-21)`

### R-16/R-19: 克隆完成状态通知
- **文件**: `frontend/src/views/Projects/ProjectDetail.vue`
- **修复**: 采用轮询方案（每 5 秒）。通过 `watch` 监听 `hasBuildingRepos` 计算属性，有 building 仓库时开始轮询，所有仓库完成后停止轮询并 toast 通知用户。组件卸载时清理定时器
- **提交**: `fix(02): building 仓库轮询状态直到克隆完成 (R-16/R-19)`

## 修复的中优先级发现

### R-05: `delete_project` 缺少磁盘清理
- **文件**: `backend/services/project_service.py`
- **修复**: 软删数据库记录后，用 `shutil.rmtree` 清理 `generated_sites/{project_id}` 目录，`ignore_errors=True` 防止文件系统错误阻断
- **提交**: `fix(02): delete_project 补充磁盘目录清理 (R-05)`

### T-04: 同项目下重复仓库名检查
- **文件**: `backend/services/project_service.py`
- **修复**: `add_repo` 中验证仓库名后，查询现有仓库列表检查是否同名，重复时返回 HTTP 409
- **提交**: `fix(02): add_repo 增加同项目下仓库名唯一性检查 (T-04)`
