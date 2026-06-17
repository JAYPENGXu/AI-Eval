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
import { store } from './main'
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

const kbs = ref([])
const documents = ref([])
const chunkMethods = ref([])
const selectedKb = ref(null)
const selectedDocument = ref(null)
const chunks = ref([])
const stats = reactive({})
const messages = ref([])
const session = ref(null)
const chatSessions = ref([])
const question = ref('')
const loading = ref(false)
const notice = ref('')
const actionError = ref('')
const latestTrace = ref(null)
const traceHistory = ref([])
const selectedTraceIds = ref([])
const traceSearch = ref('')
const evalRuns = ref([])
const selectedEvalRun = ref(null)
const selectedEvalRunIds = ref([])
const selectedBaselineEvalRunId = ref(null)
const benchmarkCases = ref([])
const selectedDatasetSuite = ref('')
const selectedEvalSuite = ref('')
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
const agentResult = ref(null)
const agentActions = ref([])
const currentAgentThreadId = ref('')
const selectedAgentTask = ref('repair')
const activeExperimentPlan = ref(null)
const completedAgentActions = ref(new Set())
const pollingEvalRunIds = ref(new Set())
const splitterContainer = ref(null)
const labWidthPercent = ref(Number(localStorage.getItem('labWidthPercent')) || 62)
const isResizing = ref(false)
const highlightedSourceRefs = reactive({})
const openSourcePanels = reactive({})
const feedbackDrafts = reactive({})
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

function agentThreadBusinessKey() {
  const kbId = selectedKb.value?.id || 'none'
  return [
    `kb:${kbId}`,
    `trace:${agentForm.trace_id || 'none'}`,
    `eval:${agentForm.eval_run_id || 'none'}`,
    `compare:${agentForm.compare_eval_run_id || 'none'}`,
  ].join('|')
}

function agentThreadStorageKey() {
  return `aiassistant:ragops-agent-thread:${agentThreadBusinessKey()}`
}

function generateAgentThreadId() {
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `ragops:${agentThreadBusinessKey().replaceAll('|', ':')}:${random}`
}

function ensureAgentThreadId() {
  if (!selectedKb.value) return ''
  const key = agentThreadStorageKey()
  let threadId = localStorage.getItem(key)
  if (!threadId) {
    threadId = generateAgentThreadId()
    localStorage.setItem(key, threadId)
  }
  currentAgentThreadId.value = threadId
  agentForm.thread_id = threadId
  return threadId
}

function resetAgentThread() {
  if (!selectedKb.value) return
  localStorage.removeItem(agentThreadStorageKey())
  currentAgentThreadId.value = ''
  agentForm.thread_id = ensureAgentThreadId()
  agentResult.value = null
  activeExperimentPlan.value = null
  notice.value = '已创建新的 Agent 线程'
}

watch(
  () => [selectedKb.value?.id, agentForm.trace_id, agentForm.eval_run_id, agentForm.compare_eval_run_id],
  () => {
    if (!selectedKb.value) {
      currentAgentThreadId.value = ''
      agentForm.thread_id = ''
      return
    }
    const threadId = localStorage.getItem(agentThreadStorageKey()) || ''
    currentAgentThreadId.value = threadId
    agentForm.thread_id = threadId
  }
)


function messageSourceKey(message) {
  return String(message?.id || '')
}


function openNegativeFeedback(message) {
  feedbackDrafts[message.id] = {
    open: true,
    reason: message.feedback?.reason || '',
    comment: message.feedback?.comment || '',
  }
}

async function submitFeedback(message, rating) {
  if (!message?.id || String(message.id).startsWith('local-') || String(message.id).startsWith('stream-')) return
  const draft = feedbackDrafts[message.id] || {}
  if (rating === 'not_helpful' && !draft.reason) {
    openNegativeFeedback(message)
    return
  }
  busy.feedback = message.id
  try {
    const feedback = await api.createUserFeedback({
      message: message.id,
      rating,
      reason: rating === 'not_helpful' ? draft.reason : '',
      comment: rating === 'not_helpful' ? draft.comment || '' : '',
    })
    message.feedback = feedback
    feedbackDrafts[message.id] = { open: false, reason: '', comment: '' }
    await loadAgentActions()
    notice.value = rating === 'not_helpful'
      ? '已记录负反馈，并生成待确认的回归样例动作'
      : '已记录正反馈'
  } catch (err) {
    actionError.value = err.message
  } finally {
    busy.feedback = ''
  }
}

