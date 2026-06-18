import { buildQuery, request } from './client'
import type { QueryParams, RagAgentAction, RagAgentResult, RagExperimentPlan } from '../types/api'

export const agentApi = {
  runRagopsAgent: (payload: Record<string, unknown>) =>
    request<RagAgentResult>('/ragops-agent/run/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getRagopsAgentState: (params: QueryParams) =>
    request<RagAgentResult>(`/ragops-agent/state/${buildQuery(params)}`),
  resumeRagopsAgent: (payload: Record<string, unknown>) =>
    request<RagAgentResult>('/ragops-agent/resume/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listAgentActions: (params: QueryParams = {}) => request<RagAgentAction[]>(`/rag-agent-actions/${buildQuery(params)}`),
  confirmAgentAction: (id: number) =>
    request<RagAgentAction & { agent_result?: RagAgentResult }>(`/rag-agent-actions/${id}/confirm/`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  rejectAgentAction: (id: number, reason = '') =>
    request<RagAgentAction & { agent_result?: RagAgentResult }>(`/rag-agent-actions/${id}/reject/`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  listExperimentPlans: (params: QueryParams = {}) => request<RagExperimentPlan[]>(`/rag-experiment-plans/${buildQuery(params)}`),
  getExperimentPlan: (id: number) => request<RagExperimentPlan>(`/rag-experiment-plans/${id}/`),
}
