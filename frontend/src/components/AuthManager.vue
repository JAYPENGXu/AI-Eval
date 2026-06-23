<template>
  <AuthPanel v-if="!access" :auth="auth" :error="error" :personas="personas" :persona-loading="personaLoading" @login="login" @register="register" @persona-login="loginAsPersona" />
  <section v-else-if="bootstrapping" class="auth auth-switching" role="status" aria-live="polite">
    <div class="auth-switching-status">
      <span class="auth-switching-spinner" aria-hidden="true"></span>
      <strong>正在加载当前身份...</strong>
    </div>
  </section>
  <slot v-else :user="user" :logout="logout"></slot>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import type { DemoPersona } from '../types/api'
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
const personas = ref<DemoPersona[]>([])
const personaLoading = ref('')
const bootstrapping = ref(false)

async function activateSession(token: { access: string; refresh: string }) {
  bootstrapping.value = true
  authStore.setTokens(token)
  try {
    await props.bootstrap()
  } catch (err) {
    logout()
    throw err
  } finally {
    bootstrapping.value = false
  }
}


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
    await activateSession(token)
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  }
}

async function loginAsPersona(username: string) {
  error.value = ''
  personaLoading.value = username
  try {
    const token = await api.personaLogin(username)
    await activateSession(token)
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    personaLoading.value = ''
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
  bootstrapping.value = false
  authStore.logout()
}

onMounted(async () => {
  if (!access.value) {
    try {
      personas.value = (await api.demoPersonas()).personas
    } catch {
      personas.value = []
    }
  }
  if (access.value) {
    bootstrapping.value = true
    try {
      await props.bootstrap()
    } catch {
      logout()
    } finally {
      bootstrapping.value = false
    }
  }
})
</script>
