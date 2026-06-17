import { request } from './client'

export const feedbackApi = {
  createUserFeedback: (payload) =>
    request('/rag-user-feedback/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
