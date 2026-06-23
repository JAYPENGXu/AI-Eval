import { request } from './client'
import type { AuthTokens, DemoPersonasResponse, User } from '../types/api'

export const authApi = {
  register: (username: string, password: string) =>
    request<User>('/auth/register/', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  login: (username: string, password: string) =>
    request<AuthTokens>('/auth/login/', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  demoPersonas: () => request<DemoPersonasResponse>('/demo/personas/'),
  personaLogin: (username: string) =>
    request<AuthTokens>('/demo/persona-login/', {
      method: 'POST',
      body: JSON.stringify({ username }),
    }),
  me: () => request<User>('/auth/me/'),
}
