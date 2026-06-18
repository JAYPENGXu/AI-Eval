export function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

export function numberOrNull(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function deltaScore(left, right) {
  return left === null || right === null ? null : right - left
}

export function formatDate(value) {
  return value ? new Date(value).toLocaleString() : '-'
}

export function compactText(value, length = 88) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.length > length ? `${text.slice(0, length)}...` : text
}

export function formatEvalScore(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(4) : '-'
}

export function formatSignedScore(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return ''
  return `${number >= 0 ? '+' : ''}${number.toFixed(4)}`
}

export function scoreDeltaClass(value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number === 0) return 'score-delta neutral'
  return number > 0 ? 'score-delta positive' : 'score-delta negative'
}

export function metricLabel(metric) {
  const labels = {
    faithfulness: 'Faithfulness',
    answer_relevancy: 'Answer Relevancy',
    context_precision: 'Context Precision',
    context_recall: 'Context Recall',
  }
  return labels[metric] || metric
}

export function formatDiagnosticPercent(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return `${Math.round(number * 100)}%`
}

export function formatTerms(terms) {
  if (!terms || !terms.length) return '无关键项命中'
  return terms.slice(0, 6).join('、')
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

export function diffSettings(left, right) {
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

const retrievalStages = [
  { key: 'vector', label: 'Vector' },
  { key: 'bm25', label: 'BM25' },
  { key: 'hybrid', label: 'Hybrid' },
  { key: 'rerank', label: 'Rerank' },
  { key: 'compression', label: 'Compression' },
]

export function retrievalMetricRows(metrics = {}) {
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

export function isCaseFailedAt(item, stageKey) {
  if (stageKey === 'final_answer') {
    const finalAnswer = item.diagnostics?.final_answer
    return !!finalAnswer && finalAnswer.correct === false
  }
  const stage = item.diagnostics?.stages?.[stageKey]
  return !!stage && stage.hit === false
}

export function buildEvalRunComparison(left, right) {
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

export function chunkOrder(results = []) {
  return results.slice(0, 5).map((item) => item.chunk_id).filter(Boolean)
}

export function compareChunkOrder(left = [], right = []) {
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

export function diagnosticStages(item) {
  const stages = item.diagnostics?.stages || {}
  return [
    { key: 'vector', label: 'Vector TopK', ...(stages.vector || {}) },
    { key: 'bm25', label: 'BM25 TopK', ...(stages.bm25 || {}) },
    { key: 'hybrid', label: 'Hybrid TopK', ...(stages.hybrid || {}) },
    { key: 'rerank', label: 'Rerank TopN', ...(stages.rerank || {}) },
    { key: 'compression', label: 'Compression', ...(stages.compression || {}) },
  ]
}

export function finalDiagnostic(item) {
  return item.diagnostics?.final_answer || {}
}
