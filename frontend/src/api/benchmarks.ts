import { buildQuery, request } from './client'
import type { QueryParams, RagBenchmarkCase } from '../types/api'

export const benchmarkApi = {
  listBenchmarkCases: (params: QueryParams = {}) =>
    request<RagBenchmarkCase[]>(`/rag-benchmark-cases/${buildQuery(params)}`),
  createBenchmarkCase: (payload: Record<string, unknown>) =>
    request<RagBenchmarkCase>('/rag-benchmark-cases/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateBenchmarkCase: (id: number, payload: Record<string, unknown>) =>
    request<RagBenchmarkCase>(`/rag-benchmark-cases/${id}/`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteBenchmarkCase: (id: number) =>
    request<void>(`/rag-benchmark-cases/${id}/`, {
      method: 'DELETE',
    }),
  importDefaultBenchmarkCases: (kb: number) =>
    request<{ created: number; updated: number; cases: RagBenchmarkCase[] }>(
      '/rag-benchmark-cases/import-defaults/',
      {
        method: 'POST',
        body: JSON.stringify({ kb }),
      },
    ),
  createBenchmarkCaseFromTrace: (payload: Record<string, unknown>) =>
    request<{ created: boolean; case: RagBenchmarkCase }>('/rag-benchmark-cases/from-trace/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  createBenchmarkCaseFromEvalCase: (payload: Record<string, unknown>) =>
    request<{ created: boolean; case: RagBenchmarkCase }>('/rag-benchmark-cases/from-eval-case/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
