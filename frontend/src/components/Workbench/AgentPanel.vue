<template>
  <el-collapse v-show="active" :model-value="collapseValue" class="debug-section" @update:model-value="$emit('update:collapse-value', $event)">
    <el-collapse-item name="agent">
      <template #title><span>RAGOps Agent</span><small>（规划、调用工具并解释 RAG 诊断结果）</small></template>
      <div class="debug-section-body">
        <section class="agent-intro-panel agent-workflow-hero">
          <div>
            <h3>端到端 RAG 修复工作流</h3>
            <p>选择一次失败问答或一组失败评测，Agent 会收集证据、定位失败阶段、生成优化方案，并在需要写操作时通过人工确认动作暂停。</p>
          </div>
          <span>LangGraph + HITL</span>
        </section>

        <section class="agent-workflow-steps" aria-label="RAG 修复工作流步骤">
          <article>
            <strong>1. 收集证据</strong>
            <span>读取 Trace / Eval Run / 调用统计</span>
          </article>
          <article>
            <strong>2. 定位失败阶段</strong>
            <span>改写、召回、重排、压缩、生成</span>
          </article>
          <article>
            <strong>3. 生成优化方案</strong>
            <span>给出参数实验或回归样例建议</span>
          </article>
          <article>
            <strong>4. 人工确认执行</strong>
            <span>创建 Case 或运行实验前先确认</span>
          </article>
        </section>

        <section class="agent-workflow-scope">
          <div class="agent-section-title">
            <h3>选择要修复的问题</h3>
            <p>至少选择一个 Trace 或 Baseline Eval Run。Trace 更适合复盘单次坏回答，Eval Run 更适合从失败样例中生成优化实验。</p>
          </div>
          <div class="agent-context-grid">
            <label>
              失败问答 Trace
              <el-select v-model="agentForm.trace_id" placeholder="不选择" clearable>
                <el-option v-for="trace in traceHistory" :key="trace.id" :label="`#${trace.id} · ${compactText(trace.question, 48)}`" :value="trace.id" />
              </el-select>
            </label>
            <label>
              Baseline Eval Run
              <el-select v-model="agentForm.eval_run_id" placeholder="不选择" clearable>
                <el-option v-for="run in evalRuns" :key="run.id" :label="`#${run.id} · ${run.status} · ${formatDate(run.created_at)}`" :value="run.id" />
              </el-select>
            </label>
          </div>
          <div class="agent-current-task">
            <div>
              <span>当前修复对象</span>
              <strong>{{ repairTargetTitle }}</strong>
              <small>{{ repairTargetContext }}</small>
            </div>
            <p>Agent 只会先生成诊断和建议；创建回归样例、批量运行实验等写操作会进入“待确认动作”。</p>
          </div>
        </section>

        <el-collapse class="agent-context-details">
          <el-collapse-item title="高级选项" name="advanced">
          <div class="agent-context-grid">
            <label>
              对比 Eval Run（可选）
              <el-select v-model="agentForm.compare_eval_run_id" placeholder="不选择" clearable>
                <el-option v-for="run in evalRuns" :key="run.id" :label="`#${run.id} · ${run.status} · ${formatDate(run.created_at)}`" :value="run.id" />
              </el-select>
            </label>
          </div>
          <div class="agent-thread-bar">
            <span>本次分析会话：{{ agentThreadId ? compactText(agentThreadId, 88) : '运行时自动保存' }}</span>
            <el-button plain @click="$emit('new-agent-thread')" :disabled="!selectedKb || busy.agent">重新开始本次分析</el-button>
          </div>
          </el-collapse-item>
        </el-collapse>

        <el-form class="agent-form" @submit.prevent="$emit('run-agent')">
          <el-input
            type="textarea"
            v-model="agentForm.message"
            placeholder="填写优化目标，例如：优先提升答案正确性和召回稳定性，成本不要明显增加。"
          />
          <el-button type="primary" native-type="submit" :disabled="!selectedKb || busy.agent || !agentForm.message.trim()" :loading="busy.agent">
            {{ busy.agent ? 'Agent 思考中' : '开始诊断与优化' }}
          </el-button>
        </el-form>

        <div v-if="!agentResult" class="empty-state">
          选择失败 Trace 或 Baseline Eval Run 后启动工作流。Agent 会把诊断结论、证据、优化方案和需要你确认的动作展示在这里。
        </div>
        <template v-else>
          <section v-if="hasDiagnosis(agentResult.diagnosis)" class="trace-section structured-diagnosis">
            <div class="diagnosis-head">
              <h3>结构化诊断</h3>
              <span :class="['severity-pill', diagnosisSeverityClass(agentResult.diagnosis?.severity)]">
                {{ diagnosisSeverityText(agentResult.diagnosis?.severity) }}
              </span>
            </div>
            <p class="diagnosis-summary">{{ agentResult.diagnosis.summary }}</p>
            <div v-if="agentResult.diagnosis.failure_signals?.length" class="diagnosis-grid">
              <article v-for="signal in agentResult.diagnosis.failure_signals" :key="signal.code" class="diagnosis-card">
                <strong>{{ signal.label }}</strong>
                <span>{{ signal.evidence }}</span>
              </article>
            </div>
            <div v-if="agentResult.diagnosis.recommendations?.length" class="diagnosis-list">
              <h4>优化建议</h4>
              <article v-for="item in agentResult.diagnosis.recommendations" :key="item.code">
                <strong>{{ item.title }}</strong>
                <span>{{ item.detail }}</span>
              </article>
            </div>
            <div v-if="agentResult.diagnosis.recommended_actions?.length" class="diagnosis-list">
              <h4>建议动作</h4>
              <article v-for="item in agentResult.diagnosis.recommended_actions" :key="item.type">
                <strong>{{ item.label }}</strong>
                <span>{{ item.reason }}</span>
              </article>
            </div>
          </section>
          <section v-if="activeExperimentPlan || agentResult.experiment_plan" class="trace-section experiment-plan-section">
            <div class="trace-title">
              <h3>参数实验计划</h3>
              <el-button plain @click="$emit('refresh-experiment-plan', (activeExperimentPlan || agentResult.experiment_plan).id)">
                刷新计划
              </el-button>
            </div>
            <p class="diagnosis-summary">{{ (activeExperimentPlan || agentResult.experiment_plan).goal }}</p>
            <div class="trace-summary">
              <span>Baseline #{{ (activeExperimentPlan || agentResult.experiment_plan).baseline_run }}</span>
              <span>状态：{{ (activeExperimentPlan || agentResult.experiment_plan).status }}</span>
              <span>失败 Case：{{ (activeExperimentPlan || agentResult.experiment_plan).failure_summary?.failed_case_count || 0 }}</span>
              <span>主要阶段：{{ (activeExperimentPlan || agentResult.experiment_plan).failure_summary?.primary_stage || '-' }}</span>
            </div>
            <div class="experiment-variant-grid">
              <article
                v-for="variant in (activeExperimentPlan || agentResult.experiment_plan).variants || []"
                :key="variant.id"
                class="experiment-variant"
                :class="{ winner: variant.is_winner }"
              >
                <strong>{{ variant.name }} <span v-if="variant.is_winner">Winner</span></strong>
                <p>{{ variant.hypothesis }}</p>
                <div class="eval-run-params">
                  <span v-for="(value, key) in variant.rag_options" :key="key">{{ key }} {{ value }}</span>
                </div>
                <small v-if="variant.eval_run">Eval Run #{{ variant.eval_run }} · {{ variant.eval_run_status || '-' }}</small>
                <div v-if="variant.result_summary" class="trace-summary">
                  <span>分数变化 {{ signedNumber(variant.result_summary.score_delta) }}</span>
                  <span>失败数变化 {{ signedNumber(variant.result_summary.failed_delta) }}</span>
                </div>
              </article>
            </div>
            <p v-if="(activeExperimentPlan || agentResult.experiment_plan).recommendation?.reason" class="diagnosis-summary">
              推荐：{{ (activeExperimentPlan || agentResult.experiment_plan).recommendation.reason }}
            </p>
          </section>
          <section class="trace-section agent-report-section">
            <h3>Agent 报告</h3>
            <pre class="agent-report">{{ agentResult.answer }}</pre>
          </section>
          <section v-if="agentResult.action_cards?.length" class="trace-section">
            <h3>人工确认动作</h3>
            <article v-for="card in agentResult.action_cards" :key="card.id" class="action-card">
              <div>
                <strong>{{ card.title }}</strong>
                <p>{{ card.description }}</p>
                <ul v-if="actionFailureSignals(card).length" class="action-reasons">
                  <li v-for="signal in actionFailureSignals(card)" :key="signal.code">
                    <strong>{{ signal.label }}</strong>
                    <span>{{ signal.evidence }}</span>
                  </li>
                </ul>
                <small>{{ actionCardMeta(card) }}</small>
              </div>
              <el-button type="primary" @click="$emit('confirm-action', card)" :disabled="!!busy.agentAction || isAgentCardDone(card)" :loading="isAgentCardRunning(card)">
                {{ isAgentCardDone(card) ? '已完成' : (isAgentCardRunning(card) ? '执行中' : card.confirm_label || '确认') }}
              </el-button>
            </article>
          </section>
          <section class="trace-section agent-plan-section">
            <h3>执行计划</h3>
            <div v-if="!agentResult.plan?.length" class="empty-state">Agent 未生成显式计划。</div>
            <div v-else class="agent-plan-list">
              <article v-for="(step, index) in agentResult.plan" :key="index" class="agent-plan-item">
                <span class="agent-plan-index">{{ index + 1 }}</span>
                <div class="agent-plan-copy">
                  <strong>{{ step.step || step }}</strong>
                  <p v-if="step.reason">{{ step.reason }}</p>
                </div>
              </article>
            </div>
          </section>
          <section class="trace-section">
            <h3>工具调用</h3>
            <div v-if="!agentResult.tool_calls?.length" class="empty-state">没有调用工具。</div>
            <article v-for="(call, index) in agentResult.tool_calls" :key="index" class="trace-item">
              <div class="trace-item-head">
                <strong>{{ call.tool }}</strong>
                <span>{{ JSON.stringify(call.args || {}) }}</span>
              </div>
            </article>
          </section>
          <section class="trace-section">
            <div class="trace-title">
              <h3>待确认动作</h3>
              <span>{{ pendingAgentActions.length }} 项</span>
            </div>
            <div v-if="!pendingAgentActions.length" class="empty-state">暂无待确认动作。Agent 需要执行写操作时，会先在这里征求你的确认。</div>
            <div v-else class="agent-action-log">
              <article v-for="action in pendingAgentActions" :key="action.id" class="agent-action-row pending">
                <div>
                  <strong>{{ displayActionTitle(action) }}</strong>
                  <span>{{ actionSourceLabel(action) }} · {{ actionStatusText(action) }} · {{ formatDate(action.created_at) }}</span>
                  <small v-if="actionPlanId(action)">Experiment Plan：#{{ actionPlanId(action) }}</small>
                  <small v-if="action.created_case_id">Case：{{ action.created_case_id }}</small>
                  <small v-if="action.error_message">错误：{{ action.error_message }}</small>
                </div>
                <el-button
                  type="primary"
                  @click="$emit('confirm-action', action)"
                  :disabled="!!busy.agentAction || action.status === 'completed' || action.status === 'running'"
                  :loading="busy.agentAction === `action-${action.id}`"
                >
                  {{ busy.agentAction === `action-${action.id}` ? '执行中' : (action.status === 'running' ? '执行中' : (action.confirm_label || '确认')) }}
                </el-button>
              </article>
            </div>
          </section>

          <section class="trace-section audit-section">
            <el-collapse>
              <el-collapse-item name="audit">
                <template #title>
                  <span>历史审计记录</span>
                  <small>记录 Agent 曾建议过什么、谁确认了什么、执行是否成功。</small>
                </template>
              <div class="audit-toolbar">
                <el-button
                  v-for="item in auditFilters"
                  :key="item.value"
                  size="small"
                  :class="{ active: auditStatusFilter === item.value }"
                  @click="auditStatusFilter = item.value"
                >
                  {{ item.label }}
                </el-button>
              </div>
              <div v-if="!filteredAuditActions.length" class="empty-state">暂无符合条件的审计记录。</div>
              <div v-else class="agent-action-log">
                <article v-for="action in visibleAuditActions" :key="action.id" class="agent-action-row compact">
                  <div>
                    <strong>{{ displayActionTitle(action) }}</strong>
                    <span>{{ actionSourceLabel(action) }} · {{ actionStatusText(action) }} · {{ formatDate(action.created_at) }}</span>
                    <small v-if="actionPlanId(action)">Experiment Plan：#{{ actionPlanId(action) }}</small>
                    <small v-if="action.created_case_id">Case：{{ action.created_case_id }}</small>
                    <small v-if="action.error_message">错误：{{ action.error_message }}</small>
                  </div>
                  <el-button
                    v-if="action.status !== 'completed' && action.status !== 'rejected' && action.status !== 'running'"
                    type="primary"
                    @click="$emit('confirm-action', action)"
                    :disabled="!!busy.agentAction"
                    :loading="busy.agentAction === `action-${action.id}`"
                  >
                    {{ busy.agentAction === `action-${action.id}` ? '执行中' : '确认' }}
                  </el-button>
                  <span v-else-if="action.status === 'running'" class="status-pill">执行中</span>
                  <span v-else class="status-pill">{{ actionStatusText(action) }}</span>
                </article>
                <el-button
                  v-if="filteredAuditActions.length > 3 && auditStatusFilter !== 'all'"
                  plain
                  class="audit-more"
                  @click="auditStatusFilter = 'all'"
                >
                  查看全部 {{ filteredAuditActions.length }} 条
                </el-button>
              </div>
              </el-collapse-item>
            </el-collapse>
          </section>
        </template>
      </div>
    </el-collapse-item>
  </el-collapse>
