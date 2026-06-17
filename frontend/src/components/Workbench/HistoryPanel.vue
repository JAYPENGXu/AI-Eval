<template>
  <el-collapse v-show="active" :model-value="collapseValue" class="debug-section" @update:model-value="$emit('update:collapse-value', $event)">
    <el-collapse-item name="history">
      <template #title><span>历史调试记录</span><small>（保存、查看与对比 RAG Trace）</small></template>
      <div class="debug-section-body">
        <div class="trace-history-toolbar">
          <el-input :model-value="traceSearch" placeholder="按问题搜索 Trace" @update:model-value="$emit('update:trace-search', $event)" @keyup.enter="$emit('load-history')" />
          <el-button @click="$emit('load-history')" :disabled="!selectedKb">刷新</el-button>
          <el-button plain @click="$emit('clear-compare')" :disabled="!selectedTraceIds.length">清空对比</el-button>
        </div>

        <div v-if="!traceHistory.length" class="empty-state">暂无历史调试记录。发送一次问题后，这里会保存完整 Trace。</div>
        <div v-else class="trace-history-list">
          <article
            v-for="trace in traceHistory"
            :key="trace.id"
            class="trace-history-item"
            :class="{ active: latestTrace?.id === trace.id, selected: selectedTraceIds.includes(trace.id) }"
          >
            <div class="trace-history-main">
              <strong>#{{ trace.id }} · {{ compactText(trace.question, 72) }}</strong>
              <small>{{ formatDate(trace.created_at) }} · {{ trace.kb_name || selectedKb?.name }}</small>
              <div class="trace-summary compact">
                <span>{{ trace.retrieval_mode }}</span>
                <span>saved {{ formatPercent(trace.compression_stats?.saving_ratio) }}</span>
                <span>{{ trace.settings?.vector_store || '-' }}</span>
              </div>
            </div>
            <div class="trace-history-actions">
              <el-button plain @click="$emit('open-trace', trace)">查看</el-button>
              <el-button @click="$emit('toggle-compare', trace)">
                {{ selectedTraceIds.includes(trace.id) ? '取消' : '对比' }}
              </el-button>
            </div>
          </article>
        </div>

        <section v-if="latestTrace" class="trace-history-detail">
          <div class="trace-title">
            <h3>Trace #{{ latestTrace.id }} 详情</h3>
            <span>{{ formatDate(latestTrace.created_at) }}</span>
            <el-button plain @click="$emit('create-case-from-trace', latestTrace)">To Regression</el-button>
          </div>
          <div class="trace-summary">
            <span>模式：{{ latestTrace.retrieval_mode }}</span>
            <span>Vector：{{ latestTrace.vector_results?.length || 0 }}</span>
            <span>BM25：{{ latestTrace.bm25_results?.length || 0 }}</span>
            <span>Hybrid：{{ latestTrace.hybrid_results?.length || 0 }}</span>
            <span>Rerank：{{ latestTrace.rerank_results?.length || 0 }}</span>
            <span>节省：{{ formatPercent(latestTrace.compression_stats?.saving_ratio) }}</span>
          </div>
          <div class="trace-detail-grid">
            <div>
              <h4>问题</h4>
              <p>{{ latestTrace.question }}</p>
            </div>
            <div>
              <h4>答案</h4>
              <p>{{ latestTrace.message_content || '这条 Trace 暂无已关联答案。' }}</p>
            </div>
          </div>
          <section class="trace-section">
            <h3>Rerank Top Results</h3>
            <article v-for="item in latestTrace.rerank_results?.slice(0, 3)" :key="item.chunk_id" class="trace-item">
              <div class="trace-item-head">
                <strong>#{{ item.rank }} · {{ item.document }}</strong>
                <span>{{ item.engine }} · {{ formatScore(item.rerank_score || item.score) }}</span>
              </div>
              <p>{{ item.content }}</p>
            </article>
          </section>
          <el-collapse class="sentence-details">
            <el-collapse-item title="查看压缩后 Context" name="context">
              <pre>{{ latestTrace.compressed_context }}</pre>
            </el-collapse-item>
            <el-collapse-item title="查看 Final Prompt" name="prompt">
              <pre>{{ latestTrace.final_prompt }}</pre>
            </el-collapse-item>
          </el-collapse>
        </section>

        <section v-if="traceComparison" class="trace-compare">
          <div class="trace-title">
            <h3>Trace 对比</h3>
            <span>#{{ selectedTraces[0].id }} ↔ #{{ selectedTraces[1].id }}</span>
          </div>
          <div class="compare-grid">
            <div>
              <h4>问题</h4>
              <p>{{ selectedTraces[0].question }}</p>
            </div>
            <div>
              <h4>问题</h4>
              <p>{{ selectedTraces[1].question }}</p>
            </div>
          </div>

          <div class="compare-table">
            <div><strong>Vector Top5</strong><span>{{ traceComparison.vectorOrder.left.join(' -> ') || '-' }}</span><span>{{ traceComparison.vectorOrder.right.join(' -> ') || '-' }}</span></div>
            <div><strong>BM25 Top5</strong><span>{{ traceComparison.bm25Order.left.join(' -> ') || '-' }}</span><span>{{ traceComparison.bm25Order.right.join(' -> ') || '-' }}</span></div>
            <div><strong>Hybrid Top5</strong><span>{{ traceComparison.hybridOrder.left.join(' -> ') || '-' }}</span><span>{{ traceComparison.hybridOrder.right.join(' -> ') || '-' }}</span></div>
            <div><strong>Rerank Top5</strong><span>{{ traceComparison.rerankOrder.left.join(' -> ') || '-' }}</span><span>{{ traceComparison.rerankOrder.right.join(' -> ') || '-' }}</span></div>
            <div><strong>压缩后 tokens</strong><span>{{ traceComparison.compressionTokens.left }}</span><span>{{ traceComparison.compressionTokens.right }} ({{ traceComparison.compressionTokens.delta >= 0 ? '+' : '' }}{{ traceComparison.compressionTokens.delta }})</span></div>
            <div><strong>节省比例</strong><span>{{ formatPercent(traceComparison.savingRatio.left) }}</span><span>{{ formatPercent(traceComparison.savingRatio.right) }}</span></div>
            <div><strong>上下文长度</strong><span>{{ traceComparison.contextLength.left }}</span><span>{{ traceComparison.contextLength.right }} ({{ traceComparison.contextLength.delta >= 0 ? '+' : '' }}{{ traceComparison.contextLength.delta }})</span></div>
            <div><strong>答案长度</strong><span>{{ traceComparison.answerLength.left }}</span><span>{{ traceComparison.answerLength.right }} ({{ traceComparison.answerLength.delta >= 0 ? '+' : '' }}{{ traceComparison.answerLength.delta }})</span></div>
          </div>

          <el-collapse class="sentence-details">
            <el-collapse-item :title="`参数差异 ${traceComparison.settingsChanged.length} 项`" name="settings">
            <div v-if="!traceComparison.settingsChanged.length" class="empty-state">两条 Trace 的参数一致。</div>
            <div v-else class="settings-diff">
              <div v-for="item in traceComparison.settingsChanged" :key="item.key">
                <strong>{{ item.key }}</strong>
                <span>{{ item.left }}</span>
                <span>{{ item.right }}</span>
              </div>
            </div>
            </el-collapse-item>
          </el-collapse>
        </section>
      </div>
    </el-collapse-item>
  </el-collapse>
</template>

<script setup>
defineProps({
  active: { type: Boolean, default: false },
  collapseValue: { type: Array, default: () => ['history'] },
  traceSearch: { type: String, default: '' },
  selectedKb: { type: Object, default: null },
  traceHistory: { type: Array, default: () => [] },
  latestTrace: { type: Object, default: null },
  selectedTraceIds: { type: Array, default: () => [] },
  selectedTraces: { type: Array, default: () => [] },
  traceComparison: { type: Object, default: null },
  compactText: { type: Function, required: true },
  formatDate: { type: Function, required: true },
  formatPercent: { type: Function, required: true },
  formatScore: { type: Function, required: true },
})

defineEmits([
  'update:collapse-value',
  'update:trace-search',
  'load-history',
  'clear-compare',
  'open-trace',
  'toggle-compare',
  'create-case-from-trace',
])
</script>
