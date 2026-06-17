import { reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from '../api'

export function useChat({
  selectedKb,
  ragOptions,
  latestTrace,
  notice,
  actionError,
  busy,
  feedbackReasons,
  runAction,
  loadTraceHistory,
  loadModelUsage,
  loadAgentActions,
}) {
  const messages = ref([])
  const session = ref(null)
  const chatSessions = ref([])
  const question = ref('')
  const loading = ref(false)
  const highlightedSourceRefs = reactive({})
  const openSourcePanels = reactive({})
  const feedbackDrafts = reactive({})

  function resetChatState() {
    messages.value = []
    session.value = null
    chatSessions.value = []
    question.value = ''
    loading.value = false
  }

  function messageSourceKey(message) {
    return String(message?.id || '')
  }

  function openNegativeFeedback(message) {
    feedbackDrafts[message.id] = {
      open: true,
      reason: message.feedback?.reason || '',
      comment: message.feedback?.comment || '',
    }
  }

  async function submitFeedback(message, rating) {
    if (!message?.id || String(message.id).startsWith('local-') || String(message.id).startsWith('stream-')) return
    const draft = feedbackDrafts[message.id] || {}
    if (rating === 'not_helpful' && !draft.reason) {
      openNegativeFeedback(message)
      return
    }
    busy.feedback = message.id
    try {
      const feedback = await api.createUserFeedback({
        message: message.id,
        rating,
        reason: rating === 'not_helpful' ? draft.reason : '',
        comment: rating === 'not_helpful' ? draft.comment || '' : '',
      })
      message.feedback = feedback
      feedbackDrafts[message.id] = { open: false, reason: '', comment: '' }
      await loadAgentActions()
      notice.value = rating === 'not_helpful'
        ? '已记录负反馈，并生成待确认的回归样例动作'
        : '已记录正反馈'
    } catch (err) {
      actionError.value = err.message
    } finally {
      busy.feedback = ''
    }
  }

  function feedbackStatusText(feedback) {
    if (!feedback) return ''
    if (feedback.rating === 'helpful') return '已标记有帮助'
    const reason = feedbackReasons.find((item) => item.value === feedback.reason)?.label || '负反馈'
    return `已标记没帮助：${reason}`
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

  function lastSessionStorageKey(kbId = selectedKb.value?.id) {
    return kbId ? `aiassistant:last-session:${kbId}` : ''
  }

  function rememberSession(sessionId, kbId = selectedKb.value?.id) {
    const key = lastSessionStorageKey(kbId)
    if (key && sessionId) localStorage.setItem(key, String(sessionId))
  }

  async function loadChatSessions({ restore = false } = {}) {
    if (!selectedKb.value) {
      chatSessions.value = []
      return
    }
    chatSessions.value = await api.listSessions({ kb: selectedKb.value.id })
    if (session.value?.id) {
      const refreshedCurrent = chatSessions.value.find((item) => item.id === session.value.id)
      if (refreshedCurrent) session.value = refreshedCurrent
    }
    if (!restore) return
    const savedId = Number(localStorage.getItem(lastSessionStorageKey()) || 0)
    const target = chatSessions.value.find((item) => item.id === savedId) || chatSessions.value[0]
    if (target) {
      await selectChatSession(target, { remember: false })
    }
  }

  async function selectChatSessionById(value) {
    const id = Number(value)
    const target = chatSessions.value.find((item) => item.id === id)
    if (target) await selectChatSession(target)
  }

  async function selectChatSession(item, { remember = true } = {}) {
    session.value = item
    messages.value = await api.listMessages(item.id)
    if (remember) rememberSession(item.id, item.kb)
  }

  async function deleteChatSession(item) {
    if (!item?.id) return
    try {
      await ElMessageBox.confirm(
        '删除后该会话的消息、Trace 和反馈记录也会一并删除。',
        `确认删除会话 #${item.id}？`,
        {
          confirmButtonText: '删除',
          cancelButtonText: '取消',
          type: 'warning',
          confirmButtonClass: 'el-button--danger',
        },
      )
    } catch {
      return
    }
    await runAction(async () => {
      await api.deleteSession(item.id)
      const deletedCurrent = session.value?.id === item.id
      chatSessions.value = chatSessions.value.filter((sessionItem) => sessionItem.id !== item.id)
      if (String(localStorage.getItem(lastSessionStorageKey(item.kb))) === String(item.id)) {
        localStorage.removeItem(lastSessionStorageKey(item.kb))
      }
      if (deletedCurrent) {
        const nextSession = chatSessions.value[0] || null
        session.value = nextSession
        messages.value = nextSession ? await api.listMessages(nextSession.id) : []
        latestTrace.value = null
        if (nextSession) rememberSession(nextSession.id, nextSession.kb)
      }
      await loadTraceHistory()
      await loadModelUsage()
      notice.value = `已删除会话 #${item.id}`
    })
  }

  function chatSessionLabel(item) {
    const count = item.message_count ?? 0
    return `#${item.id} · ${item.display_title || item.title || 'RAG 问答'} · ${count} 条`
  }

  async function newSession() {
    session.value = await api.createSession({ kb: selectedKb.value.id, title: 'RAG 问答' })
    messages.value = []
    rememberSession(session.value.id)
    await loadChatSessions()
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
          loadChatSessions().then(() => {
            if (session.value?.id) rememberSession(session.value.id)
          })
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

  return {
    messages,
    session,
    chatSessions,
    question,
    loading,
    feedbackDrafts,
    resetChatState,
    openNegativeFeedback,
    submitFeedback,
    feedbackStatusText,
    renderMessageParts,
    sourceCitationNumber,
    highlightCitation,
    isSourcePanelOpen,
    setSourcePanelOpen,
    isSourceHighlighted,
    loadChatSessions,
    selectChatSessionById,
    selectChatSession,
    deleteChatSession,
    chatSessionLabel,
    newSession,
    ask,
  }
}
