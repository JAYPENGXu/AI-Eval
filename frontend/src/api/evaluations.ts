import { buildQuery, request } from './client'
import type { QueryParams, RagEvalRun, RagOptions } from '../types/api'

export const evaluationApi = {
  listEvalRuns: (params: QueryParams = {}) => request<RagEvalRun[]>(`/rag-eval-runs/${buildQuery(params)}`),
  getEvalRun: (id: number) => request<RagEvalRun>(`/rag-eval-runs/${id}/`),
  runEval: (payload: Record<string, unknown>) =>
    request<RagEvalRun>('/rag-eval-runs/run/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}

export type { RagOptions }
