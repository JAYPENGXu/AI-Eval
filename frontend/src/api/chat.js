import { buildQuery, request, streamRequest } from './client'

export const chatApi = {
  createSession: (payload) =>
    request('/chat-sessions/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listSessions: (params = {}) => request(`/chat-sessions/${buildQuery(params)}`),
  listMessages: (id) => request(`/chat-sessions/${id}/messages/`),
  deleteSession: (id) =>
    request(`/chat-sessions/${id}/`, {
      method: 'DELETE',
    }),
  sendMessage: (id, content, ragOptions = {}) =>
    request(`/chat-sessions/${id}/messages/`, {
      method: 'POST',
      body: JSON.stringify({ content, rag_options: ragOptions }),
    }),
  streamMessage: (id, content, ragOptions = {}, handlers) =>
    streamRequest(`/chat-sessions/${id}/stream/`, { content, rag_options: ragOptions }, handlers),
}
