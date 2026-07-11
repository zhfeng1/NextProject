import client from './client'
import type { ApiFormat } from './providers'

export interface ProgrammingTool {
  id: string
  label: string
  version?: string | null
  visible?: boolean
  available: boolean
  healthy?: boolean
  configured?: boolean
  supported_formats: ApiFormat[]
  selected_format?: ApiFormat | null
  provider_id?: string | null
  provider_name?: string | null
  provider_scope?: 'global' | 'project' | null
  model?: string | null
  unavailable_reason?: string | null
  branch_prefix?: string
  supports_mcp?: boolean
}

export interface ProgrammingToolsResponse {
  ok: boolean
  tools: ProgrammingTool[]
}

const hiddenToolIds = new Set(['claude_code'])

export const PROGRAMMING_TOOL_IDS = ['codex', 'codebuddy', 'opencode', 'kimi_code'] as const
const programmingToolOrder = new Map<string, number>(PROGRAMMING_TOOL_IDS.map((toolId, index) => [toolId, index]))

const knownLabels: Record<string, string> = {
  codex: 'Codex',
  codebuddy: 'CodeBuddy',
  opencode: 'OpenCode',
  kimi_code: 'Kimi Code',
}

export function visibleProgrammingTools(tools: ProgrammingTool[] = []) {
  return tools
    .filter(tool => tool.visible !== false && !hiddenToolIds.has(tool.id))
    .sort((left, right) => (
      (programmingToolOrder.get(left.id) ?? Number.MAX_SAFE_INTEGER)
      - (programmingToolOrder.get(right.id) ?? Number.MAX_SAFE_INTEGER)
    ))
}

export function programmingToolLabel(toolId?: string, tools: ProgrammingTool[] = []) {
  if (!toolId || hiddenToolIds.has(toolId)) return '编程工具'
  const tool = visibleProgrammingTools(tools).find(item => item.id === toolId)
  return tool?.label || knownLabels[toolId] || '编程工具'
}

export function programmingToolReason(tool?: ProgrammingTool | null) {
  if (!tool) return '当前没有可用的编程工具'
  return tool.unavailable_reason || '当前编程工具暂不可用，请检查项目或全局模型配置以及适配器状态'
}

export const programmingToolsAPI = {
  list(projectId: string) {
    return client.get<any, ProgrammingToolsResponse>('/programming-tools', {
      params: { project_id: projectId },
    })
  },
}
