<template>
  <main>
    <AuthManager :bootstrap="bootstrap" v-slot="{ user, logout }">
    <el-container class="shell">
      <AppSidebar
        :username="user?.username"
        :kbs="kbs"
        :documents="filteredDocuments"
        :selected-kb="selectedKb"
        :selected-document="selectedDocument"
        :kb-form="kbForm"
        :busy="busy"
        @create-kb="createKb"
        @select-kb="selectKb"
        @select-document="selectDocument"
        @upload="upload"
        @reset-workspace="resetWorkspace"
        @logout="logout"
      />

      <el-main class="workspace">
        <header>
          <div>
            <h1>RAGOps 工作台</h1>
            <p>从切片、检索到评测与修复，追踪每一次知识库回答的效果。</p>
          </div>
          <div class="status">{{ selectedKb?.name || '未选择知识库' }}</div>
        </header>

        <div
          ref="splitterContainer"
          class="grid resizable-grid"
          :class="{ resizing: isResizing }"
          :style="{ '--lab-width': `${labWidthPercent}%` }"
        >
          <section class="card lab">
            <WorkbenchTabs
              v-model:active-tab="activeWorkbenchTab"
              :tabs="workbenchTabs"
              :selected-kb="selectedKb"
              :document-count="filteredDocuments.length"
              :chunk-count="stats.chunk_count || selectedDocument?.chunk_count || 0"
              :eval-run-count="evalRuns.length"
              :model-call-count="modelUsage?.totals?.call_count || 0"
            />
            <ChunkLabPanel
              v-model:collapse-value="activeCollapseSections.chunkLab"
              :active="activeWorkbenchTab === 'debug'"
              :chunk-form="chunkForm"
              :chunk-methods="chunkMethods"
              :selected-document="selectedDocument"
              :busy="busy"
              :notice="notice"
              :action-error="actionError"
              :stats="stats"
              :chunks="chunks"
              @preview="preview"
              @index-document="indexDoc"
            />

            <RagDebugPanel
              v-model:collapse-value="activeCollapseSections.ragDebug"
              :active="activeWorkbenchTab === 'debug'"
              :latest-trace="latestTrace"
              :rag-options="ragOptions"
              :query-rewrite-strategies="queryRewriteStrategies"
              :compression-strategies="compressionStrategies"
              :current-rewrite-description="currentRewriteDescription"
              :current-compression-description="currentCompressionDescription"
              :format-score="formatScore"
              :format-percent="formatPercent"
            />



            <AgentPanel
              v-model:collapse-value="activeCollapseSections.agent"
              :active="activeWorkbenchTab === 'agent'"
              :selected-kb="selectedKb"
              :agent-form="agentForm"
              :trace-history="traceHistory"
              :eval-runs="evalRuns"
              :busy="busy"
              :agent-result="agentResult"
              :agent-actions="agentActions"
              :active-experiment-plan="activeExperimentPlan"
              :agent-thread-id="currentAgentThreadId"
              :compact-text="compactText"
              :format-date="formatDate"
              :has-diagnosis="hasDiagnosis"
              :diagnosis-severity-class="diagnosisSeverityClass"
              :diagnosis-severity-text="diagnosisSeverityText"
              :action-failure-signals="actionFailureSignals"
              :action-card-meta="actionCardMeta"
              :is-agent-card-done="isAgentCardDone"
              :is-agent-card-running="isAgentCardRunning"
              :display-action-title="displayActionTitle"
              :action-status-text="actionStatusText"
              @run-agent="runAgent"
              @confirm-action="confirmAgentAction"
              @refresh-experiment-plan="refreshExperimentPlan"
              @new-agent-thread="resetAgentThread"
            />

            <CostsPanel
              v-model:collapse-value="activeCollapseSections.costs"
              :active="activeWorkbenchTab === 'costs'"
              :selected-kb="selectedKb"
              :model-usage="modelUsage"
              :format-cost="formatCost"
              :format-cost-share="formatCostShare"
              :format-date="formatDate"
              :compact-text="compactText"
              @refresh="loadModelUsage"
            />

            <HistoryPanel
              v-model:collapse-value="activeCollapseSections.history"
              v-model:trace-search="traceSearch"
              :active="activeWorkbenchTab === 'history'"
              :selected-kb="selectedKb"
              :trace-history="traceHistory"
              :latest-trace="latestTrace"
              :selected-trace-ids="selectedTraceIds"
              :selected-traces="selectedTraces"
              :trace-comparison="traceComparison"
              :compact-text="compactText"
              :format-date="formatDate"
              :format-percent="formatPercent"
              :format-score="formatScore"
              @load-history="loadTraceHistory"
              @clear-compare="clearTraceCompare"
              @open-trace="openTrace"
              @toggle-compare="toggleTraceCompare"
              @create-case-from-trace="createCaseFromTrace"
            />

            <DatasetsPanel
              v-model:collapse-value="activeCollapseSections.datasets"
              v-model:selected-suite="selectedDatasetSuite"
              :active="activeWorkbenchTab === 'datasets'"
              :selected-kb="selectedKb"
              :eval-suites="evalSuites"
              :case-sources="caseSources"
              :benchmark-form="benchmarkForm"
              :benchmark-cases="benchmarkCases"
              :busy="busy"
              @refresh="loadBenchmarkCases"
              @import-defaults="importDefaultBenchmarkCases"
              @create-case="createBenchmarkCase"
              @toggle-case="toggleBenchmarkCase"
              @delete-case="deleteBenchmarkCase"
            />

            <EvaluationPanel
              v-model:collapse-value="activeCollapseSections.evaluation"
              v-model:selected-suite="selectedEvalSuite"
              :active="activeWorkbenchTab === 'evaluation'"
              :selected-kb="selectedKb"
              :eval-suites="evalSuites"
              :is-eval-running="isEvalRunning"
              :eval-runs="evalRuns"
              :selected-eval-run="selectedEvalRun"
              :selected-eval-run-ids="selectedEvalRunIds"
              :selected-eval-runs="selectedEvalRuns"
              :selected-baseline-eval-run="selectedBaselineEvalRun"
              :eval-run-comparison="evalRunComparison"
              :failure-analysis="failureAnalysis"
              :rag-options="ragOptions"
              :busy="busy"
              :format-date="formatDate"
              :metric-label="metricLabel"
              :format-eval-score="formatEvalScore"
              :score-delta-class="scoreDeltaClass"
              :format-signed-score="formatSignedScore"
              :retrieval-metric-rows="retrievalMetricRows"
              :diagnostic-stages="diagnosticStages"
              :final-diagnostic="finalDiagnostic"
              :format-diagnostic-percent="formatDiagnosticPercent"
              :format-terms="formatTerms"
              :compact-text="compactText"
              @run-eval="runEval"
              @load-runs="loadEvalRuns"
              @open-run="openEvalRun"
              @toggle-compare="toggleEvalRunCompare"
              @set-baseline="setBaselineEvalRun"
              @compare-baseline="compareEvalRunWithBaseline"
              @scroll-to-case="scrollToEvalCase"
            />
          </section>

          <div
            class="splitter"
            role="separator"
            aria-orientation="vertical"
            tabindex="0"
            @pointerdown="startResize"
            @keydown.left.prevent="nudgeSplitter(-4)"
            @keydown.right.prevent="nudgeSplitter(4)"
          ></div>

          <RagChatPanel
            v-model:question="question"
            :selected-kb="selectedKb"
            :session="session"
            :chat-sessions="chatSessions"
            :messages="messages"
            :loading="loading"
            :busy="busy"
            :feedback-drafts="feedbackDrafts"
            :feedback-reasons="feedbackReasons"
            :chat-session-label="chatSessionLabel"
            :format-date="formatDate"
            :render-message-parts="renderMessageParts"
            :feedback-status-text="feedbackStatusText"
            :is-source-panel-open="isSourcePanelOpen"
            :is-source-highlighted="isSourceHighlighted"
            :source-citation-number="sourceCitationNumber"
            @new-session="newSession"
            @ask="ask"
            @select-session="selectChatSession"
            @delete-session="deleteChatSession"
            @highlight-citation="highlightCitation"
            @submit-feedback="submitFeedback"
            @open-negative-feedback="openNegativeFeedback"
            @set-source-panel-open="setSourcePanelOpen"
          />
        </div>
      </el-main>
    </el-container>
    </AuthManager>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from './api'
