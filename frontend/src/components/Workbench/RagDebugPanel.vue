<template>
  <el-collapse v-show="active" :model-value="collapseValue" class="debug-section" @update:model-value="$emit('update:collapse-value', $event)">
    <el-collapse-item name="rag-debug">
      <template #title><span>RAG 检索调试</span><small>（向量召回、上下文与最终 Prompt）</small></template>
      <div class="debug-section-body">
        <div class="trace-panel">
          <div class="trace-title">
            <h3>RAG 检索调试</h3>
            <span v-if="latestTrace">Trace #{{ latestTrace.id }}</span>
          </div>
          <el-form class="rag-options element-toolbar" label-position="top">
            <el-form-item label="Query Rewrite">
              <el-select v-model="ragOptions.query_rewrite_strategy">
                <el-option v-for="option in queryRewriteStrategies" :key="option.value" :label="option.label" :value="option.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="Vector top_k">
              <el-input-number v-model="ragOptions.top_k" :min="1" :max="20" />
            </el-form-item>
            <el-form-item label="BM25 top_k">
              <el-input-number v-model="ragOptions.bm25_top_k" :min="1" :max="20" />
            </el-form-item>
            <el-form-item label="RRF_K">
              <el-input-number v-model="ragOptions.rrf_k" :min="1" :max="500" />
            </el-form-item>
            <el-form-item label="Rerank top_n">
              <el-input-number v-model="ragOptions.rerank_top_n" :min="1" :max="20" />
            </el-form-item>
            <el-form-item label="Context Compression">
              <el-select v-model="ragOptions.compression_strategy">
                <el-option v-for="option in compressionStrategies" :key="option.value" :label="option.label" :value="option.value" />
              </el-select>
            </el-form-item>
            <span>{{ currentRewriteDescription }} · {{ currentCompressionDescription }}</span>
          </el-form>
          <div v-if="!latestTrace" class="empty-state">发送一个问题后，这里会展示本次向量召回、上下文和最终 Prompt。</div>
          <template v-else>
            <div class="trace-summary">
              <span>意图：{{ formatIntent(latestTrace.query_intent || latestTrace.settings?.query_intent) }}</span>
              <span>路由：{{ formatRoute(latestTrace.route_decision || latestTrace.settings?.route_decision) }}</span>
              <span>模式：{{ latestTrace.retrieval_mode }}</span>
              <span>Top K：{{ latestTrace.settings?.rag_top_k }}</span>
              <span>向量库：{{ latestTrace.settings?.vector_store }}</span>
              <span>Embedding：{{ latestTrace.settings?.embedding_model }}</span>
              <span>BM25 Top K：{{ latestTrace.settings?.bm25_top_k }}</span>
              <span>BM25 k1/b：{{ latestTrace.settings?.bm25_k1 }} / {{ latestTrace.settings?.bm25_b }}</span>
              <span>Hybrid Top K：{{ latestTrace.settings?.hybrid_top_k }}</span>
              <span>RRF k：{{ latestTrace.settings?.rrf_k }}</span>
              <span>Rerank：{{ latestTrace.settings?.rerank_model }}</span>
              <span>Rerank Top N：{{ latestTrace.settings?.rerank_top_n }}</span>
              <span>Compression：{{ latestTrace.settings?.context_compression_strategy }}</span>
              <span>节省：{{ formatPercent(latestTrace.compression_stats?.saving_ratio) }}</span>
            </div>

            <section class="trace-section">
              <h3>Conversation Memory</h3>
              <div class="trace-summary">
                <span>摘要：{{ latestTrace.settings?.session_summary_used ? '已使用' : '未使用' }}</span>
                <span>摘要长度：{{ latestTrace.settings?.session_summary_chars || 0 }} 字符</span>
                <span>覆盖消息：{{ latestTrace.settings?.session_summary_message_count || 0 }}</span>
                <span>状态：{{ formatSummaryStatus(latestTrace.settings?.session_summary_status) }}</span>
              </div>
              <div v-if="latestTrace.settings?.session_summary" class="query-rewrite-box">
                <div>
                  <h4>Session Summary</h4>
                  <p>{{ latestTrace.settings.session_summary }}</p>
                </div>
                <div>
                  <h4>Recent Turns</h4>
                  <p>{{ formatConversationContext(latestTrace.settings?.conversation_context) }}</p>
                </div>
              </div>
              <div v-else class="empty-state">当前 Trace 没有使用会话摘要，仅使用最近几轮对话进行问题改写。</div>
            </section>

            <section class="trace-section">
              <h3>Query Router</h3>
              <div class="query-rewrite-box">
                <div>
                  <h4>Intent</h4>
                  <p>{{ formatIntent(latestTrace.query_intent || latestTrace.settings?.query_intent) }}</p>
                </div>
                <div>
                  <h4>Decision</h4>
                  <p>{{ formatRoute(latestTrace.route_decision || latestTrace.settings?.route_decision) }}</p>
                </div>
              </div>
              <p class="route-reason">{{ latestTrace.route_reason || latestTrace.settings?.route_reason }}</p>
            </section>

            <section class="trace-section">
              <h3>Query Rewrite</h3>
              <div class="query-rewrite-box">
                <div>
                  <h4>Original Query</h4>
                  <p>{{ latestTrace.question }}</p>
                </div>
                <div>
                  <h4>Rewritten Query</h4>
                  <p>{{ latestTrace.rewritten_query || latestTrace.question }}</p>
                </div>
              </div>
            </section>

            <section class="trace-section">
              <h3>BM25 Search</h3>
              <div v-if="!latestTrace.bm25_results?.length" class="empty-state">没有关键词召回结果。</div>
              <article v-for="item in latestTrace.bm25_results" :key="item.chunk_id" class="trace-item">
                <div class="trace-item-head">
                  <strong>#{{ item.rank }} · {{ item.document }}</strong>
                  <small v-if="sourceLocation(item)" class="source-location">{{ sourceLocation(item) }}</small>
                  <span>{{ item.engine }} · {{ formatScore(item.score) }}</span>
                </div>
                <div v-if="item.matched_terms?.length" class="matched-terms">
                  <span v-for="term in item.matched_terms" :key="term">{{ term }}</span>
                </div>
                <p>{{ item.content }}</p>
              </article>
            </section>

            <section class="trace-section">
              <h3>Hybrid Fusion (RRF)</h3>
              <div v-if="!latestTrace.hybrid_results?.length" class="empty-state">没有融合结果。</div>
              <article v-for="item in latestTrace.hybrid_results" :key="item.chunk_id" class="trace-item">
                <div class="trace-item-head">
                  <strong>#{{ item.rank }} · {{ item.document }}</strong>
                  <small v-if="sourceLocation(item)" class="source-location">{{ sourceLocation(item) }}</small>
                  <span>{{ item.engine }} · {{ formatScore(item.rrf_score || item.score) }}</span>
                </div>
                <div class="matched-terms">
                  <span v-if="item.sources?.bm25">BM25 #{{ item.sources.bm25.rank }}</span>
                  <span v-if="item.sources?.vector">Vector #{{ item.sources.vector.rank }}</span>
                </div>
                <p>{{ item.content }}</p>
              </article>
            </section>

            <section class="trace-section">
              <h3>Rerank</h3>
              <div v-if="!latestTrace.rerank_results?.length" class="empty-state">没有 Rerank 结果。</div>
              <article v-for="item in latestTrace.rerank_results" :key="item.chunk_id" class="trace-item">
                <div class="trace-item-head">
                  <strong>#{{ item.rank }} · {{ item.document }}</strong>
                  <small v-if="sourceLocation(item)" class="source-location">{{ sourceLocation(item) }}</small>
                  <span>{{ item.engine }} · {{ formatScore(item.rerank_score || item.score) }}</span>
                </div>
                <div class="matched-terms">
                  <span>Before #{{ item.pre_rerank_rank }}</span>
                  <span v-if="item.sources?.bm25">BM25 #{{ item.sources.bm25.rank }}</span>
                  <span v-if="item.sources?.vector">Vector #{{ item.sources.vector.rank }}</span>
                </div>
                <p>{{ item.content }}</p>
              </article>
            </section>

            <section class="trace-section">
              <h3>Vector Search</h3>
              <article v-for="item in latestTrace.vector_results" :key="item.chunk_id" class="trace-item">
                <div class="trace-item-head">
                  <strong>#{{ item.rank }} · {{ item.document }}</strong>
                  <small v-if="sourceLocation(item)" class="source-location">{{ sourceLocation(item) }}</small>
                  <span>{{ item.engine }} · {{ formatScore(item.score) }}</span>
                </div>
                <p>{{ item.content }}</p>
              </article>
            </section>

            <section class="trace-section compression-section">
              <h3>Context Compression</h3>
              <div class="trace-summary">
                <span>压缩前：{{ latestTrace.compression_stats?.original_tokens || 0 }} tokens</span>
                <span>压缩后：{{ latestTrace.compression_stats?.compressed_tokens || 0 }} tokens</span>
                <span>节省：{{ latestTrace.compression_stats?.saved_tokens || 0 }} tokens</span>
                <span>比例：{{ formatPercent(latestTrace.compression_stats?.saving_ratio) }}</span>
              </div>
              <article v-for="item in latestTrace.compression_results" :key="item.chunk_id" class="trace-item">
                <div class="trace-item-head">
                  <strong>#{{ item.rank }} · {{ item.document }}</strong>
                  <small v-if="sourceLocation(item)" class="source-location">{{ sourceLocation(item) }}</small>
                  <span>{{ item.original_tokens }} -> {{ item.compressed_tokens }} tokens</span>
                </div>
                <div class="compression-columns">
                  <div>
                    <h4>压缩前</h4>
                    <p>{{ item.original_content }}</p>
                  </div>
                  <div>
                    <h4>压缩后</h4>
                    <p>{{ item.content }}</p>
                  </div>
                </div>
                <el-collapse class="sentence-details">
                  <el-collapse-item title="保留 / 删除句子" name="sentences">
                  <div class="matched-terms">
                    <span v-for="sentence in item.kept_sentences" :key="sentence">保留：{{ sentence }}</span>
                  </div>
                  <div class="removed-sentences">
                    <p v-for="sentence in item.removed_sentences" :key="sentence">删除：{{ sentence }}</p>
                  </div>
                  </el-collapse-item>
                </el-collapse>
              </article>
            </section>

            <section class="trace-section">
              <h3>Context</h3>
              <pre>{{ latestTrace.compressed_context }}</pre>
            </section>

            <section class="trace-section">
              <h3>Final Prompt</h3>
              <pre>{{ latestTrace.final_prompt }}</pre>
            </section>
          </template>
        </div>
      </div>
    </el-collapse-item>
  </el-collapse>