function feedbackStatusText(feedback) {
  if (!feedback) return ''
  if (feedback.rating === 'helpful') return '已标记有帮助'
  const reason = feedbackReasons.find((item) => item.value === feedback.reason)?.label || '负反馈'
  return `已标记没帮助：${reason}`
}

function renderMessageParts(message) {
  const content = message?.content || ''
  const sourceCount = message?.sources?.length || 0
  const parts = []
  const pattern = /\[(\d+)\]/g
  let lastIndex = 0
  let match
  while ((match = pattern.exec(content))) {
    const citationNumber = Number(match[1])
    const isKnownCitation = sourceCount > 0 && citationNumber >= 1 && citationNumber <= sourceCount
    if (!isKnownCitation) continue
    if (match.index > lastIndex) {
      parts.push({ type: 'text', text: content.slice(lastIndex, match.index) })
    }
    parts.push({ type: 'citation', number: citationNumber })
    lastIndex = pattern.lastIndex
  }
  if (lastIndex < content.length) {
    parts.push({ type: 'text', text: content.slice(lastIndex) })
  }
  return parts.length ? parts : [{ type: 'text', text: content }]
}

function sourceCitationNumber(source, index) {
  return Number(source?.citation_id || index + 1)
}

function highlightCitation(message, citationNumber) {
  const key = messageSourceKey(message)
  openSourcePanels[key] = true
  highlightedSourceRefs[key] = Number(citationNumber)
  window.setTimeout(() => {
    if (highlightedSourceRefs[key] === Number(citationNumber)) {
      delete highlightedSourceRefs[key]
    }
  }, 2200)
}

function isSourcePanelOpen(message) {
  return Boolean(openSourcePanels[messageSourceKey(message)])
}

function setSourcePanelOpen(message, isOpen) {
  openSourcePanels[messageSourceKey(message)] = isOpen
}

function isSourceHighlighted(message, source, index) {
  return highlightedSourceRefs[messageSourceKey(message)] === sourceCitationNumber(source, index)
}

const filteredDocuments = computed(() =>
  selectedKb.value ? documents.value.filter((doc) => doc.kb === selectedKb.value.id) : []
)

const isEvalRunning = computed(() =>
  busy.eval ||
  pollingEvalRunIds.value.size > 0 ||
  selectedEvalRun.value?.status === 'running' ||
  evalRuns.value.some((run) => run.status === 'running')
)

const selectedTraces = computed(() =>
  selectedTraceIds.value
    .map((id) => traceHistory.value.find((trace) => trace.id === id))
    .filter(Boolean)
)

const selectedEvalRuns = computed(() =>
  selectedEvalRunIds.value
    .map((id) => evalRuns.value.find((run) => run.id === id))
    .filter(Boolean)
)

const selectedBaselineEvalRun = computed(() =>
  evalRuns.value.find((run) => run.id === selectedBaselineEvalRunId.value) || null
)


const failureAnalysis = computed(() => {
  const cases = selectedEvalRun.value?.case_results || []
  const groups = [
    { key: 'vector', label: 'Vector Miss' },
    { key: 'bm25', label: 'BM25 Miss' },
    { key: 'hybrid', label: 'Hybrid Drop' },
    { key: 'rerank', label: 'Rerank Drop' },
    { key: 'compression', label: 'Compression Lost' },
    { key: 'final_answer', label: 'Final Answer Wrong' },
  ].map((group) => {
    const failedCases = cases.filter((item) => isCaseFailedAt(item, group.key))
    return {
      ...group,
      count: failedCases.length,
      rate: cases.length ? `${Math.round((failedCases.length / cases.length) * 100)}%` : '-',
      cases: failedCases,
    }
  })
  return {
    groups,
    totalFailed: groups.reduce((sum, group) => sum + group.count, 0),
  }
})

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

