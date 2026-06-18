import { request } from './client'

export const workspaceApi = {
  resetWorkspace: () =>
    request<{ deleted: Record<string, number> }>('/reset-workspace/', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
}
