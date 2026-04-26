# Roadmap: NextProject

## Overview

本路线图采用 direct 分解策略，并在最小 phase 原则下保留 2 个 phase：先补齐执行可信度、隔离、版本与监控基础，再在其上收敛“需求 → 生成/调整 → 测试 → 部署”的主链路体验与多角色易用性。这样既延续 brownfield 渐进演进路线，又把“快且可迭代、质量高”落到真实可验证的产品行为上。

## Phases

- [ ] **Phase 1: Execution Trust Foundation** - 先把任务执行、版本回滚、运行时隔离与可观测性做成可信底座
- [ ] **Phase 2: Workflow and Usability Convergence** - 在可信底座上收敛主链路工作流，并显著提升三类用户的易用性

## Phase Details

### Phase 1: Execution Trust Foundation
**Goal**: 建立可信的任务执行、运行时隔离、版本恢复与监控基础，让平台先具备“结果可信、失败可诊断、问题可回滚”的底座。
**Depends on**: Nothing (first phase)
**Requirements**: REQ-003 强化平台可靠性与隔离能力，包括容器化子站点、版本回滚、监控告警和更稳定的任务执行能力
**Success Criteria** (what must be TRUE):
  1. 任务执行结果能够真实反映预览重启、部署与关键后处理是否成功，失败不会再以成功态误导用户。
  2. 子站点运行与任务执行具备更明确的隔离边界，关键高风险路径不再默认依赖宿主级权限。
  3. 版本快照、回滚与基础监控成为可依赖能力，出现异常时可以定位、恢复并给出清晰状态。

### Phase 2: Workflow and Usability Convergence
**Goal**: 在可信底座上把需求到部署的主链路收敛为更顺畅的高质量迭代工作流，并让程序员、项目经理和普通用户都能稳定完成核心操作。
**Depends on**: Phase 1
**Requirements**: REQ-001 把“需求 → 生成/调整 → 测试 → 部署”的主链路进一步打磨成快速且高质量的可迭代工作流；REQ-002 明显提升易用性，让程序员、项目经理和普通用户都能顺畅完成核心操作
**Success Criteria** (what must be TRUE):
  1. 用户可以围绕单个站点连续完成需求整理、生成/调整、测试验证、部署发布与结果回看，不需要在分散页面和不一致状态之间来回切换。
  2. 程序员、项目经理和普通用户都能理解当前任务阶段、结果质量与下一步动作，核心反馈不再依赖技术背景才能读懂。
  3. 主链路中的关键操作具备更清晰的默认路径、失败提示与恢复路径，迭代效率提升且不会以牺牲质量保障为代价。

## Scope Decisions

- **In scope**: 任务执行可信度、预览/部署结果真实性、子站点与任务隔离、版本回滚可信度、基础监控告警、围绕站点的端到端工作流收敛、多角色可用性提升、关键状态与结果表达统一
- **Deferred**: 全技术栈通用低代码能力、全面微服务拆分、一次性重写 legacy `/api/*` 与所有历史模块
- **Out of scope**: 为了追求生成速度而削弱测试、回滚、监控与可维护性；在当前阶段同时扩张到所有部署平台与所有技术栈

## Progress

| Phase | Status | Completed |
|-------|--------|-----------|
| 1. Execution Trust Foundation | Not started | - |
| 2. Workflow and Usability Convergence | Not started | - |
