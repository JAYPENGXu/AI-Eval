<template>
  <el-collapse v-show="active" :model-value="collapseValue" class="debug-section" @update:model-value="$emit('update:collapse-value', $event)">
    <el-collapse-item name="costs">
      <template #title><span>模型与成本监控</span><small>（Token、成本、慢请求、失败请求与 Trace 成本）</small></template>
      <div class="debug-section-body">
        <div class="trace-history-toolbar cost-toolbar">
          <el-button class="compact-action" @click="$emit('refresh')" :disabled="!selectedKb">刷新</el-button>
          <span>当前知识库：{{ selectedKb?.name || '-' }}</span>
        </div>
        <div v-if="!modelUsage" class="empty-state">暂无模型调用记录。完成一次索引或问答后，这里会展示模型调用、Token 与成本。</div>
        <template v-else>
          <div class="cost-metrics">
            <div><strong>{{ modelUsage.totals.call_count }}</strong><span>总调用次数</span></div>
            <div><strong>{{ modelUsage.totals.total_tokens }}</strong><span>总 Token</span></div>
            <div><strong>{{ formatCost(modelUsage.totals.estimated_cost) }}</strong><span>总成本</span></div>
            <div><strong>{{ modelUsage.totals.avg_latency_ms }} ms</strong><span>平均延迟</span></div>
            <div><strong>{{ modelUsage.totals.slow_count }}</strong><span>慢请求</span></div>
            <div><strong>{{ modelUsage.totals.failed_count }}</strong><span>失败请求</span></div>
          </div>

          <section class="trace-section">
            <h3>各模型成本占比</h3>
            <div v-if="!modelUsage.by_model?.length" class="empty-state">暂无模型调用。</div>
            <el-table v-else :data="modelUsage.by_model" class="cost-table" size="small" table-layout="fixed">
              <el-table-column prop="model" label="模型" min-width="180" />
              <el-table-column prop="call_type" label="类型" min-width="180" />
              <el-table-column prop="call_count" label="调用" width="90" />
              <el-table-column label="Token" width="110">
                <template #default="{ row }">{{ row.total_tokens || 0 }}</template>
              </el-table-column>
              <el-table-column label="成本" width="120">
                <template #default="{ row }">{{ formatCost(row.estimated_cost) }}</template>
              </el-table-column>
              <el-table-column label="占比" width="90">
                <template #default="{ row }">{{ formatCostShare(row.estimated_cost, modelUsage.totals.estimated_cost) }}</template>
              </el-table-column>
            </el-table>
          </section>

          <section class="trace-section">
            <h3>单次 Trace 成本</h3>
            <div v-if="!modelUsage.trace_costs?.length" class="empty-state">暂无已关联 Trace 的模型调用。</div>
            <el-table v-else :data="modelUsage.trace_costs" class="cost-table" size="small">
              <el-table-column label="Trace" width="100">
                <template #default="{ row }">#{{ row.trace }}</template>
              </el-table-column>
              <el-table-column prop="call_count" label="调用" width="90" />
              <el-table-column label="Token" width="110">
                <template #default="{ row }">{{ row.total_tokens || 0 }}</template>
              </el-table-column>
              <el-table-column label="成本" width="120">
                <template #default="{ row }">{{ formatCost(row.estimated_cost) }}</template>
              </el-table-column>
              <el-table-column label="问题" min-width="240">
                <template #default="{ row }">{{ compactText(row.trace__question, 56) }}</template>
              </el-table-column>
            </el-table>
          </section>

          <section class="trace-section">
            <h3>慢请求</h3>
            <div v-if="!modelUsage.slow_calls?.length" class="empty-state">暂无超过 {{ modelUsage.totals.slow_threshold_ms }} ms 的慢请求。</div>
            <article v-for="item in modelUsage.slow_calls" :key="`slow-${item.id}`" class="trace-item">
              <div class="trace-item-head">
                <strong>{{ item.model }} · {{ item.call_type }}</strong>
                <span>{{ item.latency_ms }} ms · {{ formatDate(item.created_at) }}</span>
              </div>
              <p>Token: {{ item.total_tokens }} · Cost: {{ formatCost(item.estimated_cost) }} · Trace: {{ item.trace || '-' }}</p>
            </article>
          </section>

          <section class="trace-section">
            <h3>失败请求</h3>
            <div v-if="!modelUsage.failed_calls?.length" class="empty-state">暂无失败模型调用。</div>
            <article v-for="item in modelUsage.failed_calls" :key="`failed-${item.id}`" class="trace-item">
              <div class="trace-item-head">
                <strong>{{ item.model }} · {{ item.call_type }}</strong>
                <span>{{ formatDate(item.created_at) }}</span>
              </div>
              <p>{{ item.error_message || '无错误信息' }}</p>
            </article>
          </section>
        </template>
      </div>
    </el-collapse-item>
  </el-collapse>
</template>

<script setup>
defineProps({
  active: { type: Boolean, default: false },
  collapseValue: { type: Array, default: () => ['costs'] },
  selectedKb: { type: Object, default: null },
  modelUsage: { type: Object, default: null },
  formatCost: { type: Function, required: true },
  formatCostShare: { type: Function, required: true },
  formatDate: { type: Function, required: true },
  compactText: { type: Function, required: true },
})

defineEmits(['refresh', 'update:collapse-value'])
</script>