import { useAuthStore } from './stores/auth'
import { getErrorMessage, shouldIgnoreRequestError } from './composables/polling'
import AuthManager from './components/AuthManager.vue'
import RagChatPanel from './components/Chat/RagChatPanel.vue'
import AppSidebar from './components/Sidebar/AppSidebar.vue'
import AgentPanel from './components/Workbench/AgentPanel.vue'
import ChunkLabPanel from './components/Workbench/ChunkLabPanel.vue'
import CostsPanel from './components/Workbench/CostsPanel.vue'
import DatasetsPanel from './components/Workbench/DatasetsPanel.vue'
import EvaluationPanel from './components/Workbench/EvaluationPanel.vue'
import HistoryPanel from './components/Workbench/HistoryPanel.vue'
import WorkbenchTabs from './components/Workbench/WorkbenchTabs.vue'
import RagDebugPanel from './components/Workbench/RagDebugPanel.vue'
import {
  compactText,
  compareChunkOrder,
  diagnosticStages,
  diffSettings,
  finalDiagnostic,
  formatDate,
  formatDiagnosticPercent,
  formatEvalScore,
  formatSignedScore,
  formatTerms,
  metricLabel,
  retrievalMetricRows,
  scoreDeltaClass,
} from './composables/helpers'
import { useEvalRuns } from './composables/useEvalRuns'
import { useChat } from './composables/useChat'
import { useAgent } from './composables/useAgent'

