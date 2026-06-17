import { buildQuery, request } from './client'

export const benchmarkApi = {
  listBenchmarkCases: (params = {}) => request(`/rag-benchmark-cases/${buildQuery(params)}`),
  createBenchmarkCase: (payload) =>
    request('/rag-benchmark-cases/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateBenchmarkCase: (id, payload) =>
    request(`/rag-benchmark-cases/${id}/`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteBenchmarkCase: (id) =>
    request(`/rag-benchmark-cases/${id}/`, {
      method: 'DELETE',
    }),
  importDefaultBenchmarkCases: (kb) =>
    request('/rag-benchmark-cases/import-defaults/', {
      method: 'POST',
      body: JSON.stringify({ kb }),
    }),
  createBenchmarkCaseFromTrace: (payload) =>
    request('/rag-benchmark-cases/from-trace/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  createBenchmarkCaseFromEvalCase: (payload) =>
    request('/rag-benchmark-cases/from-eval-case/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
