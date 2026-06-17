import { buildQuery, request } from './client'

export const agentApi = {
  runRagopsAgent: (payload) =>
    request('/ragops-agent/run/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listAgentActions: (params = {}) => request(`/rag-agent-actions/${buildQuery(params)}`),
  confirmAgentAction: (id) =>
    request(`/rag-agent-actions/${id}/confirm/`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  rejectAgentAction: (id, reason = '') =>
    request(`/rag-agent-actions/${id}/reject/`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  listExperimentPlans: (params = {}) => request(`/rag-experiment-plans/${buildQuery(params)}`),
  getExperimentPlan: (id) => request(`/rag-experiment-plans/${id}/`),
}
