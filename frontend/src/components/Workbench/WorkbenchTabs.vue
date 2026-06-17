<template>
  <el-tabs :model-value="activeTab" class="workbench-tabs" stretch @update:model-value="$emit('update:active-tab', $event)">
    <el-tab-pane v-for="tab in tabs" :key="tab.key" :name="tab.key">
      <template #label>
        <span class="workbench-tab-label">
          <strong>{{ tab.label }}</strong>
          <small>{{ tab.caption }}</small>
        </span>
      </template>
    </el-tab-pane>
  </el-tabs>
  <div class="workbench-context">
    <span>KB: {{ selectedKb?.name || '-' }}</span>
    <span>Docs: {{ documentCount }}</span>
    <span>Chunks: {{ chunkCount }}</span>
    <span>Eval Runs: {{ evalRunCount }}</span>
    <span>Model Calls: {{ modelCallCount }}</span>
  </div>
</template>

<script setup>
defineProps({
  activeTab: { type: String, required: true },
  tabs: { type: Array, default: () => [] },
  selectedKb: { type: Object, default: null },
  documentCount: { type: Number, default: 0 },
  chunkCount: { type: Number, default: 0 },
  evalRunCount: { type: Number, default: 0 },
  modelCallCount: { type: Number, default: 0 },
})

defineEmits(['update:active-tab'])
</script>
