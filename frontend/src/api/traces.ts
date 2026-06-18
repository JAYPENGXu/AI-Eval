import { buildQuery, request } from './client'
import type { QueryParams, RagTrace } from '../types/api'

export const traceApi = {
  listTraces: (params: QueryParams = {}) => request<RagTrace[]>(`/rag-traces/${buildQuery(params)}`),
  getTrace: (id: number) => request<RagTrace>(`/rag-traces/${id}/`),
}
