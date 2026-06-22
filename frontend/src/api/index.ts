import { agentApi } from './agent'
import { authApi } from './auth'
import { benchmarkApi } from './benchmarks'
import { chatApi } from './chat'
import { costApi } from './costs'
import { documentApi } from './documents'
import { evaluationApi } from './evaluations'
import { feedbackApi } from './feedback'
import { operationsApi } from './operations'
import { permissionApi } from './permissions'
import { knowledgeBaseApi } from './knowledgeBases'
import { traceApi } from './traces'
import { workspaceApi } from './workspace'

export const api = {
  ...authApi,
  ...knowledgeBaseApi,
  ...documentApi,
  ...chatApi,
  ...traceApi,
  ...benchmarkApi,
  ...feedbackApi,
  ...evaluationApi,
  ...costApi,
  ...agentApi,
  ...workspaceApi,
  ...operationsApi,
  ...permissionApi,
}

export type ApiClient = typeof api
