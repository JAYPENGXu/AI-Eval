<template>
  <AuthPanel v-if="!store.access" :auth="auth" :error="error" @login="login" @register="register" />
  <slot v-else :user="store.user" :logout="logout"></slot>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { store } from '../main'
import AuthPanel from './AuthPanel.vue'

const props = defineProps({
  bootstrap: { type: Function, required: true },
})

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
    store.access = token.access
    store.refresh = token.refresh
    localStorage.setItem('access', token.access)
    localStorage.setItem('refresh', token.refresh)
    await props.bootstrap()
  } catch (err) {
    error.value = err.message
  }
}

async function register() {
  error.value = ''
  if (!validateAuthForm()) return
  try {
    await api.register(auth.username.trim(), auth.password)
    await login()
  } catch (err) {
    error.value = err.message
  }
}

function logout() {
  store.access = ''
  store.refresh = ''
  store.user = null
  localStorage.clear()
}

onMounted(async () => {
  if (store.access) {
    try {
      await props.bootstrap()
    } catch {
      logout()
    }
  }
})
</script>
