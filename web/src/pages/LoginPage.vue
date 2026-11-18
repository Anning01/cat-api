<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowUpRight, BookOpen, ChevronDown, Layers, MessageCircle, ScanLine, Smartphone } from 'lucide-vue-next'
import { tr } from '@/i18n'
import QilingLogin from '@/features/auth/QilingLogin.vue'
import PhoneLogin from '@/features/auth/PhoneLogin.vue'
import WechatLogin from '@/features/auth/WechatLogin.vue'
import LoginAgreement from '@/features/auth/LoginAgreement.vue'
import AppButton from '@/components/AppButton.vue'
import ConsolePreferences from '@/components/ConsolePreferences.vue'
import { useAuthStore } from '@/features/auth/authStore'
import type { LoginResult } from '@/types'

const props = defineProps<{ embedded?: boolean }>()
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const formId = useId()
const username = ref('')
const password = ref('')
const agreed = ref(false)
const busy = ref(false)
const error = ref('')
const links = [
  { path: '/platform/models', label: '模型目录', icon: Layers },
  { path: '/platform/docs', label: '接口文档', icon: BookOpen },
  { path: '/contact', label: '联系我们', icon: MessageCircle },
]
const title = computed(() => !auth.phoneEnabled && auth.provider === 'qiling' ? '器灵扫码登录' : '登录控制台')
const legacyAvailable = computed(() => !auth.wechatEnabled && (auth.qilingEnabled || auth.provider === 'password'))
const method = ref(route.query.method === 'phone' && auth.phoneEnabled ? 'phone'
  : auth.wechatEnabled ? 'wechat'
  : auth.provider === 'phone' || auth.provider === 'wechat' ? 'phone' : 'legacy')
const hasMethodOptions = computed(() => [auth.wechatEnabled, auth.phoneEnabled, legacyAvailable.value].filter(Boolean).length > 1)
const activeWechat = computed(() => method.value === 'wechat' && auth.wechatEnabled)
const activePhone = computed(() => method.value === 'phone' && auth.phoneEnabled)
const activePassword = computed(() => method.value === 'legacy' && auth.provider === 'password')

watch(() => route.query.method, value => {
  if (value === 'phone' && auth.phoneEnabled) method.value = 'phone'
  if (value === 'wechat' && auth.wechatEnabled) method.value = 'wechat'
})

function destination() {
  const value = String(route.query.redirect || '/platform/usage')
  return value.startsWith('/') && !value.startsWith('//') ? value : '/platform/usage'
}

async function accept(session: LoginResult) {
  error.value = ''
  try {
    await auth.acceptSession(session)
    if (!props.embedded || route.path === '/login') await router.replace(destination())
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : tr('登录失败，请重试')
  }
}

