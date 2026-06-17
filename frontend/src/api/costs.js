import { buildQuery, request } from './client'

export const costApi = {
  getModelUsageSummary: (params = {}) => request(`/model-usage/summary/${buildQuery(params)}`),
}
