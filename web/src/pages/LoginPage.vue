<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import QilingLogin from '@/features/auth/QilingLogin.vue'
import AppButton from '@/components/AppButton.vue'
import { useAuthStore } from '@/features/auth/authStore'
import type { LoginResult } from '@/types'
const auth=useAuthStore(), router=useRouter(), route=useRoute()
const username=ref(''), password=ref(''), agreed=ref(false), busy=ref(false), error=ref('')
function destination(){ const value=String(route.query.redirect || '/platform/usage'); return value.startsWith('/')&&!value.startsWith('//')?value:'/platform/usage' }
async function accept(session:LoginResult){await auth.acceptSession(session);await router.replace(destination())}
async function login(){busy.value=true;error.value='';try{await auth.login(username.value,password.value);await router.replace(destination())}catch(e){error.value=e instanceof Error?e.message:'登录失败'}finally{busy.value=false}}
</script>
<template><main class="account-page login-page"><section class="account-card login-card"><span class="eyebrow">WELCOME TO CAT API</span><h1>连接创作的每一种可能</h1><p class="muted">一个账户，调用文本、图片与视频模型。</p>
<QilingLogin v-if="auth.provider==='qiling'&&agreed" @authenticated="accept"/>
<form v-else-if="auth.provider==='password'" @submit.prevent="login"><label>用户名<input v-model="username" required autocomplete="username"></label><label>密码<input v-model="password" type="password" required autocomplete="current-password"></label><AppButton type="submit" :loading="busy" :disabled="!agreed">登录</AppButton></form>
<label class="legal-choice"><input v-model="agreed" type="checkbox">我已阅读并同意 <a href="/api/auth/legal/terms" target="_blank" rel="noopener">用户协议</a> 和 <a href="/api/auth/legal/privacy" target="_blank" rel="noopener">隐私政策</a></label><p v-if="error" role="alert">{{error}}</p></section></main></template>