</template>

<script setup>
import { computed, ref } from 'vue'
const props = defineProps({
  active: { type: Boolean, default: false },
  collapseValue: { type: Array, default: () => ['agent'] },
  selectedKb: { type: Object, default: null },
  agentForm: { type: Object, required: true },
  traceHistory: { type: Array, default: () => [] },
  evalRuns: { type: Array, default: () => [] },
  busy: { type: Object, required: true },
  agentResult: { type: Object, default: null },
  agentActions: { type: Array, default: () => [] },
  activeExperimentPlan: { type: Object, default: null },
  agentThreadId: { type: String, default: '' },
  selectedAgentTask: { type: String, default: '' },
  compactText: { type: Function, required: true },
  formatDate: { type: Function, required: true },
  hasDiagnosis: { type: Function, required: true },
  diagnosisSeverityClass: { type: Function, required: true },
  diagnosisSeverityText: { type: Function, required: true },
  actionFailureSignals: { type: Function, required: true },
  actionCardMeta: { type: Function, required: true },
  isAgentCardDone: { type: Function, required: true },
  isAgentCardRunning: { type: Function, required: true },
  displayActionTitle: { type: Function, required: true },
  actionStatusText: { type: Function, required: true },
})


const repairTargetTitle = computed(() => {
  if (props.agentForm.trace_id && props.agentForm.eval_run_id) return 'Trace + Eval Run 联合诊断'
  if (props.agentForm.trace_id) return '单次坏回答诊断'
  if (props.agentForm.eval_run_id) return '评测失败集诊断'
  return '尚未选择修复对象'
})

