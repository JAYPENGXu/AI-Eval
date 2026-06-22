<template>
  <el-collapse v-show="active" :model-value="collapseValue" class="debug-section" @update:model-value="$emit('update:collapse-value', $event)">
    <el-collapse-item name="datasets">
      <template #title>
        <span>专家评测集</span>
        <small>（Eval Case 模板维护）</small>
      </template>

      <div class="debug-section-body datasets-panel">
        <section class="dataset-guide">
          <div>
            <h3>专家维护的 Eval Case 模板</h3>
            <p>每条用例同时描述用户问题、证据、硬性 deterministic 检查、Rubric 评分标准和通过阈值。运行评测时，系统会按 suite 过滤并保存每项硬性检查的通过/失败明细。</p>
          </div>
          <div class="dataset-guide-steps">
            <span>基础信息</span>
            <span>证据</span>
            <span>硬性检查</span>
            <span>阈值</span>
          </div>
        </section>

        <div class="trace-history-toolbar">
          <el-select :model-value="selectedSuite" placeholder="全部 Suite" clearable style="width: 160px" @change="updateSuite">
            <el-option label="全部 Suite" value="" />
            <el-option v-for="suite in evalSuites" :key="suite.value" :label="suiteLabel(suite.value, suite.label)" :value="suite.value" />
          </el-select>
          <el-button type="primary" plain @click="$emit('import-defaults')" :disabled="!selectedKb" :loading="busy.datasetImport">导入默认样例</el-button>
          <el-button plain @click="$emit('refresh')" :disabled="!selectedKb" :loading="busy.datasetRefresh">刷新</el-button>
          <span class="muted">这里面向专家维护，不做普通表单降噪。</span>
        </div>

        <el-form class="benchmark-form benchmark-form-cn" label-position="top" @submit.prevent="$emit('create-case')">
          <section class="form-section form-section-required">
            <header class="form-section-head"><h3>基础信息</h3></header>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>用例编号</span><span class="field-required">必填</span></span>
              <el-input v-model="benchmarkForm.case_id" placeholder="例如 ragops_router_internal_001" />
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>Case 类型</span></span>
              <el-select v-model="benchmarkForm.case_type" style="width: 100%">
                <el-option label="专家模板" value="expert" />
                <el-option label="回归用例" value="regression" />
                <el-option label="冒烟用例" value="smoke" />
                <el-option label="发布门禁" value="release_gate" />
              </el-select>
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>Suite</span></span>
              <el-select v-model="benchmarkForm.suite" style="width: 100%">
                <el-option v-for="suite in evalSuites" :key="suite.value" :label="suiteLabel(suite.value, suite.label)" :value="suite.value" />
              </el-select>
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>难度</span></span>
              <el-select v-model="benchmarkForm.difficulty" style="width: 100%">
                <el-option label="简单" value="easy" />
                <el-option label="中等" value="medium" />
                <el-option label="困难" value="hard" />
              </el-select>
            </el-form-item>
            <el-form-item class="field-block wide">
              <span class="field-label-with-tip"><span>评测问题</span><span class="field-required">必填</span></span>
              <el-input v-model="benchmarkForm.question" type="textarea" :rows="2" placeholder="专家定义的用户问题" />
            </el-form-item>
          </section>

          <section class="form-section">
            <header class="form-section-head"><h3>标准答案与证据</h3></header>
            <el-form-item class="field-block wide">
              <span class="field-label-with-tip"><span>标准答案</span><span class="field-required">必填</span></span>
              <el-input v-model="benchmarkForm.reference" type="textarea" :rows="4" placeholder="领域专家认可的参考答案" />
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>期望术语</span></span>
              <el-input v-model="benchmarkForm.expectedTermsText" placeholder="多个术语用逗号或换行分隔" />
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>目标 Chunk ID</span></span>
              <el-input v-model="benchmarkForm.targetChunkIdsText" placeholder="例如 47,48" />
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>标签</span></span>
              <el-input v-model="benchmarkForm.tagsText" placeholder="多个标签用逗号分隔" />
            </el-form-item>
          </section>

          <section class="form-section">
            <header class="form-section-head"><h3>确定性检查</h3></header>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>Router Intent</span></span>
              <el-select v-model="benchmarkForm.routerIntent" clearable style="width: 100%">
                <el-option label="internal_knowledge" value="internal_knowledge" />
                <el-option label="web_required" value="web_required" />
                <el-option label="unsupported" value="unsupported" />
              </el-select>
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>Rewrite 包含</span></span>
              <el-input v-model="benchmarkForm.rewriteContainsText" placeholder="术语列表" />
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>Answer 必须包含</span></span>
              <el-input v-model="benchmarkForm.answerContainsText" placeholder="术语列表" />
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>Answer 禁止包含</span></span>
              <el-input v-model="benchmarkForm.answerNotContainsText" placeholder="术语列表" />
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>阶段命中要求</span></span>
              <div class="check-grid">
                <el-checkbox v-model="benchmarkForm.citationRequired">Citation Required</el-checkbox>
                <el-checkbox v-model="benchmarkForm.vectorHit">Vector Hit</el-checkbox>
                <el-checkbox v-model="benchmarkForm.bm25Hit">BM25 Hit</el-checkbox>
                <el-checkbox v-model="benchmarkForm.hybridHit">Hybrid Hit</el-checkbox>
                <el-checkbox v-model="benchmarkForm.rerankKeep">Rerank Keep</el-checkbox>
              </div>
            </el-form-item>
            <el-form-item class="field-block wide">
              <span class="field-label-with-tip"><span>Compression 保留术语</span></span>
              <el-input v-model="benchmarkForm.compressionKeepTermsText" placeholder="留空时可由 expected_terms 承担" />
            </el-form-item>
          </section>

          <section class="form-section">
            <header class="form-section-head"><h3>Rubric 评分</h3></header>
            <el-form-item class="field-block wide">
              <span class="field-label-with-tip"><span>Rubric JSON</span></span>
              <el-input v-model="benchmarkForm.rubricText" type="textarea" :rows="5" placeholder='例如 {"dimensions":[{"name":"事实正确性","weight":0.5}]}' />
            </el-form-item>
          </section>

          <section class="form-section form-section-compact">
            <header class="form-section-head"><h3>通过阈值</h3></header>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>Deterministic 最低通过率</span></span>
              <el-input-number v-model="benchmarkForm.deterministicMinPassRate" :min="0" :max="1" :step="0.05" controls-position="right" style="width: 100%" />
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>Judge 正确性阈值</span></span>
              <el-input-number v-model="benchmarkForm.minCorrectnessScore" :min="0" :max="1" :step="0.05" controls-position="right" style="width: 100%" />
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>Judge 引用阈值</span></span>
              <el-input-number v-model="benchmarkForm.minCitationScore" :min="0" :max="1" :step="0.05" controls-position="right" style="width: 100%" />
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>最大幻觉风险</span></span>
              <el-input-number v-model="benchmarkForm.maxHallucinationRisk" :min="0" :max="1" :step="0.05" controls-position="right" style="width: 100%" />
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>最大总 Token</span></span>
              <el-input-number v-model="benchmarkForm.maxTotalTokens" :min="0" :step="100" controls-position="right" style="width: 100%" />
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>最大延迟 ms</span></span>
              <el-input-number v-model="benchmarkForm.maxLatencyMs" :min="0" :step="500" controls-position="right" style="width: 100%" />
            </el-form-item>
            <el-form-item class="field-block">
              <span class="field-label-with-tip"><span>来源</span></span>
              <el-select v-model="benchmarkForm.source" style="width: 100%">
                <el-option v-for="source in caseSources" :key="source.value" :label="sourceLabel(source.value, source.label)" :value="source.value" />
              </el-select>
            </el-form-item>
            <el-form-item class="field-block wide">
              <span class="field-label-with-tip"><span>维护说明</span></span>
              <el-input v-model="benchmarkForm.notes" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item class="field-block"><div class="switch-line"><el-switch v-model="benchmarkForm.enabled" active-text="启用" inactive-text="停用" /></div></el-form-item>
          </section>

          <div class="benchmark-form-actions">
            <el-button type="primary" native-type="submit" :disabled="!selectedKb" :loading="busy.datasetCreate">新增 Eval Case</el-button>
          </div>
        </el-form>

        <div v-if="!benchmarkCases.length" class="empty-state">暂无 Eval Case。可以先导入默认样例，或由专家新增模板。</div>
        <div v-else class="benchmark-list">
          <article v-for="item in benchmarkCases" :key="item.id" class="benchmark-item" :class="{ disabled: !item.enabled }">
            <div class="trace-history-main">
              <strong>{{ item.question }}</strong>
              <small>{{ item.case_id }} · {{ item.case_type || 'expert' }} · {{ difficultyLabel(item.difficulty) }} · {{ suiteLabel(item.suite) }} · {{ (item.tags || []).join(', ') || '-' }}</small>
              <p>{{ item.reference }}</p>
              <small v-if="item.expected_terms?.length">期望术语：{{ item.expected_terms.join(', ') }}</small>
              <small v-if="item.target_chunk_ids?.length">目标 Chunk：{{ item.target_chunk_ids.join(', ') }}</small>
              <small v-if="deterministicKeys(item).length">硬性检查：{{ deterministicKeys(item).join(', ') }}</small>
            </div>
            <div class="trace-history-actions">
              <el-button @click="$emit('toggle-case', item)" :loading="busy.datasetAction === item.id">{{ item.enabled ? '停用' : '启用' }}</el-button>
              <el-button type="danger" @click="$emit('delete-case', item)" :loading="busy.datasetAction === `delete-${item.id}`">删除</el-button>
            </div>
          </article>
        </div>
        <section class="parse-eval-maintenance">
          <header class="form-section-head">
            <div>
              <h3>文档解析评测集</h3>
              <p>维护页级结构、OCR 识别与解析质量的确定性验收样例。</p>
            </div>
            <span class="muted">TXT / Markdown / DOCX / PDF</span>
          </header>

          <el-form class="parse-case-form" label-position="top" @submit.prevent="$emit('create-parse-case')">
            <el-form-item label="Case ID">
              <el-input v-model="parseCaseForm.case_id" placeholder="例如 parse_markdown_001" />
            </el-form-item>
            <el-form-item label="标题">
              <el-input v-model="parseCaseForm.title" placeholder="样例用途或文档类型" />
            </el-form-item>
            <el-form-item label="Suite">
              <el-select v-model="parseCaseForm.suite">
                <el-option v-for="suite in evalSuites" :key="suite.value" :label="suite.label" :value="suite.value" />
              </el-select>
            </el-form-item>

            <el-form-item label="评测文档">
              <el-upload
                :auto-upload="false"
                :limit="1"
                accept=".txt,.md,.markdown,.docx,.pdf"
                @change="$emit('select-parse-file', $event.raw)"
              >
                <el-button>选择文档</el-button>
              </el-upload>
            </el-form-item>
            <el-form-item label="期望页数">
              <el-input-number v-model="parseCaseForm.expected_page_count" :min="1" controls-position="right" />
            </el-form-item>
            <el-form-item class="parse-field-wide" label="期望标题">
              <el-input v-model="parseCaseForm.expectedHeadingsText" type="textarea" :rows="3" placeholder="每行一个标题，按原文填写" />
            </el-form-item>
            <el-form-item class="parse-field-all" label="逐页术语 JSON">
              <el-input
                v-model="parseCaseForm.expectedTermsByPageText"
                type="textarea"
                :rows="4"
                placeholder='例如 {"1":["Redis","Celery"],"2":["Milvus"]}'
              />
            </el-form-item>

            <div class="parse-case-actions">
              <el-button type="primary" native-type="submit" :loading="busy.parseCaseCreate">创建解析 Case</el-button>
              <el-button :loading="busy.parseCaseRefresh" @click="$emit('refresh-parse-cases')">刷新列表</el-button>
            </div>
          </el-form>

          <div v-if="!parseCases.length" class="empty-state parse-case-empty">暂无文档解析评测 Case。</div>
          <div v-else class="parse-case-list">
            <article v-for="item in parseCases" :key="item.id" class="benchmark-item">
              <div class="trace-history-main">
                <strong>{{ item.case_id }} · {{ item.title }}</strong>
                <small>{{ suiteLabel(item.suite) }} · 期望 {{ item.expected_page_count || '-' }} 页</small>
              </div>
              <el-button type="danger" plain @click="$emit('delete-parse-case', item)">删除</el-button>
            </article>
          </div>
        </section>
      </div>
    </el-collapse-item>
  </el-collapse>
