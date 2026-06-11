<template>
  <main>
    <section v-if="!store.access" class="auth">
      <div>
        <h1>AIAssistant</h1>
        <p>上传文档，比较五种切片方式，然后基于知识库提问。</p>
      </div>
      <form @submit.prevent="login">
        <input v-model="auth.username" placeholder="用户名" autocomplete="username" />
        <input v-model="auth.password" placeholder="密码" type="password" autocomplete="current-password" />
        <button type="submit">登录</button>
        <button type="button" class="ghost" @click="register">注册</button>
        <span class="error">{{ error }}</span>
      </form>
    </section>

    <section v-else class="shell">
      <aside>
        <div class="brand">
          <h2>AIAssistant</h2>
          <span>{{ store.user?.username }}</span>
        </div>

        <div class="panel">
          <h3>知识库</h3>
          <div class="inline">
            <input v-model="kbForm.name" placeholder="知识库名称" />
            <button type="button" @click="createKb">新建</button>
          </div>
          <button
            v-for="kb in kbs"
            :key="kb.id"
            class="list-item"
            :class="{ active: selectedKb?.id === kb.id }"
            @click="selectKb(kb)"
          >
            {{ kb.name }}
          </button>
        </div>

        <div class="panel">
          <h3>文档</h3>
          <input type="file" @change="upload" />
          <button
            v-for="doc in filteredDocuments"
            :key="doc.id"
            class="list-item"
            :class="{ active: selectedDocument?.id === doc.id }"
            @click="selectDocument(doc)"
          >
            <strong>{{ doc.filename }}</strong>
            <small>{{ doc.status }} · {{ doc.chunk_method }}</small>
          </button>
        </div>

        <button type="button" class="danger" :disabled="busy.reset" @click="resetWorkspace">


          {{ busy.reset ? '重置中' : '一键重置' }}


        </button>


        <button type="button" class="ghost" @click="logout">退出</button>
      </aside>

      <section class="workspace">
        <header>
          <div>
            <h1>调试工作台</h1>
            <p>先预览切片，再索引入库，最后在右侧对话栏提问。</p>
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
            <div class="workbench-tabs" role="tablist" aria-label="RAG workbench">
              <button
                v-for="tab in workbenchTabs"
                :key="tab.key"
                type="button"
                role="tab"
                :aria-selected="activeWorkbenchTab === tab.key"
                :class="{ active: activeWorkbenchTab === tab.key }"
                @click="activeWorkbenchTab = tab.key"
              >
                <strong>{{ tab.label }}</strong>
                <small>{{ tab.caption }}</small>
              </button>
            </div>
            <div class="workbench-context">
              <span>KB: {{ selectedKb?.name || '-' }}</span>
              <span>Docs: {{ filteredDocuments.length }}</span>
              <span>Chunks: {{ stats.chunk_count || selectedDocument?.chunk_count || 0 }}</span>
              <span>Eval Runs: {{ evalRuns.length }}</span>
              <span>Model Calls: {{ modelUsage?.totals?.call_count || 0 }}</span>
            </div>
            <details v-show="activeWorkbenchTab === 'debug'" class="debug-section" open>
              <summary><span>切片实验室</span><small>文档切片、预览与索引</small></summary>
              <div class="debug-section-body">
            <div class="toolbar">
              <label>
                切片方式
                <select v-model="chunkForm.chunk_method" @change="preview">
                  <option v-for="method in chunkMethods" :key="method.value" :value="method.value">
                    {{ method.label }}
                  </option>
                </select>
              </label>
              <label>
                chunk size
                <input v-model.number="chunkForm.options.chunk_size" type="number" min="100" />
              </label>
              <label>
                overlap
                <input v-model.number="chunkForm.options.chunk_overlap" type="number" min="0" />
              </label>
              <label>
                window
                <input v-model.number="chunkForm.options.window_size" type="number" min="1" />
              </label>
              <button type="button" @click="preview" :disabled="!selectedDocument || busy.preview">预览</button>
              <button type="button" @click="indexDoc" :disabled="!selectedDocument || busy.index">
                {{ busy.index ? '索引中' : '索引' }}
              </button>
            </div>

            <p v-if="notice" class="notice">{{ notice }}</p>
            <p v-if="actionError" class="error">{{ actionError }}</p>

            <div class="metrics">
              <span>Chunks: {{ stats.chunk_count || 0 }}</span>
              <span>Avg Tokens: {{ stats.avg_tokens || 0 }}</span>
              <span>Max Tokens: {{ stats.max_tokens || 0 }}</span>
            </div>

            <div class="chunks">
              <article v-for="chunk in chunks" :key="chunk.index" class="chunk">
                <div class="chunk-head">
                  <strong>#{{ chunk.index + 1 }}</strong>
                  <span>{{ chunk.token_count }} tokens</span>
                </div>
                <p>{{ chunk.content }}</p>
              </article>
            </div>

              </div>
            </details>

            <details v-show="activeWorkbenchTab === 'debug'" class="debug-section" open>
              <summary><span>RAG 检索调试</span><small>向量召回、上下文与最终 Prompt</small></summary>
              <div class="debug-section-body">
            <div class="trace-panel">
              <div class="trace-title">
                <h3>RAG 检索调试</h3>
                <span v-if="latestTrace">Trace #{{ latestTrace.id }}</span>
              </div>
              <div class="rag-options">
                <label>
                  Query Rewrite
                  <select v-model="ragOptions.query_rewrite_strategy">
                    <option v-for="option in queryRewriteStrategies" :key="option.value" :value="option.value">
                      {{ option.label }}
                    </option>
                  </select>
                </label>
                <label>
                  Vector top_k
                  <input v-model.number="ragOptions.top_k" type="number" min="1" max="20" />
                </label>
                <label>
                  BM25 top_k
                  <input v-model.number="ragOptions.bm25_top_k" type="number" min="1" max="20" />
                </label>
                <label>
                  RRF_K
                  <input v-model.number="ragOptions.rrf_k" type="number" min="1" max="500" />
                </label>
                <label>
                  Rerank top_n
                  <input v-model.number="ragOptions.rerank_top_n" type="number" min="1" max="20" />
                </label>
                <label>
                  Context Compression
                  <select v-model="ragOptions.compression_strategy">
                    <option v-for="option in compressionStrategies" :key="option.value" :value="option.value">
                      {{ option.label }}
                    </option>
                  </select>
                </label>
                <span>{{ currentRewriteDescription }} · {{ currentCompressionDescription }}</span>
              </div>
              <div v-if="!latestTrace" class="empty-state">发送一个问题后，这里会展示本次向量召回、上下文和最终 Prompt。</div>
              <template v-else>
                <div class="trace-summary">
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
                      <span>{{ item.original_tokens }} → {{ item.compressed_tokens }} tokens</span>
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
                    <details class="sentence-details">
                      <summary>保留 / 删除句子</summary>
                      <div class="matched-terms">
                        <span v-for="sentence in item.kept_sentences" :key="sentence">保留：{{ sentence }}</span>
                      </div>
                      <div class="removed-sentences">
                        <p v-for="sentence in item.removed_sentences" :key="sentence">删除：{{ sentence }}</p>
                      </div>
                    </details>
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
            </details>


            <details v-show="activeWorkbenchTab === 'costs'" class="debug-section" open>
              <summary><span>模型与成本监控</span><small>Token、成本、慢请求、失败请求与 Trace 成本</small></summary>
              <div class="debug-section-body">
                <div class="trace-history-toolbar">
                  <button type="button" @click="loadModelUsage" :disabled="!selectedKb">刷新</button>
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
                    <div v-else class="cost-table">
                      <div class="cost-row head"><strong>模型</strong><span>类型</span><span>调用</span><span>Token</span><span>成本</span><span>占比</span></div>
                      <div v-for="item in modelUsage.by_model" :key="`${item.model}-${item.call_type}`" class="cost-row">
                        <strong>{{ item.model }}</strong>
                        <span>{{ item.call_type }}</span>
                        <span>{{ item.call_count }}</span>
                        <span>{{ item.total_tokens || 0 }}</span>
                        <span>{{ formatCost(item.estimated_cost) }}</span>
                        <span>{{ formatCostShare(item.estimated_cost, modelUsage.totals.estimated_cost) }}</span>
                      </div>
                    </div>
                  </section>

                  <section class="trace-section">
                    <h3>单次 Trace 成本</h3>
                    <div v-if="!modelUsage.trace_costs?.length" class="empty-state">暂无已关联 Trace 的模型调用。</div>
                    <div v-else class="cost-table">
                      <div class="cost-row head"><strong>Trace</strong><span>调用</span><span>Token</span><span>成本</span><span>问题</span></div>
                      <div v-for="item in modelUsage.trace_costs" :key="item.trace" class="cost-row trace-cost">
                        <strong>#{{ item.trace }}</strong>
                        <span>{{ item.call_count }}</span>
                        <span>{{ item.total_tokens || 0 }}</span>
                        <span>{{ formatCost(item.estimated_cost) }}</span>
                        <span>{{ compactText(item.trace__question, 56) }}</span>
                      </div>
                    </div>
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
            </details>

            <details v-show="activeWorkbenchTab === 'history'" class="debug-section">
              <summary><span>历史调试记录</span><small>保存、查看与对比 RAG Trace</small></summary>
              <div class="debug-section-body">
                <div class="trace-history-toolbar">
                  <input v-model="traceSearch" placeholder="按问题搜索 Trace" @keyup.enter="loadTraceHistory" />
                  <button type="button" @click="loadTraceHistory" :disabled="!selectedKb">刷新</button>
                  <button type="button" class="ghost" @click="clearTraceCompare" :disabled="!selectedTraceIds.length">清空对比</button>
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
                      <button type="button" class="ghost" @click="openTrace(trace)">查看</button>
                      <button type="button" @click="toggleTraceCompare(trace)">
                        {{ selectedTraceIds.includes(trace.id) ? '取消' : '对比' }}
                      </button>
                    </div>
                  </article>
                </div>

                <section v-if="latestTrace" class="trace-history-detail">
                  <div class="trace-title">
                    <h3>Trace #{{ latestTrace.id }} 详情</h3>
                    <span>{{ formatDate(latestTrace.created_at) }}</span>
                  
                    <button type="button" class="ghost" @click="createCaseFromTrace(latestTrace)">To Regression</button></div>
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
                  <details class="sentence-details">
                    <summary>查看压缩后 Context</summary>
                    <pre>{{ latestTrace.compressed_context }}</pre>
                  </details>
                  <details class="sentence-details">
                    <summary>查看 Final Prompt</summary>
                    <pre>{{ latestTrace.final_prompt }}</pre>
                  </details>
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
                    <div><strong>Vector Top5</strong><span>{{ traceComparison.vectorOrder.left.join(' → ') || '-' }}</span><span>{{ traceComparison.vectorOrder.right.join(' → ') || '-' }}</span></div>
                    <div><strong>BM25 Top5</strong><span>{{ traceComparison.bm25Order.left.join(' → ') || '-' }}</span><span>{{ traceComparison.bm25Order.right.join(' → ') || '-' }}</span></div>
                    <div><strong>Hybrid Top5</strong><span>{{ traceComparison.hybridOrder.left.join(' → ') || '-' }}</span><span>{{ traceComparison.hybridOrder.right.join(' → ') || '-' }}</span></div>
                    <div><strong>Rerank Top5</strong><span>{{ traceComparison.rerankOrder.left.join(' → ') || '-' }}</span><span>{{ traceComparison.rerankOrder.right.join(' → ') || '-' }}</span></div>
                    <div><strong>压缩后 tokens</strong><span>{{ traceComparison.compressionTokens.left }}</span><span>{{ traceComparison.compressionTokens.right }} ({{ traceComparison.compressionTokens.delta >= 0 ? '+' : '' }}{{ traceComparison.compressionTokens.delta }})</span></div>
                    <div><strong>节省比例</strong><span>{{ formatPercent(traceComparison.savingRatio.left) }}</span><span>{{ formatPercent(traceComparison.savingRatio.right) }}</span></div>
                    <div><strong>上下文长度</strong><span>{{ traceComparison.contextLength.left }}</span><span>{{ traceComparison.contextLength.right }} ({{ traceComparison.contextLength.delta >= 0 ? '+' : '' }}{{ traceComparison.contextLength.delta }})</span></div>
                    <div><strong>答案长度</strong><span>{{ traceComparison.answerLength.left }}</span><span>{{ traceComparison.answerLength.right }} ({{ traceComparison.answerLength.delta >= 0 ? '+' : '' }}{{ traceComparison.answerLength.delta }})</span></div>
                  </div>

                  <details class="sentence-details">
                    <summary>参数差异 {{ traceComparison.settingsChanged.length }} 项</summary>
                    <div v-if="!traceComparison.settingsChanged.length" class="empty-state">两条 Trace 的参数一致。</div>
                    <div v-else class="settings-diff">
                      <div v-for="item in traceComparison.settingsChanged" :key="item.key">
                        <strong>{{ item.key }}</strong>
                        <span>{{ item.left }}</span>
                        <span>{{ item.right }}</span>
                      </div>
                    </div>
                  </details>
                </section>
              </div>
            </details>

            <details v-show="activeWorkbenchTab === 'datasets'" class="debug-section">
              <summary><span>评测基准</span><small>维护 Golden Set 与标准答案</small></summary>
              <div class="debug-section-body">
                <div class="trace-history-toolbar">
                  <select v-model="selectedDatasetSuite" @change="loadBenchmarkCases">
                    <option value="">All suites</option>
                    <option v-for="suite in evalSuites" :key="suite.value" :value="suite.value">{{ suite.label }}</option>
                  </select>
                  <button type="button" @click="importDefaultBenchmarkCases" :disabled="!selectedKb">导入默认样例</button>
                  <button type="button" class="ghost" @click="loadBenchmarkCases" :disabled="!selectedKb">刷新</button>
                  <span class="muted">领域专家维护的回归评测集。运行评测时优先使用启用的基准；没有基准才回退到 JSON 样例。</span>
                </div>

                <form class="benchmark-form" @submit.prevent="createBenchmarkCase">
                  <input v-model="benchmarkForm.case_id" placeholder="case_id，例如 publish_stage_tools" />
                  <input v-model="benchmarkForm.question" placeholder="评测问题" />
                  <textarea v-model="benchmarkForm.reference" placeholder="标准答案 reference"></textarea>
                  <input v-model="benchmarkForm.tagsText" placeholder="标签，用逗号分隔" />
                  <input v-model="benchmarkForm.expectedTermsText" placeholder="expected_terms, comma separated" />
                  <input v-model="benchmarkForm.targetChunkIdsText" placeholder="target_chunk_ids, comma separated" />
                  <select v-model="benchmarkForm.suite">
                    <option v-for="suite in evalSuites" :key="suite.value" :value="suite.value">{{ suite.label }}</option>
                  </select>
                  <select v-model="benchmarkForm.source">
                    <option v-for="source in caseSources" :key="source.value" :value="source.value">{{ source.label }}</option>
                  </select>
                  <textarea v-model="benchmarkForm.notes" placeholder="notes: why this case exists, failure history, owner..." />
                  <select v-model="benchmarkForm.difficulty">
                    <option value="easy">easy</option>
                    <option value="medium">medium</option>
                    <option value="hard">hard</option>
                  </select>
                  <label class="check-row">
                    <input v-model="benchmarkForm.enabled" type="checkbox" />
                    启用
                  </label>
                  <button type="submit" :disabled="!selectedKb">新增基准</button>
                </form>

                <div v-if="!benchmarkCases.length" class="empty-state">暂无评测基准。可以先导入默认样例，或由领域专家新增标准问题。</div>
                <div v-else class="benchmark-list">
                  <article v-for="item in benchmarkCases" :key="item.id" class="benchmark-item" :class="{ disabled: !item.enabled }">
                    <div class="trace-history-main">
                      <strong>{{ item.question }}</strong>
                      <small>{{ item.case_id }} · {{ item.difficulty }} · {{ (item.tags || []).join(', ') || '-' }}</small>
                      <p>{{ item.reference }}</p>
                    </div>
                    <div class="trace-history-actions">
                      <button type="button" class="ghost" @click="toggleBenchmarkCase(item)">
                        {{ item.enabled ? '禁用' : '启用' }}
                      </button>
                      <button type="button" class="danger" @click="deleteBenchmarkCase(item)">删除</button>
                    </div>
                  </article>
                </div>
              </div>
            </details>

            <details v-show="activeWorkbenchTab === 'evaluation'" class="debug-section">
              <summary><span>评测报告</span><small>运行并查看 RAGAS 评测结果</small></summary>
              <div class="debug-section-body">
                <div class="trace-history-toolbar">
                  <select v-model="selectedEvalSuite">
                    <option value="">All suites</option>
                    <option v-for="suite in evalSuites" :key="suite.value" :value="suite.value">{{ suite.label }}</option>
                  </select>
                  <button type="button" class="eval-run-button" @click="runEval" :disabled="!selectedKb || isEvalRunning">
                    {{ isEvalRunning ? '评测中' : '运行评测' }}
                  </button>
                  <button type="button" class="ghost" @click="loadEvalRuns" :disabled="!selectedKb">刷新</button>
                  <span class="muted">使用当前调试参数运行 RAGAS，完成后会自动保存并展示报告。</span>
                </div>

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
                      <small>{{ formatDate(run.created_at) }} · {{ run.kb_name || selectedKb?.name }}</small>
                      <div class="eval-score-row">
                        <span v-for="metric in run.metrics" :key="metric">
                          {{ metricLabel(metric) }} {{ formatEvalScore(run.mean_scores?.[metric]) }}
                        </span>
                      </div>
                    </div>
                    <div class="trace-history-actions">
                      <button type="button" class="ghost" @click="openEvalRun(run)">查看</button>
                      <button type="button" @click="toggleEvalRunCompare(run)">
                        {{ selectedEvalRunIds.includes(run.id) ? '取消' : '对比' }}
                      </button>
                    </div>
                  </article>
                </div>

                <section v-if="evalRunComparison" class="eval-compare">
                  <div class="trace-title">
                    <h3>评测 Run 对比</h3>
                    <span>#{{ selectedEvalRuns[0].id }} ↔ #{{ selectedEvalRuns[1].id }}</span>
                  </div>
                  <div class="eval-score-grid">
                    <div v-for="item in evalRunComparison.metricDeltas" :key="item.metric">
                      <strong>{{ metricLabel(item.metric) }}</strong>
                      <span>{{ formatEvalScore(item.right) }}</span>
                      <small>
                        {{ formatEvalScore(item.left) }} → {{ formatEvalScore(item.right) }}
                        <b :class="scoreDeltaClass(item.delta)">
                          {{ formatSignedScore(item.delta) }}
                        </b>
                      </small>
                    </div>
                  </div>

                  <details class="sentence-details" open>
                    <summary>参数差异 {{ evalRunComparison.settingsChanged.length }} 项</summary>
                    <div v-if="!evalRunComparison.settingsChanged.length" class="empty-state">两次评测的参数一致。</div>
                    <div v-else class="settings-diff">
                      <div v-for="item in evalRunComparison.settingsChanged" :key="item.key">
                        <strong>{{ item.key }}</strong>
                        <span>{{ item.left }}</span>
                        <span>{{ item.right }}</span>
                      </div>
                    </div>
                  </details>

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
                    <span>{{ selectedEvalRun.status }} · {{ formatDate(selectedEvalRun.finished_at || selectedEvalRun.created_at) }}</span>
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
                      <small>Recall@K {{ formatEvalScore(item.recall_at_k) }} ? MRR {{ formatEvalScore(item.mrr) }} ? target {{ item.target_case_count }}</small>
                    </div>
                  </div>
                  <div class="trace-summary">
                    <span>Query Rewrite：{{ selectedEvalRun.settings?.query_rewrite_strategy || '-' }}</span>
                    <span>Vector top_k：{{ selectedEvalRun.settings?.top_k || '-' }}</span>
                    <span>BM25 top_k：{{ selectedEvalRun.settings?.bm25_top_k || '-' }}</span>
                    <span>RRF_K：{{ selectedEvalRun.settings?.rrf_k || '-' }}</span>
                    <span>Rerank top_n：{{ selectedEvalRun.settings?.rerank_top_n || '-' }}</span>
                    <span>Compression：{{ selectedEvalRun.settings?.compression_strategy || '-' }}</span>
                  </div>

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
                            @click="scrollToEvalCase(caseItem.id)"
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
                    <details class="sentence-details">
                      <summary>查看 Context / Top Chunks</summary>
                      <div class="trace-summary">
                        <span>BM25：{{ item.top_chunks?.bm25?.join(' → ') || '-' }}</span>
                        <span>Vector：{{ item.top_chunks?.vector?.join(' → ') || '-' }}</span>
                        <span>Hybrid：{{ item.top_chunks?.hybrid?.join(' → ') || '-' }}</span>
                        <span>Rerank：{{ item.top_chunks?.rerank?.join(' → ') || '-' }}</span>
                      </div>
                      <pre>{{ (item.contexts || []).join('\n\n---\n\n') }}</pre>
                    </details>
                  </article>
                </section>
              </div>
            </details>
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

          <section class="card chat">
            <div class="chat-head">
              <h2>RAG 对话</h2>
              <button type="button" @click="newSession" :disabled="!selectedKb">新会话</button>
            </div>
            <div class="messages">
              <article v-for="message in messages" :key="message.id" :class="['message', message.role]">
                <p class="message-content">
                  <template v-for="(part, partIndex) in renderMessageParts(message)" :key="`${message.id}-part-${partIndex}`">
                    <button
                      v-if="part.type === 'citation'"
                      type="button"
                      class="citation-link"
                      title="Highlight source"
                      @click="highlightCitation(message, part.number)"
                    >[{{ part.number }}]</button>
                    <span v-else>{{ part.text }}</span>
                  </template>
                </p>
                <details
                  v-if="message.sources?.length"
                  :open="isSourcePanelOpen(message)"
                  @toggle="setSourcePanelOpen(message, $event.target.open)"
                >
                  <summary>引用来源</summary>
                  <div
                    v-for="(source, sourceIndex) in message.sources"
                    :key="source.chunk_id || sourceIndex"
                    :class="['source', { active: isSourceHighlighted(message, source, sourceIndex) }]"
                  >
                    <strong><span class="source-citation">[{{ sourceCitationNumber(source, sourceIndex) }}]</span> {{ source.document }}</strong>
                    <span>{{ Number(source.score).toFixed(3) }}</span>
                    <p>{{ source.content }}</p>
                  </div>
                </details>
              </article>
            </div>
            <form class="ask" @submit.prevent="ask">
              <textarea v-model="question" placeholder="基于已索引文档提问"></textarea>
              <button :disabled="!selectedKb || loading || !question.trim()">{{ loading ? '回答中' : '发送' }}</button>
            </form>
          </section>
        </div>
      </section>
    </section>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from './api'