const evalRunComparison = computed(() => {
  if (selectedEvalRuns.value.length !== 2) return null
  const [left, right] = selectedEvalRuns.value
  return buildEvalRunComparison(left, right)
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

function formatEvalScore(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(4) : '-'
}

function formatSignedScore(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return ''
  return `${number >= 0 ? '+' : ''}${number.toFixed(4)}`
}

function scoreDeltaClass(value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number === 0) return 'score-delta neutral'
  return number > 0 ? 'score-delta positive' : 'score-delta negative'
}

function numberOrNull(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function deltaScore(left, right) {
  return left === null || right === null ? null : right - left
}

function metricLabel(metric) {
  const labels = {
    faithfulness: 'Faithfulness',
    answer_relevancy: 'Answer Relevancy',
    context_precision: 'Context Precision',
    context_recall: 'Context Recall',
  }
  return labels[metric] || metric
}

const retrievalStages = [
  { key: 'vector', label: 'Vector' },
  { key: 'bm25', label: 'BM25' },
  { key: 'hybrid', label: 'Hybrid' },
  { key: 'rerank', label: 'Rerank' },
  { key: 'compression', label: 'Compression' },
]

function retrievalMetricRows(metrics = {}) {
  return retrievalStages.map((stage) => ({
    stage: stage.key,
    label: stage.label,
    hit_rate: numberOrNull(metrics?.[stage.key]?.hit_rate),
    recall_at_k: numberOrNull(metrics?.[stage.key]?.recall_at_k),
    mrr: numberOrNull(metrics?.[stage.key]?.mrr),
    target_case_count: metrics?.[stage.key]?.target_case_count || 0,
  }))
}

function compareRetrievalMetrics(leftMetrics = {}, rightMetrics = {}) {
  return retrievalMetricRows(rightMetrics).flatMap((rightRow) => {
    const leftRow = retrievalMetricRows(leftMetrics).find((item) => item.stage === rightRow.stage) || {}
    return ['hit_rate', 'recall_at_k', 'mrr'].map((metric) => {
      const leftValue = numberOrNull(leftRow[metric])
      const rightValue = numberOrNull(rightRow[metric])
      return {
        stage: rightRow.stage,
        metric,
        label: `${rightRow.label} ${metric}`,
        left: leftValue,
        right: rightValue,
        delta: deltaScore(leftValue, rightValue),
      }
    })
  })
}

function isCaseFailedAt(item, stageKey) {
  if (stageKey === 'final_answer') {
    const finalAnswer = item.diagnostics?.final_answer
    return !!finalAnswer && finalAnswer.correct === false
  }
  const stage = item.diagnostics?.stages?.[stageKey]
  return !!stage && stage.hit === false
}

function scrollToEvalCase(id) {
  window.requestAnimationFrame(() => {
    document.getElementById(`eval-case-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

function diagnosticStages(item) {
  const stages = item.diagnostics?.stages || {}
  return [
    { key: 'vector', label: 'Vector TopK', ...(stages.vector || {}) },
    { key: 'bm25', label: 'BM25 TopK', ...(stages.bm25 || {}) },
    { key: 'hybrid', label: 'Hybrid TopK', ...(stages.hybrid || {}) },
    { key: 'rerank', label: 'Rerank TopN', ...(stages.rerank || {}) },
    { key: 'compression', label: 'Compression', ...(stages.compression || {}) },
  ]
}

function finalDiagnostic(item) {
  return item.diagnostics?.final_answer || {}
}

function formatDiagnosticPercent(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return `${Math.round(number * 100)}%`
}

function formatTerms(terms) {
  if (!terms || !terms.length) return '无关键项命中'
  return terms.slice(0, 6).join('、')
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

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : '-'
}

function compactText(value, length = 88) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.length > length ? `${text.slice(0, length)}...` : text
}

function chunkOrder(results = []) {
  return results.slice(0, 5).map((item) => item.chunk_id).filter(Boolean)
}

function compareChunkOrder(left = [], right = []) {
  const leftOrder = chunkOrder(left)
  const rightOrder = chunkOrder(right)
  const shared = leftOrder.filter((id) => rightOrder.includes(id))
  return {
    left: leftOrder,
    right: rightOrder,
    sameTop1: leftOrder[0] && leftOrder[0] === rightOrder[0],
    sharedCount: shared.length,
  }
}

const ragParamLabels = {
  query_rewrite_strategy: 'Query Rewrite',
  top_k: 'Vector TopK',
  bm25_top_k: 'BM25 TopK',
  rrf_k: 'RRF K',
  rerank_top_n: 'Rerank TopN',
  compression_strategy: '压缩策略',
}

function formatSettingValue(value) {
  if (value === undefined || value === null || value === '') return '-'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function diffSettings(left, right) {
  const preferredKeys = Object.keys(ragParamLabels)
  const keys = Array.from(new Set([...preferredKeys, ...Object.keys(left), ...Object.keys(right)]))
  return keys
    .filter((key) => JSON.stringify(left[key]) !== JSON.stringify(right[key]))
    .map((key) => ({
      key,
      label: ragParamLabels[key] || key,
      left: formatSettingValue(left[key]),
      right: formatSettingValue(right[key]),
    }))
}





function agentTaskTitle() {
  return '端到端 RAG 修复工作流'
}

function validateAgentTask() {
  if (!agentForm.trace_id && !agentForm.eval_run_id) {
    return '请先选择失败问答 Trace 或 Baseline Eval Run。'
  }
  return ''
}

async function confirmRunAgent() {
  const validationMessage = validateAgentTask()
  if (validationMessage) {
    actionError.value = validationMessage
    return false
  }
  try {
    await ElMessageBox.confirm(
      `即将启动：${agentTaskTitle()}。Agent 会读取当前选择的 Trace / Eval Run，生成诊断、优化方案和需要人工确认的动作。`,
      '确认启动 RAG 修复工作流？',
      {
        confirmButtonText: '确认执行',
        cancelButtonText: '再检查一下',
        type: 'warning',
      },
    )
    return true
  } catch {
    return false
  }
}

async function runAgent() {
  if (!selectedKb.value || !agentForm.message.trim()) return
  const shouldRun = await confirmRunAgent()
  if (!shouldRun) return
  await runAction(async () => {
    busy.agent = true
    completedAgentActions.value = new Set()
    agentResult.value = await api.runRagopsAgent({
      kb: selectedKb.value.id,
      trace: agentForm.trace_id,
      eval_run: agentForm.eval_run_id,
      compare_eval_run: agentForm.compare_eval_run_id,
      thread_id: ensureAgentThreadId(),
      message: agentForm.message,
    })
    currentAgentThreadId.value = agentResult.value?.thread_id || currentAgentThreadId.value
    agentForm.thread_id = currentAgentThreadId.value
    activeExperimentPlan.value = agentResult.value?.experiment_plan || null
    await loadAgentActions()
  })
  busy.agent = false
}

async function loadModelUsage() {
  if (!selectedKb.value) {
    modelUsage.value = null
    agentResult.value = null
    agentActions.value = []
    return
  }
  modelUsage.value = await api.getModelUsageSummary({ kb: selectedKb.value.id })
}

async function loadAgentActions() {
  if (!selectedKb.value) {
    agentActions.value = []
    return
  }
  agentActions.value = await api.listAgentActions({ kb: selectedKb.value.id })
}

async function loadTraceHistory() {
  if (!selectedKb.value) {
    traceHistory.value = []
    selectedTraceIds.value = []
    evalRuns.value = []
    selectedEvalRun.value = null
    selectedEvalRunIds.value = []
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

async function openTrace(trace) {
  const detail = trace.vector_results ? trace : await api.getTrace(trace.id)
  latestTrace.value = detail
  traceHistory.value = traceHistory.value.map((item) => (item.id === detail.id ? detail : item))
}

async function loadEvalRuns() {
  if (!selectedKb.value) {
    evalRuns.value = []
    selectedEvalRun.value = null
    selectedEvalRunIds.value = []
    benchmarkCases.value = []
    return
  }
  busy.evalLoad = true
  try {
    evalRuns.value = await api.listEvalRuns({ kb: selectedKb.value.id })
    if (selectedEvalRun.value && !evalRuns.value.some((run) => run.id === selectedEvalRun.value.id)) {
      selectedEvalRun.value = null
    }
    selectedEvalRunIds.value = selectedEvalRunIds.value.filter((id) => evalRuns.value.some((run) => run.id === id))
    const runningRun = evalRuns.value.find((run) => run.status === 'running')
    if (runningRun) {
      startEvalPolling(runningRun.id)
    }
  } finally {
    busy.evalLoad = false
  }
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

function agentActionBusyKey(card) {
  if (!card) return ''
  if (card.action_id) return `action-${card.action_id}`
  return card.action_type || card.action_uid ? `action-${card.id}` : `card-${card.id}`
}

function agentActionCompletionKey(card) {
  if (!card) return ''
  if (card.action_id) return `action-${card.action_id}`
  return card.action_type || card.action_uid ? `action-${card.id}` : `card-${card.id}`
}

async function confirmAgentAction(card) {
  const actionId = card?.action_id || card?.id
  if (!actionId) return
  try {
    await ElMessageBox.confirm(
      `${card.description || ''}\n\n确认后将执行这条已审计的 Agent 动作。`,
      card.title || '确认执行 Agent 动作？',
      {
        confirmButtonText: '确认执行',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  const busyId = agentActionBusyKey(card)
  busy.agentAction = busyId
  try {
    const updated = await api.confirmAgentAction(actionId)
    selectedDatasetSuite.value = 'regression'
    await loadBenchmarkCases()
    await loadAgentActions()
    if (agentResult.value?.action_cards?.length) {
      agentResult.value.action_cards = agentResult.value.action_cards.map((item) =>
        item.action_id === updated.id
          ? { ...item, status: updated.status, created_case_id: updated.created_case_id, result: updated.result }
          : item
      )
    }
    if (updated.status === 'completed') {
      const next = new Set(completedAgentActions.value)
      next.add(agentActionCompletionKey(card))
      completedAgentActions.value = next
    }
    if (updated.action_type === 'run_experiment_plan' && updated.result?.plan_id) {
      activeExperimentPlan.value = await api.getExperimentPlan(updated.result.plan_id)
      pollExperimentPlan(updated.result.plan_id)
    }
    notice.value = `Agent 动作${actionStatusText(updated)}：${updated.created_case_id || updated.result?.plan_id || displayActionTitle(updated)}`
  } finally {
    busy.agentAction = ''
  }
}



async function refreshExperimentPlan(planId = activeExperimentPlan.value?.id) {
  if (!planId) return
  activeExperimentPlan.value = await api.getExperimentPlan(planId)
  return activeExperimentPlan.value
}

async function pollExperimentPlan(planId) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const plan = await refreshExperimentPlan(planId)
    if (!plan || ['completed', 'failed'].includes(plan.status)) {
      if (plan?.status === 'completed') {
        await loadEvalRuns()
        notice.value = `实验计划 #${plan.id} 已完成，推荐 Winner：${plan.recommendation?.winner_name || '-'}`
      }
      return
    }
    await sleep(3000)
  }
}

function hasDiagnosis(diagnosis) {
  return Boolean(diagnosis && (diagnosis.summary || diagnosis.failure_signals?.length || diagnosis.recommendations?.length))
}

function diagnosisSeverityText(severity) {
  const map = {
    high: '高风险',
    medium: '中风险',
    low: '低风险',
    info: '观察',
  }
  return map[severity] || '观察'
}

function diagnosisSeverityClass(severity) {
  return severity || 'info'
}

function displayActionTitle(action) {
  const title = action?.title || ''
  const map = {
    'Create Regression Case': '创建 Regression Case',
    'Create Regression Case from Failure': '从失败样例创建 Regression Case',
  }
  return map[title] || title
}

function displayActionSource(source) {
  const map = {
    trace: 'Trace',
    eval_failure: '评测失败',
  }
  return map[source] || source || '-'
}

function isAgentCardDone(card) {
  return completedAgentActions.value.has(agentActionCompletionKey(card)) || card?.status === 'completed'
}

function actionStatusText(action) {
  if (!action) return '-'
  if (action.status === 'completed') return `已完成${action.created_case_id ? ` -> ${action.created_case_id}` : ''}`
  if (action.status === 'failed') return '失败'
  if (action.status === 'rejected') return '已拒绝'
  return '待确认'
}

function actionFailureSignals(card) {
  return card?.failure_signals || card?.payload?.failure_signals || []
}

function actionCardMeta(card) {
  if (card?.source === 'trace') return `Trace #${card.payload?.trace || '-'}`
  if (card?.source === 'eval_failure') return `Eval Case Result #${card.payload?.eval_case || '-'}`
  return card?.source || ''
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

function buildEvalRunComparison(left, right) {
  if (!left?.case_results || !right?.case_results) return null
  const metricNames = Array.from(new Set([...(left.metrics || []), ...(right.metrics || [])]))
  const rightCaseMap = new Map((right.case_results || []).map((item) => [item.case_id, item]))
  return {
    metricDeltas: metricNames.map((metric) => {
      const leftScore = numberOrNull(left.mean_scores?.[metric])
      const rightScore = numberOrNull(right.mean_scores?.[metric])
      return {
        metric,
        left: leftScore,
        right: rightScore,
        delta: deltaScore(leftScore, rightScore),
      }
    }),
    retrievalMetricDeltas: compareRetrievalMetrics(left.retrieval_metrics || {}, right.retrieval_metrics || {}),
    settingsChanged: diffSettings(left.settings || {}, right.settings || {}),
    caseDeltas: (left.case_results || [])
      .map((leftCase) => {
        const rightCase = rightCaseMap.get(leftCase.case_id)
        if (!rightCase) return null
        return {
          case_id: leftCase.case_id,
          question: rightCase.question || leftCase.question,
          metrics: metricNames.map((metric) => {
            const leftScore = numberOrNull(leftCase.scores?.[metric])
            const rightScore = numberOrNull(rightCase.scores?.[metric])
            return {
              metric,
              left: leftScore,
              right: rightScore,
              delta: deltaScore(leftScore, rightScore),
            }
          }),
        }
      })
      .filter(Boolean),
  }
}

async function openEvalRun(run) {
  busy.evalDetail = run.id
  try {
    const detail = run.case_results ? run : await api.getEvalRun(run.id)
    selectedEvalRun.value = detail
    evalRuns.value = evalRuns.value.map((item) => (item.id === detail.id ? detail : item))
    if (detail.baseline_run && !selectedBaselineEvalRunId.value) {
      selectedBaselineEvalRunId.value = detail.baseline_run
    }
  } finally {
    busy.evalDetail = ''
  }
}

async function setBaselineEvalRun(run) {
  if (!run?.id) return
  if (!run.case_results) await openEvalRun(run)
  selectedBaselineEvalRunId.value = run.id
  notice.value = `已设置 Baseline Run #${run.id}（${run.param_signature || 'no-signature'}）`
}

async function compareEvalRunWithBaseline(run) {
  if (!run?.id || !selectedBaselineEvalRunId.value || selectedBaselineEvalRunId.value === run.id) return
  const baseline = evalRuns.value.find((item) => item.id === selectedBaselineEvalRunId.value)
  if (!baseline) return
  if (!baseline.case_results) await openEvalRun(baseline)
  if (!run.case_results) await openEvalRun(run)
  selectedEvalRunIds.value = [selectedBaselineEvalRunId.value, run.id]
}

async function toggleEvalRunCompare(run) {
  let ids = [...selectedEvalRunIds.value]
  if (ids.includes(run.id)) {
    ids = ids.filter((id) => id !== run.id)
  } else {
    ids = [...ids.slice(-1), run.id]
    if (!run.case_results) await openEvalRun(run)
  }
  selectedEvalRunIds.value = ids
  await Promise.all(
    ids.map(async (id) => {
      const runItem = evalRuns.value.find((item) => item.id === id)
      if (runItem && !runItem.case_results) await openEvalRun(runItem)
    })
  )
}

async function runEval() {
  if (!selectedKb.value || isEvalRunning.value) return
  await runAction(async () => {
    busy.eval = true
    notice.value = 'RAGAS 评测正在运行，完成后会自动展示报告'
    const startedRun = await api.runEval({
      kb: selectedKb.value.id,
      suite: selectedEvalSuite.value,
      baseline_run: selectedBaselineEvalRunId.value || undefined,
      rag_options: { ...ragOptions },
    })
    selectedEvalRun.value = startedRun
    evalRuns.value = [startedRun, ...evalRuns.value.filter((run) => run.id !== startedRun.id)]
    startEvalPolling(startedRun.id)
  })
}

async function startEvalPolling(id) {
  if (pollingEvalRunIds.value.has(id)) return
  pollingEvalRunIds.value = new Set([...pollingEvalRunIds.value, id])
  busy.eval = true
  try {
    const result = await pollEvalRun(id)
    await loadEvalRuns()
    selectedEvalRun.value = result
    notice.value = `评测完成：RAGAS Run #${result.id}`
  } catch (err) {
    actionError.value = err.message
  } finally {
    const next = new Set(pollingEvalRunIds.value)
    next.delete(id)
    pollingEvalRunIds.value = next
    busy.eval = pollingEvalRunIds.value.size > 0
  }
}

async function pollEvalRun(id) {
  let intervalMs = 3000
  const maxIntervalMs = 10000
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const run = await api.getEvalRun(id)
    selectedEvalRun.value = run
    evalRuns.value = evalRuns.value.map((item) => (item.id === run.id ? run : item))
    if (run.status === 'completed') return run
    if (run.status === 'failed') throw new Error(run.error_message || 'RAGAS 评测失败')
    const waitMs = document.hidden ? Math.max(intervalMs, 15000) : intervalMs
    await sleep(waitMs)
    if (!document.hidden) {
      intervalMs = Math.min(Math.round(intervalMs * 1.5), maxIntervalMs)
    }
  }
  throw new Error('RAGAS 评测仍在运行，请稍后刷新评测报告')
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
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
    messages.value = []
    session.value = null
    latestTrace.value = null
    traceHistory.value = []
    selectedTraceIds.value = []
    evalRuns.value = []
    selectedEvalRun.value = null
    selectedEvalRunIds.value = []
    benchmarkCases.value = []
    modelUsage.value = null
    agentResult.value = null
    notice.value = `已重置：知识库 ${result.deleted.knowledge_bases} 个，文档 ${result.deleted.documents} 个，切片 ${result.deleted.chunks} 个，会话 ${result.deleted.chat_sessions} 个`
    await loadKbs()
    documents.value = await api.listDocuments()
  })
  busy.reset = false
}

