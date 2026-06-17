import { request } from './client'

export const knowledgeBaseApi = {
  chunkMethods: () => request('/chunk-methods/'),
  listKbs: () => request('/knowledge-bases/'),
  createKb: (payload) =>
    request('/knowledge-bases/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
