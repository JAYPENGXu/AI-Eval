import { ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from '../api'
import { getErrorMessage, shouldIgnoreRequestError, sleep } from './polling'

export function useAgent({
  selectedKb,
  agentForm,
  busy,
  notice,
  actionError,
  runAction,
  loadBenchmarkCases,
  loadEvalRuns,
  selectedDatasetSuite,
}) {
  const agentResult = ref(null)
  const agentActions = ref([])
  const currentAgentThreadId = ref('')
  const activeExperimentPlan = ref(null)
  const completedAgentActions = ref(new Set())

  function resetAgentState() {
    agentResult.value = null
    agentActions.value = []
    currentAgentThreadId.value = ''
    activeExperimentPlan.value = null
    completedAgentActions.value = new Set()
    agentForm.thread_id = ''
  }

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

  function applyAgentResult(result) {
    if (!result) return
    agentResult.value = result
    currentAgentThreadId.value = result.thread_id || currentAgentThreadId.value
    agentForm.thread_id = currentAgentThreadId.value
    if (currentAgentThreadId.value) {
      localStorage.setItem(agentThreadStorageKey(), currentAgentThreadId.value)
    }
    activeExperimentPlan.value = result.experiment_plan || activeExperimentPlan.value
  }

  async function loadAgentThreadState() {
    if (!selectedKb.value) return
    const threadId = localStorage.getItem(agentThreadStorageKey()) || currentAgentThreadId.value
    if (!threadId) return
    try {
      const state = await api.getRagopsAgentState({ thread_id: threadId })
      applyAgentResult(state)
    } catch (err) {
      if (shouldIgnoreRequestError(err)) return
      const message = getErrorMessage(err)
      if (!message.includes('404') && !message.toLowerCase().includes('not found')) {
        actionError.value = message
      }
    }
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
    async () => {
      if (!selectedKb.value) {
        currentAgentThreadId.value = ''
        agentForm.thread_id = ''
        return
      }
      const threadId = localStorage.getItem(agentThreadStorageKey()) || ''
      currentAgentThreadId.value = threadId
      agentForm.thread_id = threadId
      await loadAgentThreadState()
    },
  )

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
      applyAgentResult(agentResult.value)
      await loadAgentActions()
    })
    busy.agent = false
  }

  async function loadAgentActions() {
    if (!selectedKb.value) {
      agentActions.value = []
      return
    }
    agentActions.value = await api.listAgentActions({ kb: selectedKb.value.id })
  }

  function agentActionBusyKey(card) {
    if (!card) return ''
    if (card.action_id) return `action-${card.action_id}`
    return card.action_type || card.type || card.action_uid ? `action-${card.id}` : `card-${card.id}`
  }

  function agentActionCompletionKey(card) {
    if (!card) return ''
    if (card.action_id) return `action-${card.action_id}`
    return card.action_type || card.type || card.action_uid ? `action-${card.id}` : `card-${card.id}`
  }

  function isAgentCardRunning(card) {
    if (!card) return false
    return busy.agentAction === agentActionBusyKey(card) || card.status === 'running'
  }

  function updateAgentActionCard(card, patch) {
    if (!agentResult.value?.action_cards?.length) return
    agentResult.value.action_cards = agentResult.value.action_cards.map((item) => {
      const sameAction = card?.action_id && item.action_id === card.action_id
      const sameCard = !card?.action_id && item.id === card?.id
      return sameAction || sameCard ? { ...item, ...patch } : item
    })
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
    updateAgentActionCard(card, { status: 'running' })
    try {
      const updated = await api.confirmAgentAction(actionId)
      if (updated.agent_result) {
        applyAgentResult(updated.agent_result)
      }
      if (updated.action_type === 'run_experiment_plan' && updated.result?.plan_id) {
        updateAgentActionCard(card, { status: updated.status || 'running', result: updated.result })
        activeExperimentPlan.value = await api.getExperimentPlan(updated.result.plan_id)
        await pollExperimentPlan(updated.result.plan_id)
        await loadAgentActions()
        const latest = agentActions.value.find((item) => item.id === updated.id)
        if (latest) {
          updateAgentActionCard(card, {
            status: latest.status,
            result: latest.result,
            error_message: latest.error_message,
          })
          if (latest.status === 'completed') {
            const next = new Set(completedAgentActions.value)
            next.add(agentActionCompletionKey(card))
            completedAgentActions.value = next
          }
          notice.value = `Agent 动作${actionStatusText(latest)}：${latest.result?.plan_id || displayActionTitle(latest)}`
        }
        return
      }

      selectedDatasetSuite.value = 'regression'
      await loadBenchmarkCases()
      await loadAgentActions()
      updateAgentActionCard(card, {
        status: updated.status,
        created_case_id: updated.created_case_id,
        result: updated.result,
        error_message: updated.error_message,
      })
      if (updated.status === 'completed') {
        const next = new Set(completedAgentActions.value)
        next.add(agentActionCompletionKey(card))
        completedAgentActions.value = next
      }
      notice.value = `Agent 动作${actionStatusText(updated)}：${updated.created_case_id || updated.result?.plan_id || displayActionTitle(updated)}`
    } catch (err) {
      if (shouldIgnoreRequestError(err)) return
      updateAgentActionCard(card, { status: 'failed', error_message: getErrorMessage(err) })
      actionError.value = getErrorMessage(err)
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
        await loadAgentActions()
        if (plan?.status === 'completed') {
          await loadEvalRuns()
          notice.value = `实验计划 #${plan.id} 已完成，推荐 Winner：${plan.recommendation?.winner_name || '-'}`
        }
        return plan
      }
      await sleep(3000)
    }
    return activeExperimentPlan.value
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

  function isAgentCardDone(card) {
    if (isAgentCardRunning(card)) return false
    return completedAgentActions.value.has(agentActionCompletionKey(card)) || card?.status === 'completed'
  }

  function actionStatusText(action) {
    if (!action) return '-'
    if (action.status === 'running') return '执行中'
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

  return {
    agentResult,
    agentActions,
    currentAgentThreadId,
    activeExperimentPlan,
    completedAgentActions,
    resetAgentState,
    resetAgentThread,
    runAgent,
    loadAgentActions,
    loadAgentThreadState,
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
  }
}
