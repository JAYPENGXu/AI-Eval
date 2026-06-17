import { request } from './client'

export const authApi = {
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
}
