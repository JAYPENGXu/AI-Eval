import { request } from './client'
import type { DocumentRecord } from '../types/api'

export const documentApi = {
  listDocuments: () => request<DocumentRecord[]>('/documents/'),
  uploadDocument: (kb: number, file: File) => {
    const form = new FormData()
    form.append('kb', String(kb))
    form.append('file', file)
    return request<DocumentRecord>('/documents/', { method: 'POST', body: form })
  },
  previewChunks: (id: number, payload: Record<string, unknown>) =>
    request<{ chunks: import('../types/api').ChunkRecord[]; stats: Record<string, number> }>(
      `/documents/${id}/chunk-preview/`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  indexDocument: (id: number, payload: Record<string, unknown>) =>
    request<{ chunk_count: number }>(`/documents/${id}/index/`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
