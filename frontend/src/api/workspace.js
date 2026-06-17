import { request } from './client'

export const workspaceApi = {
  resetWorkspace: () =>
    request('/reset-workspace/', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
}