const authStore = useAuthStore()

const kbs = ref([])
const documents = ref([])
const chunkMethods = ref([])
const selectedKb = ref(null)
const selectedDocument = ref(null)
const chunks = ref([])
const stats = reactive({})
const notice = ref('')
const actionError = ref('')
const latestTrace = ref(null)
const traceHistory = ref([])
const selectedTraceIds = ref([])
const traceSearch = ref('')
const benchmarkCases = ref([])
const selectedDatasetSuite = ref('')
const activeWorkbenchTab = ref('debug')
const activeCollapseSections = reactive({
  chunkLab: ['chunk-lab'],
  ragDebug: ['rag-debug'],
  agent: ['agent'],
  costs: ['costs'],
  history: ['history'],
  datasets: ['datasets'],
  evaluation: ['evaluation'],
})
const modelUsage = ref(null)
const splitterContainer = ref(null)
const labWidthPercent = ref(Number(localStorage.getItem('labWidthPercent')) || 62)
const isResizing = ref(false)
const busy = reactive({
  preview: false,
  index: false,
  upload: false,
  reset: false,
  eval: false,
  evalLoad: false,
  evalDetail: '',
  datasetImport: false,
  datasetRefresh: false,
  datasetCreate: false,
  datasetAction: '',
  agent: false,
  agentAction: '',
  feedback: '',
})
const feedbackReasons = [
  { value: 'missed_question', label: '没答到问题' },
  { value: 'wrong_citation', label: '引用不对' },
  { value: 'insufficient_context', label: '资料不足' },
  { value: 'off_topic', label: '答非所问' },
  { value: 'factual_error', label: '事实错误' },
  { value: 'too_verbose', label: '太啰嗦' },
  { value: 'other', label: '其他' },
]

const workbenchTabs = [
  { key: 'debug', label: '调试', caption: '切片与检索' },
  { key: 'evaluation', label: '评测', caption: '评测报告' },
  { key: 'datasets', label: '评测集', caption: '基准与回归' },
  { key: 'history', label: '历史', caption: 'Trace 复盘' },
  { key: 'agent', label: 'Agent', caption: 'RAGOps 诊断' },
  { key: 'costs', label: '成本', caption: '模型与 Token' },
]
const evalSuites = [
  { value: 'smoke', label: '冒烟集' },
  { value: 'benchmark', label: '基准集' },
  { value: 'regression', label: '回归集' },
  { value: 'release', label: '发布集' },
]
const caseSources = [
  { value: 'expert', label: '专家维护' },
  { value: 'trace', label: 'Trace 沉淀' },
  { value: 'eval_failure', label: '评测失败沉淀' },
  { value: 'user_feedback', label: '用户反馈沉淀' },
  { value: 'default_json', label: '默认样例' },
]
const kbForm = reactive({ name: '默认知识库', description: '' })
const chunkForm = reactive({
  chunk_method: 'sentence',
  options: { chunk_size: 800, chunk_overlap: 100, window_size: 1, semantic_threshold: 0.72 },
})
const ragOptions = reactive({
  query_rewrite_strategy: 'rule',
  top_k: 5,
  bm25_top_k: 5,
  rrf_k: 60,
  rerank_top_n: 5,
  compression_strategy: 'structure_aware',
})
const agentForm = reactive({
  message: '请执行端到端 RAG 修复工作流：收集证据、定位失败阶段、生成优化方案；如果需要创建回归样例或运行参数实验，请先生成待确认动作。',
  trace_id: '',
  eval_run_id: '',
  compare_eval_run_id: '',
  thread_id: '',
})

