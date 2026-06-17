import { buildQuery, request } from './client'

export const evaluationApi = {
  listEvalRuns: (params = {}) => request(`/rag-eval-runs/${buildQuery(params)}`),
  getEvalRun: (id) => request(`/rag-eval-runs/${id}/`),
  runEval: (payload) =>
    request('/rag-eval-runs/run/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
