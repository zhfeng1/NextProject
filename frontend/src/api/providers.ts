import client from './client'

export interface LLMProvider {
  id: string
  user_id: string
  name: string
  base_url: string
  api_key: string
  models: string[]
  format: 'responses' | 'messages'
  is_default: boolean
  created_at: string | null
  updated_at: string | null
}

export type LLMProviderCreate = Partial<Omit<LLMProvider, 'id' | 'user_id' | 'created_at' | 'updated_at'>>

export const providersAPI = {
  list() {
    return client.get<any, { ok: boolean; providers: LLMProvider[] }>('/providers')
  },

  create(data: LLMProviderCreate) {
    return client.post<any, { ok: boolean; provider: LLMProvider }>('/providers', data)
  },

  update(id: string, data: LLMProviderCreate) {
    return client.put<any, { ok: boolean; provider: LLMProvider }>(`/providers/${id}`, data)
  },

  remove(id: string) {
    return client.delete(`/providers/${id}`)
  },

  fetchModels(data: { base_url: string; api_key: string }) {
    return client.post<any, { ok: boolean; models: string[]; error?: string }>('/providers/fetch-models', data)
  },

  verifyModel(data: { provider_id: string; model: string }) {
    return client.post<any, { ok: boolean; message?: string; error?: string }>('/providers/verify-model', data)
  },
}
