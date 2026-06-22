import { request } from './client'
import type { DocumentParseRun, DocumentRecord, ParsePreview } from '../types/api'

export const documentApi = {
  listDocuments: () => request<DocumentRecord[]>('/documents/'),
  uploadDocument: (kb: number, file: File) => {
    const form = new FormData()
    form.append('kb', String(kb))
    form.append('file', file)
    return request<DocumentRecord>('/documents/', { method: 'POST', body: form })
  },
  parseDocument: (id: number) =>
    request<DocumentParseRun>(`/documents/${id}/parse/`, { method: 'POST', body: JSON.stringify({}) }),
  getParseStatus: (id: number) => request<DocumentParseRun>(`/documents/${id}/parse-status/`),
  getParsePreview: (id: number, page = 1, parseRunId?: number) => {
    const query = new URLSearchParams({ page: String(page) })
    if (parseRunId) query.set('parse_run_id', String(parseRunId))
    return request<ParsePreview>(`/documents/${id}/parse-preview/?${query.toString()}`)
  },
  acceptParse: (id: number, parseRunId?: number) =>
    request<DocumentParseRun>(`/documents/${id}/accept-parse/`, {
      method: 'POST',
      body: JSON.stringify(parseRunId ? { parse_run_id: parseRunId } : {}),
    }),
  previewChunks: (id: number, payload: Record<string, unknown>) =>
    request<{ chunks: import('../types/api').ChunkRecord[]; stats: Record<string, number> }>(
      `/documents/${id}/chunk-preview/`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  indexDocument: (id: number, payload: Record<string, unknown>) =>
    request<any>(`/documents/${id}/index/`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
