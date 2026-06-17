<template>
  <section class="auth">
    <div class="auth-hero" aria-label="RAGPilot，面向知识库问答的 RAGOps 调试、评测与优化平台。">
      <div class="auth-kicker">RAGOps Workspace</div>
      <h1 class="auth-title" aria-hidden="true">
        <span style="--i: 0">R</span>
        <span style="--i: 1">A</span>
        <span style="--i: 2">G</span>
        <span style="--i: 3">P</span>
        <span style="--i: 4">i</span>
        <span style="--i: 5">l</span>
        <span style="--i: 6">o</span>
        <span style="--i: 7">t</span>
      </h1>
      <p class="auth-subtitle">面向知识库问答的 RAGOps 调试、评测与优化平台。</p>
    </div>
    <el-form class="auth-form" @submit.prevent="$emit('login')">
      <el-input v-model="auth.username" placeholder="用户名" autocomplete="username" />
      <el-input v-model="auth.password" placeholder="密码" type="password" autocomplete="current-password" show-password />
      <el-button type="primary" native-type="submit">登录</el-button>
      <el-button native-type="button" @click="$emit('register')">注册</el-button>
      <span class="error">{{ error }}</span>
    </el-form>
  </section>
</template>

<script setup>
defineProps({
  auth: { type: Object, required: true },
  error: { type: String, default: '' },
})

defineEmits(['login', 'register'])
</script>
