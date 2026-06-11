import { store } from './main'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8010/api'

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {})
  if (!(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  if (store.access) {
    headers.set('Authorization', `Bearer ${store.access}`)
  }
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  const text = await response.text()
  const data = text ? JSON.parse(text) : null
  if (!response.ok) {
    const fieldErrors = data && typeof data === 'object'
      ? Object.entries(data)
          .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join('，') : value}`)
          .join('；')
      : ''
    throw new Error(data?.detail || data?.error || fieldErrors || `HTTP ${response.status}`)
  }
  return data
}

function authHeaders(extra = {}) {
  const headers = new Headers(extra)
  if (store.access) {
    headers.set('Authorization', `Bearer ${store.access}`)
  }
  return headers
}

function dispatchSseBlock(block, handlers) {
  const lines = block.split(/\r?\n/)
  let event = 'message'
  const dataLines = []
  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart())
    }
  }
  if (!dataLines.length) return
  const data = JSON.parse(dataLines.join('\n'))
  if (event === 'sources') handlers.onSources?.(data)
  if (event === 'trace') handlers.onTrace?.(data)
  if (event === 'delta') handlers.onDelta?.(data.content || '')
  if (event === 'done') handlers.onDone?.(data)
  if (event === 'error') {
    handlers.onError?.(data)
    throw new Error(data.detail || 'Stream failed')
  }
}

async function streamRequest(path, body, handlers = {}) {
  const headers = authHeaders({ 'Content-Type': 'application/json' })
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const text = await response.text()
    const data = text ? JSON.parse(text) : null
    throw new Error(data?.detail || `HTTP ${response.status}`)
  }
  if (!response.body) {
    throw new Error('ReadableStream is not supported by this browser')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      dispatchSseBlock(block, handlers)
    }
  }
  buffer += decoder.decode()
  if (buffer.trim()) {
    dispatchSseBlock(buffer, handlers)
  }
}

export const api = {
  register: (username, password) =>
    request('/auth/register/', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  login: (username, password) =>
    request('/auth/login/', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  me: () => request('/auth/me/'),
  chunkMethods: () => request('/chunk-methods/'),
  listKbs: () => request('/knowledge-bases/'),
  createKb: (payload) =>
    request('/knowledge-bases/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listDocuments: () => request('/documents/'),
  uploadDocument: (kb, file) => {
    const form = new FormData()
    form.append('kb', kb)
    form.append('file', file)
    return request('/documents/', { method: 'POST', body: form })
  },
  previewChunks: (id, payload) =>
    request(`/documents/${id}/chunk-preview/`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  indexDocument: (id, payload) =>
    request(`/documents/${id}/index/`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  createSession: (payload) =>
    request('/chat-sessions/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listSessions: () => request('/chat-sessions/'),
  listMessages: (id) => request(`/chat-sessions/${id}/messages/`),
  sendMessage: (id, content, ragOptions = {}) =>
    request(`/chat-sessions/${id}/messages/`, {
      method: 'POST',
      body: JSON.stringify({ content, rag_options: ragOptions }),
    }),
  streamMessage: (id, content, ragOptions = {}, handlers) =>
    streamRequest(`/chat-sessions/${id}/stream/`, { content, rag_options: ragOptions }, handlers),
  listTraces: (params = {}) => {
    const query = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') query.set(key, value)
    })
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return request(`/rag-traces/${suffix}`)
  },
  getTrace: (id) => request(`/rag-traces/${id}/`),
  listBenchmarkCases: (params = {}) => {
    const query = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') query.set(key, value)
    })
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return request(`/rag-benchmark-cases/${suffix}`)
  },
  createBenchmarkCase: (payload) =>
    request('/rag-benchmark-cases/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateBenchmarkCase: (id, payload) =>
    request(`/rag-benchmark-cases/${id}/`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteBenchmarkCase: (id) =>
    request(`/rag-benchmark-cases/${id}/`, {
      method: 'DELETE',
    }),
  importDefaultBenchmarkCases: (kb) =>
    request('/rag-benchmark-cases/import-defaults/', {
      method: 'POST',
      body: JSON.stringify({ kb }),
    }),
  createBenchmarkCaseFromTrace: (payload) =>
    request('/rag-benchmark-cases/from-trace/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  createBenchmarkCaseFromEvalCase: (payload) =>
    request('/rag-benchmark-cases/from-eval-case/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listEvalRuns: (params = {}) => {
    const query = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') query.set(key, value)
    })
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return request(`/rag-eval-runs/${suffix}`)
  },
  getEvalRun: (id) => request(`/rag-eval-runs/${id}/`),
  runEval: (payload) =>
    request('/rag-eval-runs/run/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getModelUsageSummary: (params = {}) => {
    const query = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') query.set(key, value)
    })
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return request(`/model-usage/summary/${suffix}`)
  },
  resetWorkspace: () =>
    request('/reset-workspace/', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
}
