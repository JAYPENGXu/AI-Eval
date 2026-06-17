import { store } from '../main'

export const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export function buildQuery(params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, value)
  })
  const text = query.toString()
  return text ? `?${text}` : ''
}

export async function request(path, options = {}) {
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
    if (!line || line.startsWith(':')) continue
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

function consumeSseText(text, state, handlers) {
  state.buffer += text
  const blocks = state.buffer.split(/\r?\n\r?\n/)
  state.buffer = blocks.pop() || ''
  for (const block of blocks) {
    dispatchSseBlock(block, handlers)
  }
}

async function readTextStream(response, handlers) {
  const state = { buffer: '' }
  if (window.TextDecoderStream) {
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      consumeSseText(value, state, handlers)
    }
  } else {
    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      consumeSseText(decoder.decode(value, { stream: true }), state, handlers)
    }
    consumeSseText(decoder.decode(), state, handlers)
  }
  if (state.buffer.trim()) {
    dispatchSseBlock(state.buffer, handlers)
  }
}

export async function streamRequest(path, body, handlers = {}) {
  const headers = authHeaders({ 'Content-Type': 'application/json' })
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal: handlers.signal,
  })
  if (!response.ok) {
    const text = await response.text()
    const data = text ? JSON.parse(text) : null
    throw new Error(data?.detail || `HTTP ${response.status}`)
  }
  if (!response.body) {
    throw new Error('ReadableStream is not supported by this browser')
  }

  await readTextStream(response, handlers)
}
