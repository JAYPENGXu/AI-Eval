import type { Ref } from 'vue'
import type {
  KnowledgeBase,
  RagBenchmarkCase,
  RagOptions,
} from '../types/api'

export interface BusyState {
  preview: boolean
  index: boolean
  upload: boolean
  reset: boolean
  eval: boolean
  evalLoad: boolean
  evalDetail: number | string
  datasetImport: boolean
  datasetRefresh: boolean
  datasetCreate: boolean
  datasetAction: number | string
  agent: boolean
  agentAction: number | string
  feedback: number | string
}

export interface UseEvalRunsOptions {
  selectedKb: Ref<KnowledgeBase | null>
  busy: BusyState
  ragOptions: RagOptions
  notice: Ref<string>
  actionError: Ref<string>
  runAction: (fn: () => Promise<void>) => Promise<void>
  benchmarkCases: Ref<RagBenchmarkCase[]>
}