</template>

<script setup>
defineProps({
  active: { type: Boolean, default: false },
  collapseValue: { type: Array, default: () => ['rag-debug'] },
  latestTrace: { type: Object, default: null },
  ragOptions: { type: Object, required: true },
  queryRewriteStrategies: { type: Array, default: () => [] },
  compressionStrategies: { type: Array, default: () => [] },
  currentRewriteDescription: { type: String, default: '' },
  currentCompressionDescription: { type: String, default: '' },
  formatScore: { type: Function, required: true },
  formatPercent: { type: Function, required: true },
})

function formatIntent(value) {
  const map = {
    internal_knowledge: '内部知识库问题',
    web_required: '需要联网/实时信息',
    unsupported: '无法处理的其它问题',
  }
  return map[value] || value || '-'
}

function formatRoute(value) {
  const map = {
    rag: '进入内部 RAG',
    reject_without_web_tool: '拒绝：未接入联网搜索',
    reject: '拒绝回答',
  }
  return map[value] || value || '-'
}

function formatSummaryStatus(value) {
  const map = {
    idle: '空闲',
    running: '生成中',
    failed: '失败',
    missing: '未创建',
  }
  return map[value] || value || '-'
}

function formatConversationContext(messages = []) {
  if (!Array.isArray(messages) || !messages.length) return '无'
  const roleMap = { user: '用户', assistant: '助手' }
  return messages.map((item) => `${roleMap[item.role] || item.role}：${item.content}`).join('\n')
}

function sourceLocation(item) {
  return item?.location?.label || ''
}

defineEmits(['update:collapse-value'])
</script>