const benchmarkForm = reactive({
  case_id: '',
  case_type: 'expert',
  question: '',
  reference: '',
  tagsText: '',
  expectedTermsText: '',
  targetChunkIdsText: '',
  suite: 'benchmark',
  source: 'expert',
  notes: '',
  difficulty: 'medium',
  enabled: true,
  routerIntent: 'internal_knowledge',
  rewriteContainsText: '',
  answerContainsText: '',
  answerNotContainsText: '',
  citationRequired: false,
  vectorHit: false,
  bm25Hit: false,
  hybridHit: false,
  rerankKeep: false,
  compressionKeepTermsText: '',
  rubricText: '{\n  "dimensions": []\n}',
  deterministicMinPassRate: 1,
  minCorrectnessScore: 0.7,
  minCitationScore: 0.6,
  maxHallucinationRisk: 0.3,
  maxTotalTokens: 0,
  maxLatencyMs: 0,
})

watch(activeWorkbenchTab, () => {
  notice.value = ''
  actionError.value = ''
})
const queryRewriteStrategies = [
  { value: 'rule', label: 'Rule Rewrite', description: '\u89c4\u5219\u6539\u5199\uff0c\u4fbf\u5b9c\u3001\u7a33\u5b9a\u3001\u53ef\u89e3\u91ca\u3002' },
  { value: 'llm', label: 'LLM Rewrite', description: '\u8c03\u7528\u4fbf\u5b9c\u6a21\u578b\u505a\u8bed\u4e49\u6539\u5199\uff0c\u66f4\u7075\u6d3b\u4f46\u66f4\u6162\u3002' },
  { value: 'none', label: 'No Rewrite', description: '\u4e0d\u6539\u5199\uff0c\u76f4\u63a5\u4f7f\u7528\u539f\u59cb\u95ee\u9898\u68c0\u7d22\u3002' },
]
const compressionStrategies = [
  { value: 'llm', label: 'LLM Compression', description: '\u8c03\u7528\u4fbf\u5b9c\u6a21\u578b\u505a\u8bed\u4e49\u538b\u7f29\uff0c\u66f4\u667a\u80fd\u4f46\u66f4\u6162\u4e14\u4f1a\u4ea7\u751f\u989d\u5916\u8c03\u7528\u6210\u672c\u3002' },
  { value: 'structure_aware', label: 'Structure Aware', description: '保留命中句子，并保护标题、列表等结构化上下文。' },
  { value: 'sentence_filter', label: 'Sentence Filter', description: '只按问题关键词相关性保留句子，压缩更激进。' },
  { value: 'none', label: 'No Compression', description: '不压缩，直接把 Rerank 后的 chunk 作为上下文。' },
]

async function runAction(fn) {
  actionError.value = ''
  notice.value = ''
  try {
    await fn()
  } catch (err) {
    if (shouldIgnoreRequestError(err)) return
    actionError.value = getErrorMessage(err)
  } finally {
    busy.preview = false
    busy.index = false
    busy.upload = false
    busy.reset = false
    busy.eval = false
  }
}

async function loadBenchmarkCases() {
  if (!selectedKb.value) {
    benchmarkCases.value = []
    return
  }
  busy.datasetRefresh = true
  try {
    benchmarkCases.value = await api.listBenchmarkCases({ kb: selectedKb.value.id, suite: selectedDatasetSuite.value })
  } finally {
    busy.datasetRefresh = false
  }
}

const {
  evalRuns,
  selectedEvalRun,
  selectedEvalRunIds,
  selectedBaselineEvalRunId,
  selectedEvalSuite,
  pollingEvalRunIds,
  isEvalRunning,
  selectedEvalRuns,
  selectedBaselineEvalRun,
  failureAnalysis,
  evalRunComparison,
  resetEvalState,
  loadEvalRuns,
  openEvalRun,
  setBaselineEvalRun,
  compareEvalRunWithBaseline,
  toggleEvalRunCompare,
  runEval,
  scrollToEvalCase,
} = useEvalRuns({
  selectedKb,
  busy,
  ragOptions,
  notice,
  actionError,
  runAction,
  benchmarkCases,
})

const {
  agentResult,
  agentActions,
  currentAgentThreadId,
  activeExperimentPlan,
  resetAgentState,
  resetAgentThread,
  runAgent,
  loadAgentActions,
  confirmAgentAction,
  refreshExperimentPlan,
  hasDiagnosis,
  diagnosisSeverityText,
  diagnosisSeverityClass,
  displayActionTitle,
  isAgentCardDone,
  isAgentCardRunning,
  actionStatusText,
  actionFailureSignals,
  actionCardMeta,
} = useAgent({
  selectedKb,
  agentForm,
  busy,
  notice,
  actionError,
  runAction,
  loadBenchmarkCases,
  loadEvalRuns,
  selectedDatasetSuite,
})

