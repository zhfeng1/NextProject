---
status: complete
phase: 02-multi-repo-project-model
source: 02-01-SUMMARY.md, 02-02-SUMMARY.md, 02-03-SUMMARY.md, 02-04-SUMMARY.md
started: 2026-04-23T08:00:00Z
updated: 2026-04-24T09:15:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: 停止所有服务后重新启动（docker compose down && ./start.sh --build）。服务正常启动无报错，Alembic 迁移自动完成，健康检查或首页可正常访问。
result: pass

### 2. 侧边栏导航更新
expected: 侧边栏显示"项目管理"菜单项（带 FolderKanban 图标），点击后跳转到 /projects 页面。原来的"站点管理/我的站点"已替换为"项目管理/我的项目"。
result: pass

### 3. 项目列表页面
expected: 访问 /projects 看到项目卡片网格布局。顶部有搜索框可过滤项目。无项目时显示空状态。
result: pass

### 4. 创建新项目
expected: 点击创建按钮弹出对话框，填写项目名称和描述后提交。新项目出现在列表中。
result: pass

### 5. 项目详情页面
expected: 点击项目卡片进入详情页，显示项目名称、描述等信息，以及该项目下的仓库列表。
result: pass

### 6. 添加仓库到项目
expected: 在项目详情页点击"添加仓库"，弹出对话框可输入仓库名称。支持空白创建和 git clone 两种方式（clone 方式需填 URL 和可选的 git 凭据）。提交后仓库出现在列表中。
result: issue
reported: "非git仓库新增后显示stopped。git clone仓库状态一直卡在building/克隆中。仓库名称必填项缺少必填标记。"
severity: major

### 7. 项目编辑器
expected: 在项目详情页点击"打开编辑器"跳转到 /projects/:id/edit。页面显示仓库 Tab 栏和文件树区域。
result: issue
reported: "可以打开，但无法返回上一个页面。空白仓库里默认代码还有用吗？"
severity: minor

### 8. 仓库 Tab 切换
expected: 编辑器页面顶部显示仓库 Tab。切换 Tab 后文件树自动刷新为对应仓库的文件列表。已打开的编辑器标签不会关闭。
result: pass

### 9. 文件浏览与查看
expected: 在文件树中点击文件，右侧打开编辑器标签页显示文件内容（只读模式）。标签页格式为 [repoName] filename。
result: issue
reported: "没问题，后面加点语法高亮吧"
severity: cosmetic

### 10. 删除项目
expected: 在项目详情页或列表页可以删除项目。删除后项目从列表消失。
result: issue
reported: "可以删除，仓库也要支持删除"
severity: minor

### 11. /sites 路由重定向
expected: 浏览器访问 /sites 自动重定向到 /projects 页面。
result: pass

## Summary

total: 11
passed: 7
issues: 4
pending: 0
skipped: 0
blocked: 0

## Gaps

- truth: "git clone 仓库提交后应正常开始克隆并完成"
  status: failed
  reason: "User reported: git clone仓库状态一直卡在building/克隆中"
  severity: major
  test: 6
  root_cause: "clone_repo Celery task 未注册到 worker（worker tasks 列表中无 clone_repo）"
  artifacts:
    - path: "backend/tasks/clone_repo.py"
      issue: "task 未被 celery app autodiscover"
  missing:
    - "将 clone_repo task 注册到 celery worker 的 task discovery"

- truth: "添加仓库表单必填项应有明确标记"
  status: failed
  reason: "User reported: 仓库名称必填项缺少必填标记"
  severity: cosmetic
  test: 6
  artifacts: []
  missing: []

- truth: "编辑器页面应可返回项目详情页"
  status: failed
  reason: "User reported: 打开编辑器后无法返回上一个页面"
  severity: minor
  test: 7
  artifacts: []
  missing: []

- truth: "空白仓库不应包含无用的默认模板代码"
  status: failed
  reason: "User reported: 空白仓库里默认代码还有用吗"
  severity: minor
  test: 7
  artifacts: []
  missing: []

- truth: "文件查看应支持语法高亮"
  status: failed
  reason: "User reported: 缺少语法高亮"
  severity: cosmetic
  test: 9
  artifacts: []
  missing: []

- truth: "仓库应支持单独删除"
  status: failed
  reason: "User reported: 仓库也要支持删除"
  severity: minor
  test: 10
  artifacts: []
  missing: []
