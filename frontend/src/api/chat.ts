import { buildQuery, request, streamRequest } from './client'
import type { ChatMessage, ChatSession, QueryParams, RagOptions, StreamHandlers } from '../types/api'

export const chatApi = {
  createSession: (payload: Record<string, unknown>) =>
    request<ChatSession>('/chat-sessions/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listSessions: (params: QueryParams = {}) => request<ChatSession[]>(`/chat-sessions/${buildQuery(params)}`),
  listMessages: (id: number) => request<ChatMessage[]>(`/chat-sessions/${id}/messages/`),
  deleteSession: (id: number) =>
    request<void>(`/chat-sessions/${id}/`, {
      method: 'DELETE',
    }),
  sendMessage: (id: number, content: string, ragOptions: RagOptions = {}) =>
    request<ChatMessage>(`/chat-sessions/${id}/messages/`, {
      method: 'POST',
      body: JSON.stringify({ content, rag_options: ragOptions }),
    }),
  streamMessage: (id: number, content: string, ragOptions: RagOptions = {}, handlers: StreamHandlers = {}) =>
    streamRequest(`/chat-sessions/${id}/stream/`, { content, rag_options: ragOptions }, handlers),
}
