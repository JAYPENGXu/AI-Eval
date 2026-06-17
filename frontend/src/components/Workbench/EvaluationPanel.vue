<template>
  <el-collapse v-show="active" :model-value="collapseValue" class="debug-section" @update:model-value="$emit('update:collapse-value', $event)">
    <el-collapse-item name="evaluation">
      <template #title><span>评测报告</span><small>（运行并查看 RAGAS 评测结果）</small></template>
      <div class="debug-section-body">
        <div class="trace-history-toolbar">
          <el-select :model-value="selectedSuite" placeholder="All suites" clearable @change="$emit('update:selected-suite', $event)">
            <el-option label="All suites" value="" />
            <el-option v-for="suite in evalSuites" :key="suite.value" :label="suite.label" :value="suite.value" />
          </el-select>
          <el-button type="primary" class="eval-run-button" @click="$emit('run-eval')" :disabled="!selectedKb || isEvalRunning" :loading="isEvalRunning || busy.eval">
            {{ isEvalRunning ? '评测中' : '运行评测' }}
          </el-button>
          <el-button plain @click="$emit('load-runs')" :disabled="!selectedKb" :loading="busy.evalLoad">刷新</el-button>
          <span class="muted">使用当前调试参数运行 RAGAS，完成后会自动保存并展示报告。</span>
        </div>

        <section class="eval-param-bridge">
          <div>
            <h3>本次评测将使用当前调试参数</h3>
            <p>在“调试”页调整 Query Rewrite、TopK、Rerank 或 Compression 后，点击运行评测会把这些参数保存到新的 Eval Run，后续可与其他 Run 对比。</p>
          </div>
          <div class="eval-param-grid">
            <span v-for="item in paramRows(ragOptions)" :key="item.key">
              <small>{{ item.label }}</small>
              <strong>{{ item.value }}</strong>
            </span>
          </div>
        </section>

        <section class="baseline-strip">
          <div>
            <strong>Baseline</strong>
            <span v-if="selectedBaselineEvalRun">
              #{{ selectedBaselineEvalRun.id }} · {{ selectedBaselineEvalRun.param_signature || '-' }}
            </span>
            <span v-else>未选择。可以在历史 Run 中点击“设为 Baseline”。</span>
          </div>
          <small>后续运行评测会记录它的 baseline_run，历史 Run 也可以一键与 Baseline 对比。</small>
        </section>

        <div v-if="!evalRuns.length" class="empty-state">暂无评测报告。点击“运行评测”后，这里会展示每次参数组合的评分。</div>
        <div v-else class="eval-run-list">
          <article
            v-for="run in evalRuns"
            :key="run.id"
            class="eval-run-item"
            :class="{ active: selectedEvalRun?.id === run.id }"
          >
            <div class="trace-history-main">
              <strong>#{{ run.id }} · {{ run.status }} · {{ run.case_count }} cases</strong>
              <small>
                {{ formatDate(run.created_at) }} · {{ run.kb_name || selectedKb?.name }}
                · 签名 {{ run.param_signature || '-' }}
                <template v-if="run.baseline_run"> · baseline #{{ run.baseline_run }}</template>
              </small>
              <div class="eval-score-row">
                <span v-for="metric in run.metrics" :key="metric">
                  {{ metricLabel(metric) }} {{ formatEvalScore(run.mean_scores?.[metric]) }}
                </span>
              </div>
              <div class="eval-run-params">
                <span v-for="item in compactParamRows(run.settings)" :key="item.key">
                  {{ item.label }} {{ item.value }}
                </span>
              </div>
            </div>
            <div class="trace-history-actions">
              <el-button plain @click="$emit('open-run', run)" :loading="busy.evalDetail === run.id">查看</el-button>
              <el-button plain @click="$emit('set-baseline', run)" :disabled="selectedBaselineEvalRun?.id === run.id">设为 Baseline</el-button>
              <el-button
                @click="$emit('compare-baseline', run)"
                :disabled="!selectedBaselineEvalRun || selectedBaselineEvalRun.id === run.id"
                :loading="busy.evalDetail === run.id && !run.case_results"
              >
                对比 Baseline
              </el-button>
              <el-button @click="$emit('toggle-compare', run)" :loading="busy.evalDetail === run.id && !run.case_results">
                {{ selectedEvalRunIds.includes(run.id) ? '取消' : '对比' }}
              </el-button>
            </div>
          </article>
        </div>

        <section v-if="evalRunComparison" class="eval-compare">
          <div class="trace-title">
            <h3>评测 Run 对比</h3>
            <span>
              #{{ selectedEvalRuns[0].id }} ↔ #{{ selectedEvalRuns[1].id }}
              · {{ selectedEvalRuns[0].param_signature || '-' }} → {{ selectedEvalRuns[1].param_signature || '-' }}
            </span>
          </div>
          <div class="eval-score-grid">
            <div v-for="item in evalRunComparison.metricDeltas" :key="item.metric">
              <strong>{{ metricLabel(item.metric) }}</strong>
              <span>{{ formatEvalScore(item.right) }}</span>
              <small>
                {{ formatEvalScore(item.left) }} -> {{ formatEvalScore(item.right) }}
                <b :class="scoreDeltaClass(item.delta)">
                  {{ formatSignedScore(item.delta) }}
                </b>
              </small>
            </div>
          </div>

          <el-collapse class="sentence-details" :model-value="['settings']">
            <el-collapse-item :title="`参数差异 ${evalRunComparison.settingsChanged.length} 项`" name="settings">
            <div v-if="!evalRunComparison.settingsChanged.length" class="empty-state">两次评测的参数一致。</div>
            <div v-else class="settings-diff">
              <div v-for="item in evalRunComparison.settingsChanged" :key="item.key">
                <strong>{{ item.label || item.key }}</strong>
                <span>{{ item.left }}</span>
                <span>{{ item.right }}</span>
              </div>
            </div>
            </el-collapse-item>
          </el-collapse>

          <div class="eval-case-delta-list">
            <article v-for="caseItem in evalRunComparison.caseDeltas" :key="caseItem.case_id" class="eval-case">
              <div class="trace-item-head">
                <strong>{{ caseItem.question }}</strong>
                <span>{{ caseItem.case_id }}</span>
              </div>
              <div class="compare-table">
                <div v-for="metric in caseItem.metrics" :key="metric.metric">
                  <strong>{{ metricLabel(metric.metric) }}</strong>
                  <span>{{ formatEvalScore(metric.left) }}</span>
                  <span>
                    {{ formatEvalScore(metric.right) }}
                    <b :class="scoreDeltaClass(metric.delta)">{{ formatSignedScore(metric.delta) }}</b>
                  </span>
                </div>
              </div>
            </article>
          </div>
        </section>

        <section v-if="selectedEvalRun" class="eval-report">
          <div class="trace-title">
            <h3>RAGAS Run #{{ selectedEvalRun.id }}</h3>
            <span>
              {{ selectedEvalRun.status }} · {{ formatDate(selectedEvalRun.finished_at || selectedEvalRun.created_at) }}
              · 签名 {{ selectedEvalRun.param_signature || '-' }}
              <template v-if="selectedEvalRun.baseline_run"> · baseline #{{ selectedEvalRun.baseline_run }}</template>
            </span>
          </div>
          <div class="eval-score-grid">
            <div v-for="metric in selectedEvalRun.metrics" :key="metric">
              <strong>{{ metricLabel(metric) }}</strong>
              <span>{{ formatEvalScore(selectedEvalRun.mean_scores?.[metric]) }}</span>
            </div>
          </div>
          <div class="retrieval-metric-grid">
            <div v-for="item in retrievalMetricRows(selectedEvalRun.retrieval_metrics)" :key="item.stage">
              <strong>{{ item.label }}</strong>
              <span>Hit {{ formatEvalScore(item.hit_rate) }}</span>
              <small>Recall@K {{ formatEvalScore(item.recall_at_k) }} / MRR {{ formatEvalScore(item.mrr) }} / target {{ item.target_case_count }}</small>
            </div>
            <div v-if="selectedEvalRun.retrieval_metrics?.deterministic">
              <strong>Deterministic</strong>
              <span>Pass {{ formatEvalScore(selectedEvalRun.retrieval_metrics.deterministic.pass_rate) }}</span>
              <small>{{ selectedEvalRun.retrieval_metrics.deterministic.passed_count || 0 }} passed / {{ selectedEvalRun.retrieval_metrics.deterministic.failed_count || 0 }} failed</small>
            </div>
            <div v-if="selectedEvalRun.retrieval_metrics?.judge">
              <strong>LLM Judge</strong>
              <span>Pass {{ formatEvalScore(selectedEvalRun.retrieval_metrics.judge.pass_rate) }}</span>
              <small>Correct {{ formatEvalScore(selectedEvalRun.retrieval_metrics.judge.mean_correctness_score) }} / Citation {{ formatEvalScore(selectedEvalRun.retrieval_metrics.judge.mean_citation_score) }} / Hallucination {{ formatEvalScore(selectedEvalRun.retrieval_metrics.judge.mean_hallucination_risk) }}</small>
            </div>
          </div>
          <section class="eval-param-snapshot">
            <div class="trace-title">
              <h3>本次 Run 参数快照</h3>
              <span>用于复现和对比</span>
            </div>
            <div class="eval-param-grid">
              <span v-for="item in paramRows(selectedEvalRun.settings)" :key="item.key">
                <small>{{ item.label }}</small>
                <strong>{{ item.value }}</strong>
              </span>
            </div>
          </section>

          <section class="failure-analysis">
            <div class="trace-title">
              <h3>Failure Analysis</h3>
              <span>{{ failureAnalysis.totalFailed }} failed signals</span>
            </div>
            <div class="failure-grid">
              <article v-for="group in failureAnalysis.groups" :key="group.key" class="failure-card" :class="{ clean: group.count === 0 }">
                <strong>{{ group.label }}</strong>
                <span>{{ group.count }}</span>
                <small>{{ group.rate }} of cases</small>
                <div v-if="group.cases.length" class="failure-case-list">
                  <button
                    v-for="caseItem in group.cases.slice(0, 5)"
                    :key="caseItem.id"
                    type="button"
                    class="ghost"
                    @click="$emit('scroll-to-case', caseItem.id)"
                  >
                    {{ compactText(caseItem.case_id, 32) }}
                  </button>
                </div>
              </article>
            </div>
          </section>

          <article v-for="item in selectedEvalRun.case_results || []" :key="item.id" :id="`eval-case-${item.id}`" class="eval-case">
            <div class="trace-item-head">
              <strong>{{ item.question }}</strong>
              <span>{{ item.case_id }} · {{ item.rewrite_strategy }} · {{ item.contexts?.length || 0 }} contexts</span>
            </div>
            <p v-if="item.rewritten_query && item.rewritten_query !== item.question" class="eval-question">
              Rewrite: {{ item.rewritten_query }}
            </p>
            <div class="eval-score-row">
              <span v-for="metric in selectedEvalRun.metrics" :key="metric">
                {{ metricLabel(metric) }} {{ formatEvalScore(item.scores?.[metric]) }}
              </span>
            </div>
            <div v-if="item.judge_results" class="judge-summary" :class="item.judge_results.passed ? 'hit' : 'miss'">
              <div>
                <strong>LLM-as-Judge</strong>
                <span>{{ item.judge_results.passed ? '通过' : '待复核' }}</span>
              </div>
              <div class="eval-score-row">
                <span>Correctness {{ formatEvalScore(item.judge_results.correctness_score) }}</span>
                <span>Citation {{ formatEvalScore(item.judge_results.citation_score) }}</span>
                <span>Hallucination {{ formatEvalScore(item.judge_results.hallucination_risk) }}</span>
              </div>
              <p>{{ item.judge_results.reason || item.judge_results.error || '-' }}</p>
            </div>
            <div v-if="item.deterministic_results?.total_count" class="deterministic-chain">
              <div
                v-for="check in item.deterministic_results.checks"
                :key="`${item.id}-${check.key}`"
                class="diagnostic-node"
                :class="check.passed ? 'hit' : 'miss'"
              >
                <strong>{{ deterministicLabel(check.key) }}</strong>
                <span>{{ check.passed ? '通过' : '失败' }}</span>
                <small>期望 {{ formatDeterministicValue(check.expected) }} / 实际 {{ formatDeterministicValue(check.actual) }}</small>
                <p v-if="check.detail">{{ check.detail }}</p>
              </div>
            </div>
            <div v-if="item.diagnostics" class="diagnostic-chain">
              <div
                v-for="stage in diagnosticStages(item)"
                :key="stage.key"
                class="diagnostic-node"
                :class="stage.hit ? 'hit' : 'miss'"
              >
                <strong>{{ stage.label }}</strong>
                <span>{{ stage.hit ? '命中' : '未命中' }} - 覆盖 {{ formatDiagnosticPercent(stage.coverage) }}</span>
                <small>{{ stage.candidate_count ?? '-' }} candidates - {{ formatTerms(stage.matched_terms) }}</small>
                <p v-if="stage.evidence?.snippet">{{ stage.evidence.snippet }}</p>
              </div>
              <div class="diagnostic-node" :class="finalDiagnostic(item).correct ? 'hit' : 'miss'">
                <strong>Final Answer</strong>
                <span>{{ finalDiagnostic(item).correct ? '正确' : '待复核' }} - 覆盖 {{ formatDiagnosticPercent(finalDiagnostic(item).coverage) }}</span>
                <small>{{ formatTerms(finalDiagnostic(item).matched_terms) }}</small>
                <p v-if="finalDiagnostic(item).evidence">{{ finalDiagnostic(item).evidence }}</p>
              </div>
            </div>
            <div class="trace-detail-grid">
              <div>
                <h4>标准答案</h4>
                <p>{{ item.reference }}</p>
              </div>
              <div>
                <h4>模型回答</h4>
                <p>{{ item.answer }}</p>
              </div>
            </div>
            <el-collapse class="sentence-details">
              <el-collapse-item title="查看 Context / Top Chunks" name="contexts">
              <div class="trace-summary">
                <span>BM25：{{ item.top_chunks?.bm25?.join(' -> ') || '-' }}</span>
                <span>Vector：{{ item.top_chunks?.vector?.join(' -> ') || '-' }}</span>
                <span>Hybrid：{{ item.top_chunks?.hybrid?.join(' -> ') || '-' }}</span>
                <span>Rerank：{{ item.top_chunks?.rerank?.join(' -> ') || '-' }}</span>
              </div>
              <pre>{{ (item.contexts || []).join('\n\n---\n\n') }}</pre>
              </el-collapse-item>
            </el-collapse>
          </article>
        </section>
      </div>
    </el-collapse-item>
  </el-collapse>
