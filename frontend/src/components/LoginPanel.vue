<script setup>
import { ref } from 'vue'
import { login } from '../api'
const emit = defineEmits(['authenticated'])
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
async function submit() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try { emit('authenticated', await login(username.value, password.value)); password.value = '' }
  catch (e) { error.value = typeof e.response?.data?.detail === 'string' ? e.response.data.detail : '登录失败，请检查服务连接' }
  finally { loading.value = false }
}
</script>

<template>
  <main class="login-page">
    <section class="login-intro"><span class="seal serif">知</span><p>知源 · 团队知识空间</p><h1 class="serif">让每一次问答，<br>都有据可循。</h1><p class="note">整理资料，追溯来源，在属于你的知识空间中开始探索。</p></section>
    <form class="login-form" @submit.prevent="submit">
      <span class="eyebrow">欢迎回来</span><h2 class="serif">登录知源</h2>
      <label for="username">用户名</label><el-input id="username" v-model="username" autocomplete="username" maxlength="120" />
      <label for="password">密码</label><el-input id="password" v-model="password" type="password" show-password autocomplete="current-password" maxlength="1024" />
      <el-alert v-if="error" :title="error" type="error" :closable="false" role="alert" />
      <el-button type="primary" native-type="submit" :loading="loading" :disabled="!username.trim() || !password">进入知识空间</el-button>
      <p class="note">账号由团队管理员分配。如需访问权限，请联系管理员。</p>
    </form>
  </main>
</template>

<style scoped>
.login-page { min-height: 100vh; display: grid; grid-template-columns: 1.15fr 1fr; align-items: center; gap: 9vw; padding: 8vw; background: var(--paper-2, #f6f3eb); box-sizing: border-box; }
.seal { display: inline-grid; place-items: center; width: 60px; height: 60px; background: #3e6f68; color: #fff; font-size: 34px; }
h1 { font-size: clamp(32px, 4vw, 58px); line-height: 1.5; font-weight: 500; margin: 28px 0; }
.login-form { display: grid; gap: 18px; max-width: 400px; padding: 36px; background: var(--paper, #fffdf8); border: 1px solid var(--hairline, #ddd6c8); }
.login-form h2 { margin: 0 0 10px; font-size: 30px; font-weight: 500; }
.eyebrow { color: #3e6f68; letter-spacing: .15em; font-size: 12px; }
.note { color: #807a6f; font-size: 13px; line-height: 1.8; }
label { font-size: 13px; margin-bottom: -10px; }
@media (max-width: 760px) { .login-page { grid-template-columns: 1fr; gap: 24px; padding: 28px; } .login-intro h1 { font-size: 28px; } .login-intro .note { display: none; } .login-form { padding: 24px; max-width: none; } }
</style>
