<script setup lang="ts">
import { useId, ref } from 'vue'
import { tr } from '@/i18n'
import { useRoute, useRouter } from 'vue-router'
import { ScanLine } from 'lucide-vue-next'
import QilingLogin from '@/features/auth/QilingLogin.vue'
import AppButton from '@/components/AppButton.vue'
import ConsolePreferences from '@/components/ConsolePreferences.vue'
import { useAuthStore } from '@/features/auth/authStore'
import type { LoginResult } from '@/types'
const auth=useAuthStore(), router=useRouter(), route=useRoute()
const username=ref(''), password=ref(''), agreed=ref(false), busy=ref(false), error=ref('')
function destination(){ const value=String(route.query.redirect || '/platform/usage'); return value.startsWith('/')&&!value.startsWith('//')?value:'/platform/usage' }
async function accept(session:LoginResult){await auth.acceptSession(session);await router.replace(destination())}
async function login(){busy.value=true;error.value='';try{await auth.login(username.value,password.value);await router.replace(destination())}catch(e){error.value=e instanceof Error?e.message:'登录失败'}finally{busy.value=false}}
const formId=useId()
</script>
<template><main class="account-page login-page"><section class="account-card login-card"><header class="login-heading"><ScanLine v-if="auth.provider==='qiling'" :size="32" aria-hidden="true"/><h1 id="console-page-title" tabindex="-1">{{ tr(auth.provider==='qiling'?'器灵扫码登录':'登录控制台') }}</h1></header>
<template v-if="auth.provider==='qiling'">
  <p v-if="!auth.qilingEnabled" class="muted" role="status">{{ tr('器灵登录尚未配置，请联系管理员。') }}</p>
  <QilingLogin v-else-if="!auth.legalReady || agreed" auto-start @authenticated="accept"/>
  <p v-else class="muted">{{ tr('同意下方协议后，即可使用微信扫码登录。') }}</p>
</template>
<form v-else-if="auth.provider==='password'" @submit.prevent="login"><label :for="formId+'-field-1'">{{ tr('用户名') }}<input name="field-1" :id="formId+'-field-1'" v-model="username" autocorrect="off" autocapitalize="none" :spellcheck="false" required autocomplete="username"></label><label :for="formId+'-field-2'">{{ tr('密码') }}<input name="field-2" :id="formId+'-field-2'" v-model="password" type="password" required autocomplete="current-password"></label><AppButton type="submit" :loading="busy" :disabled="auth.legalReady&&!agreed" variant="primary">{{ tr('登录') }}</AppButton></form>
<label v-if="auth.legalReady" :for="formId+'-field-3'" class="legal-choice"><input name="field-3" :id="formId+'-field-3'" v-model="agreed" type="checkbox">{{ tr('我已阅读并同意') }} <a href="/api/auth/legal/terms" target="_blank" rel="noopener">{{ tr('用户协议') }}</a> {{ tr('和') }} <a href="/api/auth/legal/privacy" target="_blank" rel="noopener">{{ tr('隐私政策') }}</a></label><p v-else class="muted">{{ tr('当前部署尚未配置协议文档。') }}</p><p v-if="error" role="alert">{{error}}</p><div class="console-mobile-preferences"><ConsolePreferences expanded/></div></section></main></template>
