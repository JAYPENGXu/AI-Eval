import { buildQuery, request } from './client'

export const traceApi = {
  listTraces: (params = {}) => request(`/rag-traces/${buildQuery(params)}`),
  getTrace: (id) => request(`/rag-traces/${id}/`),
}