</template>

<script setup>
defineProps({
  active: { type: Boolean, default: false },
  collapseValue: { type: Array, default: () => ['evaluation'] },
  selectedSuite: { type: String, default: '' },
  selectedKb: { type: Object, default: null },
  evalSuites: { type: Array, default: () => [] },
  isEvalRunning: { type: Boolean, default: false },
  evalRuns: { type: Array, default: () => [] },
  selectedEvalRun: { type: Object, default: null },
  selectedEvalRunIds: { type: Array, default: () => [] },
  selectedEvalRuns: { type: Array, default: () => [] },
  selectedBaselineEvalRun: { type: Object, default: null },
  evalRunComparison: { type: Object, default: null },
  failureAnalysis: { type: Object, default: () => ({ totalFailed: 0, groups: [] }) },
  ragOptions: { type: Object, default: () => ({}) },
  busy: { type: Object, required: true },
  formatDate: { type: Function, required: true },
  metricLabel: { type: Function, required: true },
  formatEvalScore: { type: Function, required: true },
  scoreDeltaClass: { type: Function, required: true },
  formatSignedScore: { type: Function, required: true },
  retrievalMetricRows: { type: Function, required: true },
  diagnosticStages: { type: Function, required: true },
  finalDiagnostic: { type: Function, required: true },
  formatDiagnosticPercent: { type: Function, required: true },
  formatTerms: { type: Function, required: true },
  compactText: { type: Function, required: true },
})

