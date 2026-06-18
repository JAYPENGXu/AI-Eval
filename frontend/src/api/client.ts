import { useAuthStore } from '../stores/auth'
import type { QueryParams, StreamHandlers } from '../types/api'
import {
  UnauthorizedError,
  getSessionSignal,
  invalidateSession,
  mergeSignals,
} from './authSession'

export const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export function buildQuery(params: QueryParams = {}): string {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  })
  const text = query.toString()
  return text ? `?${text}` : ''
}

function getAccessToken(): string {
  try {
    return useAuthStore().access || ''
  } catch {
    return localStorage.getItem('access') || ''
  }
}

function parseResponseBody(text: string): unknown {
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

function buildRequestError(response: Response, data: unknown): Error {
  const record = data && typeof data === 'object' ? data as Record<string, unknown> : {}
  const fieldErrors = Object.entries(record)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join('，') : value}`)
    .join('；')
  const message = (record.detail as string) || (record.error as string) || fieldErrors || `HTTP ${response.status}`
  if (response.status === 401) {
    return new UnauthorizedError(typeof message === 'string' ? message : '登录已失效，请重新登录')
  }
  const error = new Error(message) as Error & { status?: number }
  error.status = response.status
  return error
}

export async function request<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {})
  if (!(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  const token = getAccessToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  const signal = mergeSignals(getSessionSignal(), options.signal)
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers, signal })
  const text = await response.text()
  const data = parseResponseBody(text)
  if (!response.ok) {
    const error = buildRequestError(response, data)
    if (response.status === 401) {
      invalidateSession()
    }
    throw error
  }
  return data as T
}

function authHeaders(extra: Record<string, string> = {}): Headers {
  const headers = new Headers(extra)
  const token = getAccessToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  return headers
}

function dispatchSseBlock(block: string, handlers: StreamHandlers) {
  const lines = block.split(/\r?\n/)
  let event = 'message'
  const dataLines: string[] = []
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

function consumeSseText(text: string, state: { buffer: string }, handlers: StreamHandlers) {
  state.buffer += text
  const blocks = state.buffer.split(/\r?\n\r?\n/)
  state.buffer = blocks.pop() || ''
  for (const block of blocks) {
    dispatchSseBlock(block, handlers)
  }
}

async function readTextStream(response: Response, handlers: StreamHandlers) {
  const state = { buffer: '' }
  if (window.TextDecoderStream) {
    const reader = response.body!.pipeThrough(new TextDecoderStream()).getReader()
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      consumeSseText(value, state, handlers)
    }
  } else {
    const reader = response.body!.getReader()
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

export async function streamRequest(
  path: string,
  body: Record<string, unknown>,
  handlers: StreamHandlers = {},
): Promise<void> {
  const headers = authHeaders({ 'Content-Type': 'application/json' })
  const signal = mergeSignals(getSessionSignal(), handlers.signal)
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    const text = await response.text()
    const data = parseResponseBody(text)
    const error = buildRequestError(response, data)
    if (response.status === 401) {
      invalidateSession()
    }
    throw error
  }
  if (!response.body) {
    throw new Error('ReadableStream is not supported by this browser')
  }

  await readTextStream(response, handlers)
}
