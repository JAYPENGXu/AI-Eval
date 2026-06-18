import { request } from './client'

export const knowledgeBaseApi = {
  chunkMethods: () => request<Array<{ value: string; label: string }>>('/chunk-methods/'),
  listKbs: () => request<import('../types/api').KnowledgeBase[]>('/knowledge-bases/'),
  createKb: (payload: Record<string, unknown>) =>
    request<import('../types/api').KnowledgeBase>('/knowledge-bases/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
