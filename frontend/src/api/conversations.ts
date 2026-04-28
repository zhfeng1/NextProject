import client from './client'

export interface Conversation {
  id: string
  site_id: string
  title: string
  status: 'active' | 'archived'
  summary_text: string
  message_count: number
  last_message_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ConversationMessage {
  id: number
  conversation_id: string
  seq: number
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  message_type: 'text' | 'task_ref'
  provider: string
  task_id: string
  token_count: number
  created_at: string | null
}

export const conversationsAPI = {
  create(siteId: string, title?: string) {
    return client.post<any, { ok: boolean; conversation: Conversation }>(
      `/conversations/site/${siteId}`,
      title ? { title } : {},
    )
  },

  list(siteId: string, limit = 50) {
    return client.get<any, { ok: boolean; site_id: string; conversations: Conversation[] }>(
      `/conversations/site/${siteId}?limit=${limit}`,
    )
  },

  get(convId: string) {
    return client.get<any, { ok: boolean; conversation: Conversation & { messages: ConversationMessage[] } }>(
      `/conversations/${convId}`,
    )
  },

  sendMessage(
    convId: string,
    content: string,
    opts: { provider?: string; current_url?: string; selected_xpath?: string; console_errors?: string } = {},
  ) {
    return client.post<any, { ok: boolean; user_message: ConversationMessage; assistant_message?: ConversationMessage; task_id?: string; task?: Record<string, unknown> }>(
      `/conversations/${convId}/messages`,
      {
        content,
        provider: opts.provider ?? 'codex',
        current_url: opts.current_url ?? '',
        selected_xpath: opts.selected_xpath ?? '',
        console_errors: opts.console_errors ?? '',
      },
    )
  },

  listMessages(convId: string, limit = 100, afterSeq = 0) {
    return client.get<any, { ok: boolean; conv_id: string; messages: ConversationMessage[] }>(
      `/conversations/${convId}/messages?limit=${limit}&after_seq=${afterSeq}`,
    )
  },

  archive(convId: string) {
    return client.delete<any, { ok: boolean; conversation: Conversation }>(
      `/conversations/${convId}`,
    )
  },
}