async function bootstrap() {
  store.user = await api.me()
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
  messages.value = []
  session.value = null
  chatSessions.value = []
  latestTrace.value = null
  selectedTraceIds.value = []
  evalRuns.value = []
  selectedEvalRun.value = null
  selectedEvalRunIds.value = []
  benchmarkCases.value = []
  agentActions.value = []
  chatSessions.value = []
  loadTraceHistory()
  loadEvalRuns()
  loadBenchmarkCases()
  loadModelUsage()
  loadAgentActions()
  loadChatSessions({ restore: true })
  agentResult.value = null
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

function lastSessionStorageKey(kbId = selectedKb.value?.id) {
  return kbId ? `aiassistant:last-session:${kbId}` : ''
}

function rememberSession(sessionId, kbId = selectedKb.value?.id) {
  const key = lastSessionStorageKey(kbId)
  if (key && sessionId) localStorage.setItem(key, String(sessionId))
}

async function loadChatSessions({ restore = false } = {}) {
  if (!selectedKb.value) {
    chatSessions.value = []
    return
  }
  chatSessions.value = await api.listSessions({ kb: selectedKb.value.id })
  if (session.value?.id) {
    const refreshedCurrent = chatSessions.value.find((item) => item.id === session.value.id)
    if (refreshedCurrent) session.value = refreshedCurrent
  }
  if (!restore) return
  const savedId = Number(localStorage.getItem(lastSessionStorageKey()) || 0)
  const target = chatSessions.value.find((item) => item.id === savedId) || chatSessions.value[0]
  if (target) {
    await selectChatSession(target, { remember: false })
  }
}

async function selectChatSessionById(value) {
  const id = Number(value)
  const target = chatSessions.value.find((item) => item.id === id)
  if (target) await selectChatSession(target)
}

async function selectChatSession(item, { remember = true } = {}) {
  session.value = item
  messages.value = await api.listMessages(item.id)
  if (remember) rememberSession(item.id, item.kb)
}

async function deleteChatSession(item) {
  if (!item?.id) return
  try {
    await ElMessageBox.confirm(
      '删除后该会话的消息、Trace 和反馈记录也会一并删除。',
      `确认删除会话 #${item.id}？`,
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
  await runAction(async () => {
    await api.deleteSession(item.id)
    const deletedCurrent = session.value?.id === item.id
    chatSessions.value = chatSessions.value.filter((sessionItem) => sessionItem.id !== item.id)
    if (String(localStorage.getItem(lastSessionStorageKey(item.kb))) === String(item.id)) {
      localStorage.removeItem(lastSessionStorageKey(item.kb))
    }
    if (deletedCurrent) {
      const nextSession = chatSessions.value[0] || null
      session.value = nextSession
      messages.value = nextSession ? await api.listMessages(nextSession.id) : []
      latestTrace.value = null
      if (nextSession) rememberSession(nextSession.id, nextSession.kb)
    }
    await loadTraceHistory()
    await loadModelUsage()
    notice.value = `已删除会话 #${item.id}`
  })
}

function chatSessionLabel(item) {
  const count = item.message_count ?? 0
  return `#${item.id} · ${item.display_title || item.title || 'RAG 问答'} · ${count} 条`
}

async function newSession() {
  session.value = await api.createSession({ kb: selectedKb.value.id, title: 'RAG 问答' })
  messages.value = []
  rememberSession(session.value.id)
  await loadChatSessions()
  notice.value = '已创建新会话'
}

async function ask() {
  if (!question.value.trim() || !selectedKb.value) return
  if (!session.value) {
    session.value = await api.createSession({ kb: selectedKb.value.id, title: 'RAG 问答' })
  }
  const userMessage = { id: `local-${Date.now()}`, role: 'user', content: question.value, sources: [] }
  messages.value.push(userMessage)
  const content = question.value
  question.value = ''
  const assistantMessage = {
    id: `stream-${Date.now()}`,
    role: 'assistant',
    content: '',
    sources: [],
  }
  messages.value.push(assistantMessage)
  loading.value = true
  try {
    await api.streamMessage(session.value.id, content, { ...ragOptions }, {
      onSources: (sources) => {
        assistantMessage.sources = sources
      },
      onTrace: (trace) => {
        latestTrace.value = trace
      },
      onDelta: (delta) => {
        assistantMessage.content += delta
      },
      onDone: (message) => {
        Object.assign(assistantMessage, message)
        latestTrace.value = message.trace || latestTrace.value
        loadTraceHistory()
        loadModelUsage()
        loadChatSessions().then(() => {
          if (session.value?.id) rememberSession(session.value.id)
        })
      },
      onError: (data) => {
        throw new Error(data.detail || 'Stream failed')
      },
    })
  } catch (err) {
    actionError.value = err.message
    if (!assistantMessage.content) {
      messages.value = messages.value.filter((message) => message.id !== assistantMessage.id)
    }
  } finally {
    loading.value = false
  }
}

async function runAction(fn) {
  actionError.value = ''
  notice.value = ''
  try {
    await fn()
  } catch (err) {
    actionError.value = err.message
  } finally {
    busy.preview = false
    busy.index = false
    busy.upload = false
    busy.reset = false
    busy.eval = false
  }
}

onBeforeUnmount(() => {
  stopResize()
})
</script>