const paramLabels = {
  query_rewrite_strategy: 'Rewrite',
  top_k: 'Vector',
  bm25_top_k: 'BM25',
  rrf_k: 'RRF',
  rerank_top_n: 'Rerank',
  compression_strategy: 'Compression',
}


const deterministicLabels = {
  router_intent: 'Router Intent',
  rewrite_contains: 'Rewrite Contains',
  answer_contains: 'Answer Contains',
  answer_not_contains: 'Answer Not Contains',
  citation_required: 'Citation Required',
  vector_hit: 'Vector Hit',
  bm25_hit: 'BM25 Hit',
  hybrid_hit: 'Hybrid Hit',
  rerank_keep: 'Rerank Keep',
  compression_keep_terms: 'Compression Keep Terms',
  max_total_tokens: 'Max Total Tokens',
  max_latency_ms: 'Max Latency',
}

function deterministicLabel(key) {
  return deterministicLabels[key] || key
}

function formatDeterministicValue(value) {
  if (value === undefined || value === null || value === '') return '-'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const fullParamLabels = {
  query_rewrite_strategy: 'Query Rewrite',
  top_k: 'Vector TopK',
  bm25_top_k: 'BM25 TopK',
  rrf_k: 'RRF K',
  rerank_top_n: 'Rerank TopN',
  compression_strategy: '压缩策略',
}

function formatParamValue(value) {
  if (value === undefined || value === null || value === '') return '-'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function paramRows(settings = {}) {
  return Object.keys(fullParamLabels).map((key) => ({
    key,
    label: fullParamLabels[key],
    value: formatParamValue(settings?.[key]),
  }))
}

function compactParamRows(settings = {}) {
  return Object.keys(paramLabels).map((key) => ({
    key,
    label: paramLabels[key],
    value: formatParamValue(settings?.[key]),
  }))
}

defineEmits([
  'update:collapse-value',
  'update:selected-suite',
  'run-eval',
  'load-runs',
  'open-run',
  'toggle-compare',
  'set-baseline',
  'compare-baseline',
  'scroll-to-case',
])
</script>
