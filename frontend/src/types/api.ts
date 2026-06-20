export type AnyRecord = Record<string, any>

export interface User {
  id: number
  username: string
}

export interface AuthTokens {
  access: string
  refresh: string
}

export interface KnowledgeBase {
  id: number
  name: string
  description?: string
}

export interface DocumentRecord {
  id: number
  kb: number
  filename: string
  status?: string
  chunk_count?: number
  chunk_method?: string
  error_message?: string
}

export interface ChunkRecord {
  id?: number
  index: number
  content: string
  token_count?: number
  metadata?: AnyRecord
}

export interface ChatSession {
  id: number
  kb: number
  title?: string
  display_title?: string
  message_count?: number
}

export interface ChatMessage {
  id: number | string
  role: 'user' | 'assistant' | string
  content: string
  sources?: SourceRecord[]
  feedback?: UserFeedback
  trace?: RagTrace
  created_at?: string
}

export interface SourceRecord {
  citation_id?: number
  rank?: number
  chunk_id?: number
  document?: string
  score?: number
  engine?: string
  content?: string
  metadata?: AnyRecord
}

export interface RagTrace {
  id: number
  question?: string
  rewritten_query?: string
  query_intent?: string
  route_decision?: string
  route_reason?: string
  retrieval_mode?: string
  vector_results?: unknown[]
  bm25_results?: unknown[]
  hybrid_results?: unknown[]
  rerank_results?: unknown[]
  compression_results?: unknown[]
  compression_stats?: AnyRecord
  original_context?: string
  compressed_context?: string
  final_prompt?: string
  settings?: AnyRecord
  message_content?: string
  created_at?: string
}

export interface RagEvalRun {
  id: number
  kb: number
  status: 'running' | 'completed' | 'failed' | string
  metrics?: string[]
  mean_scores?: Record<string, number>
  retrieval_metrics?: AnyRecord
  case_count?: number
  case_results?: RagEvalCaseResult[]
  baseline_run?: number | null
  param_signature?: string
  error_message?: string
  settings?: AnyRecord
  created_at?: string
}

export interface RagEvalCaseResult {
  id: number
  case_id: string
  question?: string
  scores?: Record<string, number>
  diagnostics?: AnyRecord
}

export interface RagBenchmarkCase {
  id: number
  kb: number
  case_id: string
  question: string
  reference?: string
  suite?: string
  enabled?: boolean
  source?: string
  tags?: string[]
}

export interface RagAgentResult {
  status?: 'interrupted' | 'completed' | 'running' | string
  awaiting_human?: boolean
  answer?: string
  plan?: Array<{ step?: string; reason?: string } | string>
  tool_calls?: AnyRecord[]
  tool_results?: AnyRecord[]
  action_cards?: AgentActionCard[]
  diagnosis?: AnyRecord
  experiment_plan?: RagExperimentPlan | null
  workflow_intent?: string
  thread_id?: string
  thread_business_key?: string
  execution_results?: AnyRecord[]
}

export interface AgentActionCard {
  id: number | string
  action_id?: number
  action_type?: string
  type?: string
  action_uid?: string
  status?: string
  title?: string
  description?: string
  confirm_label?: string
  source?: string
  payload?: AnyRecord
  result?: AnyRecord
  failure_signals?: AnyRecord[]
  created_case_id?: string
  error_message?: string
  created_at?: string
}

export interface RagAgentAction {
  id: number
  action_type?: string
  action_uid?: string
  status?: string
  source?: string
  title?: string
  description?: string
  confirm_label?: string
  payload?: AnyRecord
  result?: AnyRecord
  created_case_id?: string
  error_message?: string
  created_at?: string
}

export interface RagExperimentPlan {
  id: number
  status?: string
  goal?: string
  baseline_run?: number
  baseline_param_signature?: string
  failure_cases?: AnyRecord[]
  failure_summary?: AnyRecord
  recommendation?: { winner_name?: string; reason?: string } & AnyRecord
  winner_variant?: number | null
  variants?: AnyRecord[]
}

export interface UserFeedback {
  id?: number
  rating: 'helpful' | 'not_helpful' | string
  reason?: string
  comment?: string
}

export interface ModelUsageSummary {
  totals?: {
    call_count?: number
    total_tokens?: number
    total_cost?: number
  }
  by_model?: AnyRecord[]
}

export interface RagOptions {
  query_rewrite_strategy?: string
  top_k?: number
  bm25_top_k?: number
  rrf_k?: number
  rerank_top_n?: number
  compression_strategy?: string
  compression_enabled?: boolean
  suite?: string
  baseline_run?: number
}

export type QueryParams = Record<string, string | number | boolean | undefined | null>

export interface StreamHandlers {
  signal?: AbortSignal
  onSources?: (sources: SourceRecord[]) => void
  onTrace?: (trace: RagTrace) => void
  onDelta?: (delta: string) => void
  onDone?: (message: ChatMessage) => void
  onError?: (data: { detail?: string }) => void
}
