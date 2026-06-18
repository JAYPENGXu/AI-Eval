import { request } from './client'
import type { UserFeedback } from '../types/api'

export const feedbackApi = {
  createUserFeedback: (payload: Record<string, unknown>) =>
    request<UserFeedback>('/rag-user-feedback/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