const repairTargetContext = computed(() => {
  const parts = []
  if (props.agentForm.trace_id) parts.push(`Trace #${props.agentForm.trace_id}`)
  if (props.agentForm.eval_run_id) parts.push(`Baseline Run #${props.agentForm.eval_run_id}`)
  if (props.agentForm.compare_eval_run_id) parts.push(`对比 Run #${props.agentForm.compare_eval_run_id}`)
  return parts.length ? parts.join('，') : '请先选择失败 Trace 或 Baseline Eval Run'
})

const auditStatusFilter = ref('pending')
const auditFilters = [
  { value: 'pending', label: '待确认' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'all', label: '全部' },
]

const pendingAgentActions = computed(() =>
  (props.agentActions || []).filter((action) => ['pending', 'failed', 'running'].includes(action.status))
)

const filteredAuditActions = computed(() => {
  const actions = props.agentActions || []
  if (auditStatusFilter.value === 'all') return actions
  if (auditStatusFilter.value === 'pending') {
    return actions.filter((action) => ['pending', 'failed', 'running'].includes(action.status))
  }
  return actions.filter((action) => action.status === auditStatusFilter.value)
})

const visibleAuditActions = computed(() =>
  auditStatusFilter.value === 'all' ? filteredAuditActions.value : filteredAuditActions.value.slice(0, 3)
)

function actionSourceLabel(action) {
  const map = {
    experiment_plan: '参数实验',
    user_feedback: '用户反馈',
    trace: 'Trace',
    eval_failure: '评测失败',
  }
  return map[action?.source] || action?.source || '-'
}

function actionPlanId(action) {
  return action?.payload?.experiment_plan || action?.result?.plan_id || ''
}

function signedNumber(value) {
  if (value === undefined || value === null || value === '') return '-'
  const number = Number(value)
  if (Number.isNaN(number)) return String(value)
  return `${number >= 0 ? '+' : ''}${number}`
}

defineEmits(['quick-task', 'run-agent', 'confirm-action', 'refresh-experiment-plan', 'new-agent-thread', 'update:collapse-value'])
</script>
