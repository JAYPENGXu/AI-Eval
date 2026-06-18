import { buildQuery, request } from './client'
import type { ModelUsageSummary, QueryParams } from '../types/api'

export const costApi = {
  getModelUsageSummary: (params: QueryParams = {}) =>
    request<ModelUsageSummary>(`/model-usage/summary/${buildQuery(params)}`),
}