async function login() {
  busy.value = true
  error.value = ''
  try {
    await auth.login(username.value, password.value)
    await router.replace(destination())
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : tr('登录失败，请重试')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div :class="embedded ? 'sign-in-embedded' : 'sign-in-page'">
    <aside v-if="!embedded" class="sign-in-brand">
      <RouterLink to="/platform/models" class="sign-in-wordmark">Cat API</RouterLink>
      <div class="sign-in-brand-main">
        <div class="sign-in-art" aria-hidden="true">
          <img src="/logo.png" alt="" width="1254" height="1254" />
        </div>
        <p class="sign-in-brand-title">{{ tr('模型开放平台') }}</p>
        <p class="sign-in-brand-subtitle">{{ tr('文本、图像与视频模型 API') }}</p>
      </div>
      <nav class="sign-in-links" :aria-label="tr('开发接入')">
        <RouterLink v-for="link in links" :key="link.path" :to="link.path">
          <component :is="link.icon" :size="17" aria-hidden="true" />
          {{ tr(link.label) }}
          <ArrowUpRight :size="14" aria-hidden="true" />
        </RouterLink>
      </nav>
    </aside>

    <component :is="embedded ? 'div' : 'main'" :class="embedded ? undefined : 'sign-in-main'">
      <header v-if="!embedded" class="sign-in-tools">
        <RouterLink to="/platform/models" class="sign-in-wordmark sign-in-compact-brand">
          <img src="/logo.png" alt="" width="34" height="34" />
          Cat API
        </RouterLink>
        <ConsolePreferences />
      </header>

      <div class="sign-in-content">
        <header v-if="!embedded" class="sign-in-heading">
          <h1 id="console-page-title" tabindex="-1">{{ tr(title) }}</h1>
          <p v-if="auth.wechatEnabled" class="sign-in-upgrade">{{ tr('新版微信扫码登录已启用') }}</p>
          <p v-else-if="auth.provider==='wechat' && auth.phoneEnabled">{{ tr('微信扫码暂不可用，请使用手机验证码登录。') }}</p>
        </header>

        <div v-if="hasMethodOptions" role="group" class="sign-in-methods" :aria-label="tr('登录方式')">
          <AppButton v-if="auth.wechatEnabled" type="button" variant="ghost" :aria-pressed="activeWechat" @click="method='wechat'">
            <ScanLine :size="16" aria-hidden="true" />{{ tr('微信登录') }}
          </AppButton>
          <AppButton v-if="auth.phoneEnabled" type="button" variant="ghost" :aria-pressed="activePhone" @click="method='phone'">
            <Smartphone :size="16" aria-hidden="true" />{{ tr('手机验证码登录') }}
          </AppButton>
          <AppButton v-if="legacyAvailable" type="button" variant="ghost" :aria-pressed="method==='legacy'" @click="method='legacy'">
            {{ tr(auth.provider==='password'?'密码登录':'老用户登录') }}
          </AppButton>
        </div>

        <template v-if="activeWechat">
          <WechatLogin :agreed="agreed" @authenticated="accept" />
          <LoginAgreement v-if="auth.legalReady" v-model="agreed" class="sign-in-qr-agreement" />
        </template>
        <PhoneLogin v-else-if="activePhone" :agreed="agreed" @authenticated="accept">
          <template v-if="auth.legalReady" #agreement>
            <LoginAgreement v-model="agreed" />
          </template>
        </PhoneLogin>
        <p v-else-if="method==='phone'" class="sign-in-hint" role="status">{{ tr('手机验证码登录尚未配置') }}</p>
        <template v-else-if="auth.provider==='qiling'">
          <p v-if="!auth.qilingEnabled" class="sign-in-hint" role="status">{{ tr('器灵登录尚未配置，请联系管理员。') }}</p>
          <QilingLogin v-else-if="!auth.legalReady || agreed" auto-start @authenticated="accept" />
          <p v-else class="sign-in-hint">{{ tr('同意下方协议后，即可使用微信扫码登录。') }}</p>
          <LoginAgreement v-if="auth.legalReady" v-model="agreed" />
        </template>
        <form v-else-if="activePassword" class="sign-in-password" @submit.prevent="login">
          <label :for="formId+'-username'">{{ tr('用户名') }}
            <input :id="formId+'-username'" v-model="username" name="username" autocomplete="username" autocapitalize="none" :spellcheck="false" required />
          </label>
          <label :for="formId+'-password'">{{ tr('密码') }}
            <input :id="formId+'-password'" v-model="password" name="password" type="password" autocomplete="current-password" required />
          </label>
          <LoginAgreement v-if="auth.legalReady" v-model="agreed" />
          <AppButton type="submit" :loading="busy" :disabled="auth.legalReady&&!agreed" variant="primary" block>{{ tr('登录') }}</AppButton>
        </form>

        <p v-if="!auth.legalReady" class="sign-in-hint">{{ tr('当前部署尚未配置协议文档。') }}</p>
        <p v-if="error" class="console-error" role="alert">{{ error }}</p>

        <details v-if="auth.phoneEnabled && (activeWechat || activePhone)" class="sign-in-help">
          <summary>{{ tr('老账号无法登录？') }}<ChevronDown :size="14" aria-hidden="true" /></summary>
          <p>{{ tr(auth.wechatEnabled||auth.provider==='wechat'
            ? '老账号请使用已绑定的手机号。还未绑定且已退出登录，请联系支持找回原账号。'
            : '老用户请先通过原登录入口进入个人中心绑定手机，避免创建新账号。') }}</p>
          <RouterLink class="sign-in-support" to="/contact">{{ tr('联系我们') }}</RouterLink>
        </details>
      </div>

      <nav v-if="!embedded" class="sign-in-links sign-in-compact-links" :aria-label="tr('开发接入')">
        <RouterLink v-for="link in links" :key="link.path" :to="link.path">
          {{ tr(link.label) }}<ArrowUpRight :size="14" aria-hidden="true" />
        </RouterLink>
      </nav>
    </component>
  </div>
</template>

<style scoped>
.sign-in-page{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,6fr);block-size:100vh;block-size:100dvh;overflow:auto;background:var(--app-surface)}
.sign-in-brand{display:grid;grid-template-rows:auto 1fr auto;gap:24px;margin:16px 0 16px 16px;padding:clamp(24px,4vw,60px);border-radius:16px;background:var(--app-accent-soft);color:var(--app-text)}
.sign-in-wordmark{display:inline-flex;align-items:center;gap:6px;justify-self:start;min-block-size:44px;color:inherit;font-size:1.6rem;font-weight:800;letter-spacing:-.025em;text-decoration:none}
.sign-in-brand-main{display:grid;align-content:center;justify-items:center;gap:10px;text-align:center}
.sign-in-art{display:grid;position:relative;place-items:center;inline-size:min(100%,27rem);aspect-ratio:1.63;margin-block-end:10px}
.sign-in-art::before{content:"";inline-size:64%;aspect-ratio:1;border-radius:50%;background:color-mix(in srgb,var(--app-accent) 9%,var(--app-accent-soft))}
.sign-in-art img{position:absolute;inline-size:116%;block-size:auto;max-inline-size:none}
.sign-in-brand-title{position:relative;margin:0;font-size:clamp(1.85rem,3.2vw,3.25rem);font-weight:750;letter-spacing:-.035em;line-height:1.22}
.sign-in-brand-subtitle{margin:0;color:var(--app-text-secondary);font-size:1.05rem}
.sign-in-links{display:flex;align-items:center;flex-wrap:wrap;gap:8px 22px;padding-block-start:12px;border-block-start:1px solid var(--app-border)}
.sign-in-links a{display:inline-flex;align-items:center;gap:8px;min-block-size:44px;color:var(--app-text);font-size:13px;font-weight:600;text-decoration:none}
.sign-in-links a:hover{color:var(--app-accent);text-decoration:underline;text-underline-offset:4px}
.sign-in-main{display:grid;grid-template-rows:auto 1fr;min-inline-size:0;padding:24px clamp(24px,5vw,64px)}
.sign-in-tools{display:flex;justify-content:flex-end;align-items:center;gap:12px}
.sign-in-compact-brand,.sign-in-compact-links{display:none}
.sign-in-content{display:grid;align-self:center;gap:22px;inline-size:min(100%,25.5rem);min-inline-size:0;margin-inline:auto;padding-block:40px 72px}
.sign-in-heading{display:grid;gap:10px}
.sign-in-heading h1{margin:0;color:var(--app-text);font-size:clamp(2rem,3vw,2.55rem);font-weight:750;letter-spacing:-.035em;line-height:1.22}
.sign-in-heading p,.sign-in-hint{margin:0;color:var(--app-text-secondary);font-size:13px;line-height:1.6}
.sign-in-heading .sign-in-upgrade{color:var(--app-danger);font-weight:600}
.sign-in-methods{display:flex;flex-wrap:wrap;gap:4px;padding:4px;border-radius:10px;background:var(--app-surface-muted)}
.sign-in-methods :deep(button){flex:1 1 max-content;min-block-size:42px;padding-inline:10px;border-radius:7px;color:var(--app-text-secondary);white-space:normal}
.sign-in-methods :deep(button[aria-pressed='true']){background:var(--app-surface);color:var(--app-accent);box-shadow:0 1px 2px rgb(22 24 44 / 13%);font-weight:700}
.sign-in-qr-agreement{justify-self:center}
.sign-in-content :deep(.qiling-login){justify-items:center;text-align:center}
.sign-in-help{border-block-start:1px solid var(--app-border);color:var(--app-text-secondary);font-size:13px;line-height:1.6}
.sign-in-help summary{display:flex;align-items:center;justify-content:space-between;gap:8px;min-block-size:44px;color:var(--app-text-secondary);font-weight:600;cursor:pointer;list-style:none}
.sign-in-help summary::-webkit-details-marker{display:none}
.sign-in-help[open] summary svg{transform:rotate(180deg)}
.sign-in-help p{margin:0}
.sign-in-support{display:inline-block;margin-block-start:8px;color:var(--app-accent);text-decoration:underline;text-underline-offset:3px}
.sign-in-password,.sign-in-password label{display:grid;gap:8px}
.sign-in-password{gap:16px}
.sign-in-password input{inline-size:100%;min-block-size:48px;padding:8px 12px;border:1px solid var(--app-border);border-radius:8px;background:var(--app-surface);color:var(--app-text);font-size:max(1rem,16px)}
.sign-in-password :deep(button[type='submit']){min-block-size:48px}
.sign-in-embedded .sign-in-content{inline-size:100%;padding:0;gap:16px}

@media(max-width:860px){
  .sign-in-page{grid-template-columns:minmax(0,1fr)}
  .sign-in-brand{display:none}
  .sign-in-main{grid-template-rows:auto 1fr auto;padding:16px clamp(16px,5vw,32px)}
  .sign-in-tools{justify-content:space-between;flex-wrap:wrap;font-size:13px}
  .sign-in-compact-brand{display:inline-flex;font-size:1.35rem}
  .sign-in-compact-links{display:flex;justify-content:center}
  .sign-in-content{align-self:start;padding-block:clamp(32px,8dvh,72px) 32px}
}
@media(max-width:440px){
  .sign-in-tools :deep(.console-preferences){gap:8px}
  .sign-in-tools :deep(.console-preferences > label > svg){display:none}
}
</style>