</template>

<script setup>
import { ElIcon } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'

defineProps({
  active: { type: Boolean, default: false },
  collapseValue: { type: Array, default: () => ['datasets'] },
  selectedSuite: { type: String, default: '' },
  selectedKb: { type: Object, default: null },
  evalSuites: { type: Array, default: () => [] },
  caseSources: { type: Array, default: () => [] },
  benchmarkForm: { type: Object, required: true },
  benchmarkCases: { type: Array, default: () => [] },
  parseCaseForm: { type: Object, required: true },
  parseCases: { type: Array, default: () => [] },
  busy: { type: Object, required: true },
})

const emit = defineEmits([
  'update:collapse-value',
  'update:selected-suite',
  'refresh',
  'import-defaults',
  'create-case',
  'toggle-case',
  'delete-case',
  'select-parse-file', 'create-parse-case', 'refresh-parse-cases', 'delete-parse-case',
])

const suiteLabels = {
  smoke: '冒烟集',
  benchmark: '基准集',
  regression: '回归集',
  release: '发布集',
}

const sourceLabels = {
  expert: '专家维护',
  trace: 'Trace 沉淀',
  eval_failure: '评测失败沉淀',
  user_feedback: '用户反馈沉淀',
  default_json: '默认样例',
  imported: '导入样例',
}

const difficultyLabels = {
  easy: '简单',
  medium: '中等',
  hard: '困难',
}

function updateSuite(value) {
  emit('update:selected-suite', value)
  emit('refresh')
}

function suiteLabel(value, fallback = '') {
  return suiteLabels[value] || fallback || value || '全部评测集'
}

function sourceLabel(value, fallback = '') {
  return sourceLabels[value] || fallback || value || '-'
}

function difficultyLabel(value) {
  return difficultyLabels[value] || value || '-'
}

function deterministicKeys(item) {
  return Object.keys(item?.deterministic_checks || {})
}
</script>
