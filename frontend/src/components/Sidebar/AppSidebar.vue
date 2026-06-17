<template>
  <el-aside width="300px">
    <div class="brand">
      <h2>RAGPilot</h2>
      <span>{{ username }}</span>
    </div>

    <div class="panel">
      <h3>知识库</h3>
      <div class="inline">
        <el-input v-model="kbForm.name" placeholder="知识库名称" />
        <el-button type="primary" @click="$emit('create-kb')">新建</el-button>
      </div>
      <el-button
        v-for="kb in kbs"
        :key="kb.id"
        class="list-item"
        :class="{ active: selectedKb?.id === kb.id }"
        @click="$emit('select-kb', kb)"
      >
        {{ kb.name }}
      </el-button>
    </div>

    <div class="panel">
      <h3>文档</h3>
      <el-upload
        class="sidebar-upload"
        :auto-upload="false"
        :show-file-list="false"
        :disabled="!selectedKb || busy.upload"
        :on-change="(file) => $emit('upload', file)"
      >
        <el-button :disabled="!selectedKb || busy.upload" :loading="busy.upload">上传文档</el-button>
      </el-upload>
      <el-button
        v-for="doc in documents"
        :key="doc.id"
        class="list-item"
        :class="{ active: selectedDocument?.id === doc.id }"
        @click="$emit('select-document', doc)"
      >
        <strong>{{ doc.filename }}</strong>
        <small>{{ doc.status }} · {{ doc.chunk_method }}</small>
      </el-button>
    </div>

    <el-button type="danger" :loading="busy.reset" @click="$emit('reset-workspace')">
      {{ busy.reset ? '重置中' : '一键重置' }}
    </el-button>

    <el-button @click="$emit('logout')">退出</el-button>
  </el-aside>
</template>

<script setup>
defineProps({
  username: { type: String, default: '' },
  kbs: { type: Array, default: () => [] },
  documents: { type: Array, default: () => [] },
  selectedKb: { type: Object, default: null },
  selectedDocument: { type: Object, default: null },
  kbForm: { type: Object, required: true },
  busy: { type: Object, required: true },
})

defineEmits([
  'create-kb',
  'select-kb',
  'select-document',
  'upload',
  'reset-workspace',
  'logout',
])
</script>