async function loadModelUsage() {
  if (!selectedKb.value) {
    modelUsage.value = null
    resetAgentState()
    return
  }
  modelUsage.value = await api.getModelUsageSummary({ kb: selectedKb.value.id })
}

async function loadTraceHistory() {
  if (!selectedKb.value) {
    traceHistory.value = []
    selectedTraceIds.value = []
    resetEvalState()
    benchmarkCases.value = []
    modelUsage.value = null
    return
  }
  const traces = await api.listTraces({ kb: selectedKb.value.id, question: traceSearch.value })
  traceHistory.value = await Promise.all(
    traces.map(async (trace) => {
      const existing = traceHistory.value.find((item) => item.id === trace.id)
      return existing && existing.vector_results ? existing : trace
    })
  )
  selectedTraceIds.value = selectedTraceIds.value.filter((id) => traceHistory.value.some((trace) => trace.id === id))
}

const {
  messages,
  session,
  chatSessions,
  question,
  loading,
  feedbackDrafts,
  resetChatState,
  openNegativeFeedback,
  submitFeedback,
  feedbackStatusText,
  renderMessageParts,
  sourceCitationNumber,
  highlightCitation,
  isSourcePanelOpen,
  setSourcePanelOpen,
  isSourceHighlighted,
  loadChatSessions,
  selectChatSession,
  deleteChatSession,
  chatSessionLabel,
  newSession,
  ask,
} = useChat({
  selectedKb,
  ragOptions,
  latestTrace,
  notice,
  actionError,
  busy,
  feedbackReasons,
  runAction,
  loadTraceHistory,
  loadModelUsage,
  loadAgentActions,
})

const filteredDocuments = computed(() =>
  selectedKb.value ? documents.value.filter((doc) => doc.kb === selectedKb.value.id) : []
)

const selectedTraces = computed(() =>
  selectedTraceIds.value
    .map((id) => traceHistory.value.find((trace) => trace.id === id))
    .filter(Boolean)
)

const traceComparison = computed(() => {
  if (selectedTraces.value.length !== 2) return null
  const [left, right] = selectedTraces.value
  return {
    questionChanged: left.question !== right.question,
    vectorOrder: compareChunkOrder(left.vector_results, right.vector_results),
    bm25Order: compareChunkOrder(left.bm25_results, right.bm25_results),
    hybridOrder: compareChunkOrder(left.hybrid_results, right.hybrid_results),
    rerankOrder: compareChunkOrder(left.rerank_results, right.rerank_results),
    compressionTokens: {
      left: left.compression_stats?.compressed_tokens || 0,
      right: right.compression_stats?.compressed_tokens || 0,
      delta: (right.compression_stats?.compressed_tokens || 0) - (left.compression_stats?.compressed_tokens || 0),
    },
    savingRatio: {
      left: left.compression_stats?.saving_ratio || 0,
      right: right.compression_stats?.saving_ratio || 0,
      delta: (right.compression_stats?.saving_ratio || 0) - (left.compression_stats?.saving_ratio || 0),
    },
    contextLength: {
      left: left.compressed_context?.length || 0,
      right: right.compressed_context?.length || 0,
      delta: (right.compressed_context?.length || 0) - (left.compressed_context?.length || 0),
    },
    answerLength: {
      left: left.message_content?.length || 0,
      right: right.message_content?.length || 0,
      delta: (right.message_content?.length || 0) - (left.message_content?.length || 0),
    },
    settingsChanged: diffSettings(left.settings || {}, right.settings || {}),
  }
})

const currentRewriteDescription = computed(() => {
  return queryRewriteStrategies.find((item) => item.value === ragOptions.query_rewrite_strategy)?.description || ''
})

const currentCompressionDescription = computed(() => {
  return compressionStrategies.find((item) => item.value === ragOptions.compression_strategy)?.description || ''
})

function setLabWidthFromClientX(clientX) {
  const container = splitterContainer.value
  if (!container) return
  const rect = container.getBoundingClientRect()
  const minLab = 360
  const minChat = 360
  const splitterWidth = 10
  const availableWidth = rect.width - splitterWidth
  const rawLabWidth = clientX - rect.left
  const labWidth = Math.min(Math.max(rawLabWidth, minLab), availableWidth - minChat)
  const nextPercent = Math.round((labWidth / availableWidth) * 100)
  labWidthPercent.value = Number.isFinite(nextPercent) ? nextPercent : 62
  localStorage.setItem('labWidthPercent', String(labWidthPercent.value))
}

function startResize(event) {
  isResizing.value = true
  event.currentTarget.setPointerCapture?.(event.pointerId)
  setLabWidthFromClientX(event.clientX)
  window.addEventListener('pointermove', resize)
  window.addEventListener('pointerup', stopResize)
}

