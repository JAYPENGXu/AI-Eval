import { buildQuery, request } from './client'
import type { QueryParams } from '../types/api'

export const operationsApi = {
  getIndexStatus: (id: number) => request<any>(`/documents/${id}/index-status/`),
  getKbIndexHealth: (id: number) => request<any>(`/knowledge-bases/${id}/index-health/`),
  reindexStale: (id: number) => request<any[]>(`/knowledge-bases/${id}/reindex-stale/`, { method: 'POST', body: '{}' }),
  listParseCases: (params: QueryParams = {}) => request<any[]>(`/document-parse-cases/${buildQuery(params)}`),
  createParseCase: (payload: Record<string, any>) => {
    const form = new FormData()
    Object.entries(payload).forEach(([key, value]) => {
      if (value instanceof File) form.append(key, value)
      else if (value !== undefined && value !== null) form.append(key, typeof value === 'object' ? JSON.stringify(value) : String(value))
    })
    return request<any>('/document-parse-cases/', { method: 'POST', body: form })
  },
  deleteParseCase: (id: number) => request<void>(`/document-parse-cases/${id}/`, { method: 'DELETE' }),
  listParseEvalRuns: (params: QueryParams = {}) => request<any[]>(`/document-parse-eval-runs/${buildQuery(params)}`),
  getParseEvalRun: (id: number) => request<any>(`/document-parse-eval-runs/${id}/`),
  runParseEval: (suite: string) => request<any>('/document-parse-eval-runs/run/', { method: 'POST', body: JSON.stringify({ suite }) }),
  listConfigVersions: (kb: number) => request<any[]>(`/rag-config-versions/${buildQuery({ kb })}`),
  listConfigDeployments: (kb: number) => request<any[]>(`/rag-config-deployments/${buildQuery({ kb })}`),
  requestPublishConfig: (id: number) => request<any>(`/rag-config-versions/${id}/request-publish/`, { method: 'POST', body: '{}' }),
  requestRollbackConfig: (id: number, reason = '') => request<any>(`/rag-config-versions/${id}/request-rollback/`, { method: 'POST', body: JSON.stringify({ reason }) }),
  systemHealth: () => request<any>('/system-health/'),
}
