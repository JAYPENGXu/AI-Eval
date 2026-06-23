import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  abortActiveRequests,
  setOnSessionInvalidated,
} from '../api/authSession'
import type { User } from '../types/api'

export const useAuthStore = defineStore('auth', () => {
  const access = ref(localStorage.getItem('access') || '')
  const refresh = ref(localStorage.getItem('refresh') || '')
  const user = ref<User | null>(null)

  function setTokens(tokens: { access: string; refresh: string }) {
    // Prevent responses authorized as the previous identity from updating the new session.
    abortActiveRequests()
    access.value = tokens.access
    refresh.value = tokens.refresh
    localStorage.setItem('access', tokens.access)
    localStorage.setItem('refresh', tokens.refresh)
  }

  function setUser(nextUser: User | null) {
    user.value = nextUser
  }

  function clearSession() {
    abortActiveRequests()
    access.value = ''
    refresh.value = ''
    user.value = null
    localStorage.removeItem('access')
    localStorage.removeItem('refresh')
  }

  function logout() {
    clearSession()
    localStorage.clear()
  }

  function handleUnauthorized() {
    clearSession()
  }

  setOnSessionInvalidated(handleUnauthorized)

  return {
    access,
    refresh,
    user,
    setTokens,
    setUser,
    clearSession,
    logout,
    handleUnauthorized,
  }
})
