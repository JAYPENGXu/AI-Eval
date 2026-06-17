<template>
  <div v-if="open" class="chat-history-scrim" @click="$emit('close')"></div>
  <aside class="chat-history-drawer" :class="{ open }" aria-label="历史会话">
    <div class="chat-history-drawer-head">
      <div>
        <strong>历史会话</strong>
        <small>{{ sessions.length }} 个会话</small>
      </div>
      <el-button text @click="$emit('close')">关闭</el-button>
    </div>
    <div v-if="!sessions.length" class="chat-history-empty">暂无历史会话</div>
    <div v-else class="chat-history-list">
      <article
        v-for="item in sessions"
        :key="item.id"
        class="chat-history-item"
        :class="{ active: currentSession?.id === item.id }"
      >
        <el-button text class="chat-history-main-button" @click="$emit('select-session', item)">
          <strong>{{ item.display_title || item.title || 'RAG 问答' }}</strong>
          <span>#{{ item.id }} · {{ item.message_count ?? 0 }} 条消息</span>
          <small>{{ formatDate(item.updated_at || item.created_at) }}</small>
        </el-button>
        <el-button
          type="danger"
          text
          class="chat-history-delete"
          @click.stop="$emit('delete-session', item)"
        >
          删除
        </el-button>
      </article>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  open: { type: Boolean, default: false },
  sessions: { type: Array, default: () => [] },
  currentSession: { type: Object, default: null },
  formatDate: { type: Function, required: true },
})

defineEmits(['close', 'select-session', 'delete-session'])
</script>
