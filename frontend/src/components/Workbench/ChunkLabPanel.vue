<template>
  <el-collapse
    v-show="active"
    :model-value="collapseValue"
    class="debug-section"
    @update:model-value="$emit('update:collapse-value', $event)"
  >
    <el-collapse-item name="chunk-lab">
      <template #title><span>文档解析与切片实验室</span><small>（结构解析、质量门禁、切片与索引）</small></template>
      <div class="debug-section-body">
        <section v-if="selectedDocument" class="document-parse-section">
          <div class="parse-heading">
            <div>
              <strong>{{ selectedDocument.filename }}</strong>
              <small>{{ selectedDocument.mime_type || selectedDocument.file_type }}</small>
            </div>
            <el-tag :type="parseStatusType">{{ parseStatusLabel }}</el-tag>
          </div>

          <el-progress
            v-if="isParsing"
            :percentage="parseProgress"
            :indeterminate="!latestParse?.progress_total"
            :duration="2"
          />

          <div class="parse-actions">
            <el-button
              :loading="busy.parse"
              :disabled="isParsing"
              @click="$emit('reparse')"
            >重新解析</el-button>
            <el-button
              v-if="latestParse?.status === 'needs_review'"
              type="warning"
              :loading="busy.acceptParse"
              @click="$emit('accept-parse')"
            >确认使用解析结果</el-button>
          </div>

          <p v-if="latestParse?.error_message" class="error">{{ latestParse.error_message }}</p>

          <div v-if="latestParse?.quality_metrics" class="parse-metrics">
            <span>质量分 <strong>{{ latestParse.quality_score ?? '-' }}</strong></span>
            <span>文本覆盖率 <strong>{{ percent(latestParse.quality_metrics.text_coverage_rate) }}</strong></span>
            <span>空白页比例 <strong>{{ percent(latestParse.quality_metrics.blank_page_rate) }}</strong></span>
            <span>OCR 页比例 <strong>{{ percent(latestParse.quality_metrics.ocr_page_rate) }}</strong></span>
            <span>异常字符率 <strong>{{ percent(latestParse.quality_metrics.garbled_character_rate) }}</strong></span>
            <span>解析耗时 <strong>{{ latestParse.quality_metrics.parse_duration_ms || 0 }} ms</strong></span>
          </div>

          <div v-if="parsePreview?.page" class="parse-preview">
            <div class="parse-preview-head">
              <strong>解析预览 · 第 {{ parsePreview.page.page_number }} 页</strong>
              <span>{{ parsePreview.page.extraction_method === 'ocr' ? 'PaddleOCR' : '本地解析' }}</span>
            </div>
            <el-pagination
              v-if="parsePreview.page_count > 1"
              small
              layout="prev, pager, next"
              :page-size="1"
              :total="parsePreview.page_count"
              :current-page="parsePreview.page.page_number"
              @current-change="$emit('load-parse-page', $event)"
            />
            <div class="parse-blocks">
              <article v-for="block in parsePreview.page.blocks" :key="block.id" class="parse-block">
                <div>
                  <el-tag size="small" effect="plain">{{ block.type }}</el-tag>
                  <small v-if="block.heading_path?.length">{{ block.heading_path.join(' / ') }}</small>
                </div>
                <p>{{ block.text }}</p>
              </article>
            </div>
          </div>
        </section>

        <el-form class="toolbar element-toolbar" label-position="top">
          <el-form-item label="切片方式">
            <el-select v-model="chunkForm.chunk_method" @change="$emit('preview')">
              <el-option v-for="method in chunkMethods" :key="method.value" :label="method.label" :value="method.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="chunk size">
            <el-input-number v-model="chunkForm.options.chunk_size" :min="100" :step="10" />
          </el-form-item>
          <el-form-item label="overlap">
            <el-input-number v-model="chunkForm.options.chunk_overlap" :min="0" />
          </el-form-item>
          <el-form-item label="window">
            <el-input-number v-model="chunkForm.options.window_size" :min="1" />
          </el-form-item>
          <el-button type="primary" @click="$emit('preview')" :disabled="!parseReady || busy.preview" :loading="busy.preview">预览</el-button>
          <el-button @click="$emit('index-document')" :disabled="!parseReady || busy.index" :loading="busy.index">
            {{ busy.index ? '索引中' : '索引' }}
          </el-button>
        </el-form>

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
            <small v-if="chunkLocation(chunk)">{{ chunkLocation(chunk) }}</small>
            <p>{{ chunk.content }}</p>
          </article>
        </div>
      </div>
    </el-collapse-item>
  </el-collapse>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  active: { type: Boolean, default: false },
  collapseValue: { type: Array, default: () => ['chunk-lab'] },
  chunkForm: { type: Object, required: true },
  chunkMethods: { type: Array, default: () => [] },
  selectedDocument: { type: Object, default: null },
  parsePreview: { type: Object, default: null },
  busy: { type: Object, required: true },
  notice: { type: String, default: '' },
  actionError: { type: String, default: '' },
  stats: { type: Object, required: true },
  chunks: { type: Array, default: () => [] },
})

defineEmits([
  'preview', 'index-document', 'reparse', 'accept-parse', 'load-parse-page', 'update:collapse-value',
])

const latestParse = computed(() => props.selectedDocument?.latest_parse)
const parseReady = computed(() => latestParse.value?.status === 'completed')
const isParsing = computed(() => ['queued', 'running'].includes(latestParse.value?.status))
const parseProgress = computed(() => {
  const total = Number(latestParse.value?.progress_total || 0)
  return total ? Math.min(100, Math.round(Number(latestParse.value?.progress_current || 0) / total * 100)) : 0
})
const parseStatusLabel = computed(() => ({
  queued: '等待解析',
  running: '解析中',
  completed: '解析完成',
  needs_review: '需要确认',
  failed: '解析失败',
  superseded: '已被新任务替代',
}[latestParse.value?.status] || props.selectedDocument?.status || '未解析'))
const parseStatusType = computed(() => ({
  completed: 'success',
  needs_review: 'warning',
  failed: 'danger',
  queued: 'info',
  running: 'primary',
}[latestParse.value?.status] || 'info'))

function percent(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`
}

function chunkLocation(chunk) {
  const metadata = chunk.metadata || {}
  const parts = []
  if (metadata.page_start) {
    parts.push(metadata.page_end && metadata.page_end !== metadata.page_start
      ? `第 ${metadata.page_start}-${metadata.page_end} 页`
      : `第 ${metadata.page_start} 页`)
  }
  if (metadata.heading_path?.length) parts.push(metadata.heading_path.join(' / '))
  if (metadata.paragraph_start) parts.push(`段落 ${metadata.paragraph_start}`)
  return parts.join(' · ')
}
</script>