function resize(event) {
  if (!isResizing.value) return
  setLabWidthFromClientX(event.clientX)
}

function stopResize() {
  isResizing.value = false
  window.removeEventListener('pointermove', resize)
  window.removeEventListener('pointerup', stopResize)
}

function nudgeSplitter(delta) {
  const next = Math.min(Math.max(labWidthPercent.value + delta, 35), 72)
  labWidthPercent.value = next
  localStorage.setItem('labWidthPercent', String(next))
}

function formatScore(score) {
  const value = Number(score)
  return Number.isFinite(value) ? value.toFixed(4) : '-'
}

function formatPercent(value) {
  const number = Number(value)
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : '-'
}

function formatCost(value) {
  const amount = Number(value || 0)
  if (!amount) return '$0.0000'
  return `$${amount.toFixed(amount < 0.01 ? 6 : 4)}`
}

function formatCostShare(value, total) {
  const denominator = Number(total || 0)
  if (!denominator) return '-'
  return `${Math.round((Number(value || 0) / denominator) * 100)}%`
}

function parseLooseList(value) {
  return String(value || '')
    .replace(/\n/g, ',')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function parseJsonField(value, fallback = {}) {
  const raw = String(value || '').trim()
  if (!raw) return fallback
  return JSON.parse(raw)
}

function buildDeterministicChecks() {
  const checks = {}
  if (benchmarkForm.routerIntent) checks.router_intent = benchmarkForm.routerIntent
  const rewriteContains = parseLooseList(benchmarkForm.rewriteContainsText)
  if (rewriteContains.length) checks.rewrite_contains = rewriteContains
  const answerContains = parseLooseList(benchmarkForm.answerContainsText)
  if (answerContains.length) checks.answer_contains = answerContains
  const answerNotContains = parseLooseList(benchmarkForm.answerNotContainsText)
  if (answerNotContains.length) checks.answer_not_contains = answerNotContains
  if (benchmarkForm.citationRequired) checks.citation_required = true
  if (benchmarkForm.vectorHit) checks.vector_hit = true
  if (benchmarkForm.bm25Hit) checks.bm25_hit = true
  if (benchmarkForm.hybridHit) checks.hybrid_hit = true
  if (benchmarkForm.rerankKeep) checks.rerank_keep = true
  const compressionTerms = parseLooseList(benchmarkForm.compressionKeepTermsText)
  if (compressionTerms.length) checks.compression_keep_terms = compressionTerms
  if (benchmarkForm.maxTotalTokens > 0) checks.max_total_tokens = benchmarkForm.maxTotalTokens
  if (benchmarkForm.maxLatencyMs > 0) checks.max_latency_ms = benchmarkForm.maxLatencyMs
  return checks
}

function buildThresholds() {
  const thresholds = {
    deterministic_min_pass_rate: benchmarkForm.deterministicMinPassRate,
    min_correctness_score: benchmarkForm.minCorrectnessScore,
    min_citation_score: benchmarkForm.minCitationScore,
    max_hallucination_risk: benchmarkForm.maxHallucinationRisk,
  }
  if (benchmarkForm.maxTotalTokens > 0) thresholds.max_total_tokens = benchmarkForm.maxTotalTokens
  if (benchmarkForm.maxLatencyMs > 0) thresholds.max_latency_ms = benchmarkForm.maxLatencyMs
  return thresholds
}

function resetBenchmarkForm() {
  benchmarkForm.case_id = ''
  benchmarkForm.case_type = 'expert'
  benchmarkForm.question = ''
  benchmarkForm.reference = ''
  benchmarkForm.tagsText = ''
  benchmarkForm.expectedTermsText = ''
  benchmarkForm.targetChunkIdsText = ''
  benchmarkForm.suite = selectedDatasetSuite.value || 'benchmark'
  benchmarkForm.source = 'expert'
  benchmarkForm.notes = ''
  benchmarkForm.difficulty = 'medium'
  benchmarkForm.enabled = true
  benchmarkForm.routerIntent = 'internal_knowledge'
  benchmarkForm.rewriteContainsText = ''
  benchmarkForm.answerContainsText = ''
  benchmarkForm.answerNotContainsText = ''
  benchmarkForm.citationRequired = false
  benchmarkForm.vectorHit = false
  benchmarkForm.bm25Hit = false
  benchmarkForm.hybridHit = false
  benchmarkForm.rerankKeep = false
  benchmarkForm.compressionKeepTermsText = ''
  benchmarkForm.rubricText = '{\n  "dimensions": []\n}'
  benchmarkForm.deterministicMinPassRate = 1
  benchmarkForm.minCorrectnessScore = 0.7
  benchmarkForm.minCitationScore = 0.6
  benchmarkForm.maxHallucinationRisk = 0.3
  benchmarkForm.maxTotalTokens = 0
  benchmarkForm.maxLatencyMs = 0
}

async function createBenchmarkCase() {
  if (!selectedKb.value) return
  const missingFields = [
    ['case_id', '用例编号'],
    ['question', '评测问题'],
    ['reference', '标准答案'],
  ].filter(([key]) => !String(benchmarkForm[key] || '').trim())
  if (missingFields.length) {
    actionError.value = `请先填写${missingFields.map(([, label]) => label).join('、')}。`
    notice.value = ''
    return
  }
  busy.datasetCreate = true
  try {
    await runAction(async () => {
    const rubric = parseJsonField(benchmarkForm.rubricText, {})
    const created = await api.createBenchmarkCase({
      kb: selectedKb.value.id,
      case_id: benchmarkForm.case_id.trim(),
      case_type: benchmarkForm.case_type,
      question: benchmarkForm.question.trim(),
      reference: benchmarkForm.reference.trim(),
      tags: benchmarkForm.tagsText,
      expected_terms: benchmarkForm.expectedTermsText,
      target_chunk_ids: benchmarkForm.targetChunkIdsText,
      suite: benchmarkForm.suite,
      deterministic_checks: buildDeterministicChecks(),
      rubric,
      thresholds: buildThresholds(),
      source: benchmarkForm.source,
      notes: benchmarkForm.notes,
      difficulty: benchmarkForm.difficulty,
      enabled: benchmarkForm.enabled,
    })
    benchmarkCases.value = [...benchmarkCases.value, created].sort((left, right) => left.case_id.localeCompare(right.case_id))
    resetBenchmarkForm()
    notice.value = `已新增 Eval Case：${created.case_id}`
    })
  } finally {
    busy.datasetCreate = false
  }
}

async function createCaseFromTrace(trace) {
  if (!trace?.id) return
  await runAction(async () => {
    const result = await api.createBenchmarkCaseFromTrace({ trace: trace.id })
    selectedDatasetSuite.value = 'regression'
    activeWorkbenchTab.value = 'datasets'
    await loadBenchmarkCases()
    await loadModelUsage()
    notice.value = `${result.created ? 'Created' : 'Updated'} regression case: ${result.case.case_id}`
  })
}

async function createCaseFromEvalCase(item) {
  if (!item?.id) return
  await runAction(async () => {
    const result = await api.createBenchmarkCaseFromEvalCase({ eval_case: item.id })
    selectedDatasetSuite.value = 'regression'
    activeWorkbenchTab.value = 'datasets'
    await loadBenchmarkCases()
    notice.value = `${result.created ? 'Created' : 'Updated'} regression case: ${result.case.case_id}`
  })
}

async function importDefaultBenchmarkCases() {
  if (!selectedKb.value) return
  busy.datasetImport = true
  try {
    await runAction(async () => {
      const result = await api.importDefaultBenchmarkCases(selectedKb.value.id)
      benchmarkCases.value = result.cases
      notice.value = `已导入默认评测基准：新增 ${result.created} 条，更新 ${result.updated} 条`
    })
  } finally {
    busy.datasetImport = false
  }
}

async function toggleBenchmarkCase(item) {
  busy.datasetAction = item.id
  try {
    await runAction(async () => {
      const updated = await api.updateBenchmarkCase(item.id, { enabled: !item.enabled })
      benchmarkCases.value = benchmarkCases.value.map((caseItem) => (caseItem.id === updated.id ? updated : caseItem))
    })
  } finally {
    busy.datasetAction = ''
  }
}

async function deleteBenchmarkCase(item) {
  try {
    await ElMessageBox.confirm(
      `删除后该评测用例将不再参与后续评测。`,
      `确认删除评测基准 ${item.case_id}？`,
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }
  busy.datasetAction = `delete-${item.id}`
  try {
    await runAction(async () => {
      await api.deleteBenchmarkCase(item.id)
      benchmarkCases.value = benchmarkCases.value.filter((caseItem) => caseItem.id !== item.id)
    })
  } finally {
    busy.datasetAction = ''
  }
}

async function openTrace(trace) {
  const detail = trace.vector_results ? trace : await api.getTrace(trace.id)
  latestTrace.value = detail
  traceHistory.value = traceHistory.value.map((item) => (item.id === detail.id ? detail : item))
}

async function toggleTraceCompare(trace) {
  let ids = [...selectedTraceIds.value]
  if (ids.includes(trace.id)) {
    ids = ids.filter((id) => id !== trace.id)
  } else {
    ids = [...ids.slice(-1), trace.id]
    if (!trace.vector_results) await openTrace(trace)
  }
  selectedTraceIds.value = ids
  await Promise.all(
    ids.map(async (id) => {
      const traceItem = traceHistory.value.find((item) => item.id === id)
      if (traceItem && !traceItem.vector_results) await openTrace(traceItem)
    })
  )
}

function clearTraceCompare() {
  selectedTraceIds.value = []
}

async function resetWorkspace() {
  try {
    await ElMessageBox.confirm(
      '此操作会删除当前账号的所有知识库、文档、切片、会话和聊天记录。',
      '确认重置当前工作区？',
      {
        confirmButtonText: '继续',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    await ElMessageBox.confirm(
      '此操作会同时删除 Milvus 向量索引和已上传文件，且不可恢复。',
      '再次确认重置？',
      {
        confirmButtonText: '确认重置',
        cancelButtonText: '取消',
        type: 'error',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }

  await runAction(async () => {
    busy.reset = true
    const result = await api.resetWorkspace()
    kbs.value = []
    documents.value = []
    selectedKb.value = null
    selectedDocument.value = null
    chunks.value = []
    Object.keys(stats).forEach((key) => delete stats[key])
    resetChatState()
    latestTrace.value = null
    traceHistory.value = []
    selectedTraceIds.value = []
    resetEvalState()
    benchmarkCases.value = []
    modelUsage.value = null
    resetAgentState()
    notice.value = `已重置：知识库 ${result.deleted.knowledge_bases} 个，文档 ${result.deleted.documents} 个，切片 ${result.deleted.chunks} 个，会话 ${result.deleted.chat_sessions} 个`
    await loadKbs()
    documents.value = await api.listDocuments()
  })
  busy.reset = false
}

async function bootstrap() {
  authStore.setUser(await api.me())
  chunkMethods.value = await api.chunkMethods()
  await loadKbs()
  documents.value = await api.listDocuments()
  await loadTraceHistory()
  await loadEvalRuns()
  await loadBenchmarkCases()
  await loadAgentActions()
  await loadChatSessions({ restore: true })
}

async function loadKbs() {
  kbs.value = await api.listKbs()
  if (!selectedKb.value && kbs.value.length) selectedKb.value = kbs.value[0]
}

async function createKb() {
  await runAction(async () => {
    const kb = await api.createKb(kbForm)
    kbs.value.unshift(kb)
    selectedKb.value = kb
    notice.value = `已创建知识库：${kb.name}`
  })
}

function selectKb(kb) {
  selectedKb.value = kb
  selectedDocument.value = null
  chunks.value = []
  resetChatState()
  latestTrace.value = null
  selectedTraceIds.value = []
  resetEvalState()
  benchmarkCases.value = []
  resetAgentState()
  loadTraceHistory()
  loadEvalRuns()
  loadBenchmarkCases()
  loadModelUsage()
  loadAgentActions()
  loadChatSessions({ restore: true })
}

function selectDocument(doc) {
  selectedDocument.value = doc
  chunks.value = []
  Object.keys(stats).forEach((key) => delete stats[key])
}

async function upload(payload) {
  const file = payload?.raw || payload?.target?.files?.[0]
  if (!file || !selectedKb.value) return
  await runAction(async () => {
    busy.upload = true
    const doc = await api.uploadDocument(selectedKb.value.id, file)
    documents.value.unshift(doc)
    selectedDocument.value = doc
    notice.value = `已上传文档：${doc.filename}`
  })
  busy.upload = false
}

async function preview() {
  if (!selectedDocument.value) return
  await runAction(async () => {
    busy.preview = true
    const data = await api.previewChunks(selectedDocument.value.id, chunkForm)
    chunks.value = data.chunks
    Object.assign(stats, data.stats)
    notice.value = `已生成 ${data.stats.chunk_count} 个切片预览`
  })
  busy.preview = false
}

async function indexDoc() {
  if (!selectedDocument.value) return
  const documentId = selectedDocument.value.id
  await runAction(async () => {
    busy.index = true
    const result = await api.indexDocument(documentId, chunkForm)
    documents.value = await api.listDocuments()
    selectedDocument.value = documents.value.find((doc) => doc.id === documentId) || selectedDocument.value
    notice.value = `索引完成：${result.chunk_count} 个切片已入库`
    await preview()
  })
  busy.index = false
}

onBeforeUnmount(() => {
  stopResize()
})
</script>
