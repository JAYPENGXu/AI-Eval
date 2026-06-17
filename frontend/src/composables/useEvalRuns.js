import { computed, ref } from 'vue'
import { api } from '../api'
import {
  buildEvalRunComparison,
  isCaseFailedAt,
  sleep,
} from './helpers'

export function useEvalRuns({
  selectedKb,
  busy,
  ragOptions,
  notice,
  actionError,
  runAction,
  benchmarkCases,
}) {
  const evalRuns = ref([])
  const selectedEvalRun = ref(null)
  const selectedEvalRunIds = ref([])
  const selectedBaselineEvalRunId = ref(null)
  const selectedEvalSuite = ref('')
  const pollingEvalRunIds = ref(new Set())

  const isEvalRunning = computed(() =>
    busy.eval ||
    pollingEvalRunIds.value.size > 0 ||
    selectedEvalRun.value?.status === 'running' ||
    evalRuns.value.some((run) => run.status === 'running')
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

  const evalRunComparison = computed(() => {
    if (selectedEvalRuns.value.length !== 2) return null
    const [left, right] = selectedEvalRuns.value
    return buildEvalRunComparison(left, right)
  })

  function resetEvalState() {
    evalRuns.value = []
    selectedEvalRun.value = null
    selectedEvalRunIds.value = []
    selectedBaselineEvalRunId.value = null
  }

  async function loadEvalRuns() {
    if (!selectedKb.value) {
      resetEvalState()
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

  function scrollToEvalCase(id) {
    window.requestAnimationFrame(() => {
      document.getElementById(`eval-case-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  return {
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
    startEvalPolling,
    scrollToEvalCase,
  }
}
