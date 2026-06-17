<template>
  <section class="card chat">
    <div class="chat-head">
      <div>
        <h2>RAG 对话</h2>
        <small v-if="session" class="chat-session-meta">
          {{ chatSessionLabel(session) }} · {{ formatDate(session.updated_at || session.created_at) }}
        </small>
        <small v-else class="chat-session-meta">选择或新建会话后开始提问</small>
        <div v-if="session" :class="['memory-hint', memoryHint.type]">
          <span>{{ memoryHint.label }}</span>
          <small>{{ memoryHint.detail }}</small>
        </div>
      </div>
      <div class="chat-head-actions">
        <el-button @click="chatHistoryDrawerOpen = true" :disabled="!selectedKb || !chatSessions.length">
          历史会话
        </el-button>
        <el-button type="primary" @click="$emit('new-session')" :disabled="!selectedKb">新会话</el-button>
      </div>
    </div>

    <ChatHistoryDrawer
      :open="chatHistoryDrawerOpen"
      :sessions="chatSessions"
      :current-session="session"
      :format-date="formatDate"
      @close="chatHistoryDrawerOpen = false"
      @select-session="selectSession"
      @delete-session="$emit('delete-session', $event)"
    />

    <div class="messages">
      <div v-if="!messages.length" class="chat-empty-state">
        <strong>{{ session ? '当前会话暂无消息' : '还没有选择会话' }}</strong>
        <span>{{ selectedKb ? '可以直接在下方输入问题开始 RAG 对话。' : '先选择知识库，再开始提问。' }}</span>
      </div>
      <article v-for="message in messages" :key="message.id" :class="['message', message.role]">
        <p class="message-content">
          <template v-for="(part, partIndex) in renderMessageParts(message)" :key="`${message.id}-part-${partIndex}`">
            <el-button
              v-if="part.type === 'citation'"
              text
              class="citation-link"
              title="Highlight source"
              @click="$emit('highlight-citation', message, part.number)"
            >[{{ part.number }}]</el-button>
            <span v-else>{{ part.text }}</span>
          </template>
        </p>
        <div v-if="message.role === 'assistant' && !String(message.id).startsWith('stream-')" class="message-feedback">
          <el-button
            text
            :class="{ active: message.feedback?.rating === 'helpful' }"
            :disabled="busy.feedback === message.id"
            @click="$emit('submit-feedback', message, 'helpful')"
          >有帮助</el-button>
          <el-button
            text
            :class="{ active: message.feedback?.rating === 'not_helpful' }"
            :disabled="busy.feedback === message.id"
            @click="$emit('open-negative-feedback', message)"
          >没帮助</el-button>
          <span v-if="message.feedback" class="feedback-status">{{ feedbackStatusText(message.feedback) }}</span>
        </div>
        <div v-if="feedbackDrafts[message.id]?.open" class="feedback-reason-panel">
          <el-select v-model="feedbackDrafts[message.id].reason" placeholder="选择原因">
            <el-option v-for="item in feedbackReasons" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-input v-model="feedbackDrafts[message.id].comment" placeholder="补充说明，可选" />
          <el-button
            type="primary"
            @click="$emit('submit-feedback', message, 'not_helpful')"
            :disabled="!feedbackDrafts[message.id].reason || busy.feedback === message.id"
            :loading="busy.feedback === message.id"
          >
            提交反馈
          </el-button>
        </div>
        <el-collapse
          v-if="message.sources?.length"
          :model-value="isSourcePanelOpen(message) ? ['sources'] : []"
          class="message-source-collapse"
          @update:model-value="$emit('set-source-panel-open', message, $event.includes('sources'))"
        >
          <el-collapse-item title="引用来源" name="sources">
            <div
              v-for="(source, sourceIndex) in message.sources"
              :key="source.chunk_id || sourceIndex"
              :class="['source', { active: isSourceHighlighted(message, source, sourceIndex) }]"
            >
              <strong><span class="source-citation">[{{ sourceCitationNumber(source, sourceIndex) }}]</span> {{ source.document }}</strong>
              <span>{{ Number(source.score).toFixed(3) }}</span>
              <p>{{ source.content }}</p>
            </div>
          </el-collapse-item>
        </el-collapse>
      </article>
    </div>

    <el-form class="ask chat-composer" @submit.prevent="submitAsk">
      <el-input
        type="textarea"
        :model-value="question"
        placeholder="基于已索引文档提问"
        :autosize="{ minRows: 1, maxRows: 5 }"
        resize="none"
        @update:model-value="$emit('update:question', $event)"
        @keydown.enter.exact.prevent="submitAsk"
      />
      <el-button
        type="primary"
        native-type="submit"
        circle
        class="composer-send"
        :disabled="!selectedKb || loading || !question.trim()"
        aria-label="发送"
      >
        <el-icon :class="{ 'is-loading': loading }">
          <Loading v-if="loading" />
          <Top v-else />
        </el-icon>
      </el-button>
    </el-form>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Loading, Top } from '@element-plus/icons-vue'
import ChatHistoryDrawer from './ChatHistoryDrawer.vue'

const props = defineProps({
  selectedKb: { type: Object, default: null },
  session: { type: Object, default: null },
  chatSessions: { type: Array, default: () => [] },
  messages: { type: Array, default: () => [] },
  question: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  busy: { type: Object, required: true },
  feedbackDrafts: { type: Object, required: true },
  feedbackReasons: { type: Array, default: () => [] },
  chatSessionLabel: { type: Function, required: true },
  formatDate: { type: Function, required: true },
  renderMessageParts: { type: Function, required: true },
  feedbackStatusText: { type: Function, required: true },
  isSourcePanelOpen: { type: Function, required: true },
  isSourceHighlighted: { type: Function, required: true },
  sourceCitationNumber: { type: Function, required: true },
})

const emit = defineEmits([
  'ask',
  'new-session',
  'select-session',
  'delete-session',
  'update:question',
  'highlight-citation',
  'submit-feedback',
  'open-negative-feedback',
  'set-source-panel-open',
])

const chatHistoryDrawerOpen = ref(false)

const memoryHint = computed(() => {
  const summary = props.session?.summary_state
  if (!summary) {
    return { type: 'pending', label: '记忆摘要：未触发', detail: '长对话达到阈值后会自动生成摘要' }
  }
  if (summary.status === 'running') {
    return { type: 'running', label: '记忆摘要：生成中', detail: `已覆盖 ${summary.summary_message_count || 0} 条消息` }
  }
  if (summary.status === 'failed') {
    return { type: 'failed', label: '记忆摘要：生成失败', detail: summary.error_message || '下次达到条件会再次尝试' }
  }
  if (summary.summary) {
    return {
      type: 'ready',
      label: '记忆摘要：已启用',
      detail: `覆盖 ${summary.summary_message_count || 0} 条消息 · ${summary.token_estimate || 0} tokens`,
    }
  }
  return { type: 'pending', label: '记忆摘要：等待触发', detail: '继续对话后自动生成' }
})

function submitAsk() {
  if (!props.selectedKb || props.loading || !props.question.trim()) return
  emit('ask')
}

function selectSession(item) {
  emit('select-session', item)
  chatHistoryDrawerOpen.value = false
}
</script>
