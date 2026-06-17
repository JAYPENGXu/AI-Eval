<template>
  <el-collapse v-show="active" :model-value="collapseValue" class="debug-section" @update:model-value="$emit('update:collapse-value', $event)">
    <el-collapse-item name="chunk-lab">
      <template #title><span>切片实验室</span><small>（文档切片、预览与索引）</small></template>
      <div class="debug-section-body">
        <el-form class="toolbar element-toolbar" label-position="top">
          <el-form-item label="切片方式">
            <el-select v-model="chunkForm.chunk_method" @change="$emit('preview')">
              <el-option v-for="method in chunkMethods" :key="method.value" :label="method.label" :value="method.value" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <template #label>
              <span class="parameter-label">
                chunk size
                <el-tooltip content="每个切片的目标长度。值越大，单个 chunk 包含的信息越多，但可能带入更多无关内容。" placement="top">
                  <span class="help-dot" tabindex="0">?</span>
                </el-tooltip>
              </span>
            </template>
            <el-input-number v-model="chunkForm.options.chunk_size" :min="100" :step="10" />
          </el-form-item>
          <el-form-item>
            <template #label>
              <span class="parameter-label">
                overlap
                <el-tooltip content="相邻切片之间重复保留的内容长度。适当重叠可以减少上下文被切断，但会增加索引量。" placement="top">
                  <span class="help-dot" tabindex="0">?</span>
                </el-tooltip>
              </span>
            </template>
            <el-input-number v-model="chunkForm.options.chunk_overlap" :min="0" />
          </el-form-item>
          <el-form-item>
            <template #label>
              <span class="parameter-label">
                window
                <el-tooltip content="句子窗口大小。用于在命中句子前后补充相邻句子，让检索结果保留更多上下文。" placement="top">
                  <span class="help-dot" tabindex="0">?</span>
                </el-tooltip>
              </span>
            </template>
            <el-input-number v-model="chunkForm.options.window_size" :min="1" />
          </el-form-item>
          <el-button type="primary" @click="$emit('preview')" :disabled="!selectedDocument || busy.preview" :loading="busy.preview">预览</el-button>
          <el-button @click="$emit('index-document')" :disabled="!selectedDocument || busy.index" :loading="busy.index">
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
            <p>{{ chunk.content }}</p>
          </article>
        </div>
      </div>
    </el-collapse-item>
  </el-collapse>
</template>

<script setup>
defineProps({
  active: { type: Boolean, default: false },
  collapseValue: { type: Array, default: () => ['chunk-lab'] },
  chunkForm: { type: Object, required: true },
  chunkMethods: { type: Array, default: () => [] },
  selectedDocument: { type: Object, default: null },
  busy: { type: Object, required: true },
  notice: { type: String, default: '' },
  actionError: { type: String, default: '' },
  stats: { type: Object, required: true },
  chunks: { type: Array, default: () => [] },
})

defineEmits(['preview', 'index-document', 'update:collapse-value'])
</script>