import { store } from './main'

const auth = reactive({ username: 'admin', password: 'admin123' })
const error = ref('')
const kbs = ref([])
const documents = ref([])
const chunkMethods = ref([])
const selectedKb = ref(null)
const selectedDocument = ref(null)
const chunks = ref([])
const stats = reactive({})
const messages = ref([])
const session = ref(null)
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
const benchmarkCases = ref([])
const selectedDatasetSuite = ref('')
const selectedEvalSuite = ref('')
const activeWorkbenchTab = ref('debug')
const modelUsage = ref(null)
const pollingEvalRunIds = ref(new Set())
const splitterContainer = ref(null)
const labWidthPercent = ref(Number(localStorage.getItem('labWidthPercent')) || 62)
const isResizing = ref(false)
const highlightedSourceRefs = reactive({})
const openSourcePanels = reactive({})
const busy = reactive({ preview: false, index: false, upload: false, reset: false, eval: false })
const workbenchTabs = [
  { key: 'debug', label: 'Debug', caption: 'Chunking & Retrieval' },
  { key: 'evaluation', label: 'Evaluation', caption: 'Runs & Metrics' },
  { key: 'datasets', label: 'Datasets', caption: 'Benchmark Cases' },
  { key: 'history', label: 'History', caption: 'Trace Review' },
  { key: 'costs', label: 'Costs', caption: 'Models & Tokens' },
]
const evalSuites = [
  { value: 'smoke', label: 'Smoke' },
  { value: 'benchmark', label: 'Benchmark' },
  { value: 'regression', label: 'Regression' },
  { value: 'release', label: 'Release' },
]
const caseSources = [
  { value: 'expert', label: 'Expert' },
  { value: 'trace', label: 'Trace' },
  { value: 'eval_failure', label: 'Eval Failure' },
  { value: 'user_feedback', label: 'User Feedback' },
  { value: 'default_json', label: 'Default JSON' },
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
const benchmarkForm = reactive({
  case_id: '',
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


function messageSourceKey(message) {
  return String(message?.id || '')
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
  if (!left.case_results || !right.case_results) return null
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

function diffSettings(left, right) {
  const keys = Array.from(new Set([...Object.keys(left), ...Object.keys(right)])).sort()
  return keys
    .filter((key) => JSON.stringify(left[key]) !== JSON.stringify(right[key]))
    .map((key) => ({ key, left: left[key], right: right[key] }))
}



async function loadModelUsage() {
  if (!selectedKb.value) {
    modelUsage.value = null
    return
  }
  modelUsage.value = await api.getModelUsageSummary({ kb: selectedKb.value.id })
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
  evalRuns.value = await api.listEvalRuns({ kb: selectedKb.value.id })
  if (selectedEvalRun.value && !evalRuns.value.some((run) => run.id === selectedEvalRun.value.id)) {
    selectedEvalRun.value = null
  }
  selectedEvalRunIds.value = selectedEvalRunIds.value.filter((id) => evalRuns.value.some((run) => run.id === id))
  const runningRun = evalRuns.value.find((run) => run.status === 'running')
  if (runningRun) {
    startEvalPolling(runningRun.id)
  }
}

async function loadBenchmarkCases() {
  if (!selectedKb.value) {
    benchmarkCases.value = []
    return
  }
  benchmarkCases.value = await api.listBenchmarkCases({ kb: selectedKb.value.id, suite: selectedDatasetSuite.value })
}

function resetBenchmarkForm() {
  benchmarkForm.case_id = ''
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
}

async function createBenchmarkCase() {
  if (!selectedKb.value) return
  await runAction(async () => {
    const created = await api.createBenchmarkCase({
      kb: selectedKb.value.id,
      case_id: benchmarkForm.case_id,
      question: benchmarkForm.question,
      reference: benchmarkForm.reference,
      tags: benchmarkForm.tagsText,
      expected_terms: benchmarkForm.expectedTermsText,
      target_chunk_ids: benchmarkForm.targetChunkIdsText,
      suite: benchmarkForm.suite,
      source: benchmarkForm.source,
      notes: benchmarkForm.notes,
      difficulty: benchmarkForm.difficulty,
      enabled: benchmarkForm.enabled,
    })
    benchmarkCases.value = [...benchmarkCases.value, created].sort((left, right) => left.case_id.localeCompare(right.case_id))
    resetBenchmarkForm()
    notice.value = `已新增评测基准：${created.case_id}`
  })
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
  await runAction(async () => {
    const result = await api.importDefaultBenchmarkCases(selectedKb.value.id)
    benchmarkCases.value = result.cases
    notice.value = `已导入默认评测基准：新增 ${result.created} 条，更新 ${result.updated} 条`
  })
}

async function toggleBenchmarkCase(item) {
  const updated = await api.updateBenchmarkCase(item.id, { enabled: !item.enabled })
  benchmarkCases.value = benchmarkCases.value.map((caseItem) => (caseItem.id === updated.id ? updated : caseItem))
}

async function deleteBenchmarkCase(item) {
  const confirmed = window.confirm(`确认删除评测基准 ${item.case_id}？`)
  if (!confirmed) return
  await api.deleteBenchmarkCase(item.id)
  benchmarkCases.value = benchmarkCases.value.filter((caseItem) => caseItem.id !== item.id)
}

async function openEvalRun(run) {
  const detail = run.case_results ? run : await api.getEvalRun(run.id)
  selectedEvalRun.value = detail
  evalRuns.value = evalRuns.value.map((item) => (item.id === detail.id ? detail : item))
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

async function login() {
  error.value = ''
  try {
    const token = await api.login(auth.username, auth.password)
    store.access = token.access
    store.refresh = token.refresh
    localStorage.setItem('access', token.access)
    localStorage.setItem('refresh', token.refresh)
    await bootstrap()
  } catch (err) {
    error.value = err.message
  }
}

async function register() {
  error.value = ''
  try {
    await api.register(auth.username, auth.password)
    await login()
  } catch (err) {
    error.value = err.message
  }
}

function logout() {
  store.access = ''
  store.refresh = ''
  localStorage.clear()
}

async function resetWorkspace() {
  const firstConfirm = window.confirm('确认要重置当前账号的所有知识库、文档、切片、会话和聊天记录吗？')
  if (!firstConfirm) return
  const secondConfirm = window.confirm('此操作会同时删除 Milvus 向量索引和已上传文件，且不可恢复。再次确认重置？')
  if (!secondConfirm) return

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
  latestTrace.value = null
  selectedTraceIds.value = []
  evalRuns.value = []
  selectedEvalRun.value = null
  selectedEvalRunIds.value = []
  benchmarkCases.value = []
  loadTraceHistory()
  loadEvalRuns()
  loadBenchmarkCases()
  loadModelUsage()
}

function selectDocument(doc) {
  selectedDocument.value = doc
  chunks.value = []
  Object.keys(stats).forEach((key) => delete stats[key])
}

async function upload(event) {
  const file = event.target.files?.[0]
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

async function newSession() {
  session.value = await api.createSession({ kb: selectedKb.value.id, title: 'RAG 问答' })
  messages.value = []
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

onMounted(async () => {
  if (store.access) {
    try {
      await bootstrap()
    } catch {
      logout()
    }
  }
})

onBeforeUnmount(() => {
  stopResize()
})
</script>
