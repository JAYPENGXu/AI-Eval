<template>
  <AuthPanel v-if="!access" :auth="auth" :error="error" @login="login" @register="register" />
  <slot v-else :user="user" :logout="logout"></slot>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'
import AuthPanel from './AuthPanel.vue'

const props = defineProps<{
  bootstrap: () => Promise<void>
}>()

const authStore = useAuthStore()
const { access, user } = storeToRefs(authStore)

const auth = reactive({ username: '', password: '' })
const error = ref('')

function validateAuthForm() {
  if (!auth.username.trim() || !auth.password) {
    error.value = '请输入用户名和密码'
    return false
  }
  return true
}

async function login() {
  error.value = ''
  if (!validateAuthForm()) return
  try {
    const token = await api.login(auth.username.trim(), auth.password)
    authStore.setTokens(token)
    await props.bootstrap()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  }
}

async function register() {
  error.value = ''
  if (!validateAuthForm()) return
  try {
    await api.register(auth.username.trim(), auth.password)
    await login()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  }
}

function logout() {
  authStore.logout()
}

onMounted(async () => {
  if (access.value) {
    try {
      await props.bootstrap()
    } catch {
      logout()
    }
  }
})
</script>
