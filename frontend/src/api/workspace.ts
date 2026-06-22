import { request } from './client'

export const workspaceApi = {
  resetWorkspace: (organization: number, confirmShared = '') =>
    request<{ deleted: Record<string, number> }>('/reset-workspace/', {
      method: 'POST',
      body: JSON.stringify({ organization, confirm_shared: confirmShared }),
    }),
}
