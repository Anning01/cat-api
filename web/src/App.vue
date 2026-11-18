<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, ref, watch, watchEffect } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElConfigProvider } from 'element-plus'
import { Layers, BookOpen, ChartNoAxesCombined, KeyRound, Receipt, UserRound, Users, Settings, LogOut, PanelLeftClose, Menu, ChevronDown, MessageCircle } from 'lucide-vue-next'
import { useAuthStore } from '@/features/auth/authStore'
import { useAppThemeController } from '@/shared/appTheme'
import { rechargeOpen, money } from '@/shared/console'
import { notice } from '@/shared/notice'
import { tr, elementLocale } from '@/i18n'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import ConsolePreferences from '@/components/ConsolePreferences.vue'
import AppDialog from '@/components/AppDialog.vue'
import RechargeDialog from '@/features/account/RechargeDialog.vue'
import AppConfirmDialog from '@/components/AppConfirmDialog.vue'
import AppNotice from '@/components/AppNotice.vue'
import WechatLogin from '@/features/auth/WechatLogin.vue'
import type { LoginResult } from '@/types'
const LoginPage = defineAsyncComponent(() => import('@/pages/LoginPage.vue'))
const auth = useAuthStore(), theme = useAppThemeController(), route = useRoute(), router = useRouter()
const mobileNav = ref(false), collapsed = ref(false)
const loginPrompt = ref(false), bindError = ref('')
const standaloneLogin = computed(() => route.path === '/login' && !auth.isLoggedIn)
const loginAudience = computed(() => {
  if (!auth.ready || !auth.wechatEnabled) return null
  if (!auth.isLoggedIn) return route.path === '/contact' ? null : 'guest'
  return auth.qilingBound && !auth.wechatBound ? auth.user?.id ?? null : null
})
const migrationTitle = computed(() => tr(loginAudience.value==='guest'?'新版微信扫码登录':'请切换到新版微信登录'))
watch(loginAudience, audience => {
  bindError.value = ''
  loginPrompt.value = audience !== null
}, { immediate:true })
async function finishWechatBinding(session: LoginResult) {
  bindError.value = ''
  try {
    await auth.acceptSession(session)
    notice.success(tr('微信已绑定，下次可直接扫码登录。'))
    if (route.path === '/login') await router.replace('/platform/usage')
  } catch (cause) {
    bindError.value = cause instanceof Error ? cause.message : tr('登录失败，请重试')
  }
}
const name = computed(() => auth.user?.nickname || auth.user?.username || '')
const groups = computed(() => [
  { title: '开发接入', links: [
    ...(auth.isLoggedIn ? [{ path: '/platform/usage', label: '用量概览', icon: ChartNoAxesCombined }] : []),
    { path: '/platform/models', label: '模型目录', icon: Layers },
    ...(auth.isLoggedIn ? [{ path: '/platform/keys', label: 'API Keys', icon: KeyRound }] : []),
    { path: '/platform/docs', label: '接口文档', icon: BookOpen },
  ] },
  ...(auth.isLoggedIn ? [{ title: '账户与费用', links: [
    { path: '/profile', label: '个人中心', icon: UserRound }, { path: '/orders', label: '充值订单', icon: Receipt }, { path: '/billing', label: '消费账单', icon: Receipt },
  ] }] : [{title:'账户与费用',links:[{path:'/login',label:'登录控制台',icon:UserRound}]}]),
  ...(auth.isSuperAdmin ? [{ title: '平台管理', links: [{ path: '/users', label: '用户管理', icon: Users }, { path: '/settings', label: '模型配置', icon: Settings }] }] : []),
  ...(auth.isLoggedIn && auth.legacyWorksEnabled ? [{ title: '历史兼容', links: [{ path: '/legacy-works', label: '历史作品迁移', icon: Layers }] }] : []),
  { title: '帮助', links: [{ path: '/contact', label: '联系我们', icon: MessageCircle }] },
])
const current = computed(() => groups.value.flatMap(group => group.links.map(link => ({ ...link, group: group.title }))).find(link => link.path === route.path))
watchEffect(()=>{document.title=tr(current.value?.label||'登录')+' · Cat API'})
function focusContent(){document.getElementById('console-page-title')?.focus()}
watch(()=>route.path,async()=>{await nextTick();const content=document.getElementById('main-content');if(content)content.scrollTop=0})
watch(() => route.fullPath, () => {
  mobileNav.value = false
  if (route.query.recharge === '1' && auth.isLoggedIn) {
    rechargeOpen.value = true
    const query = { ...route.query }; delete query.recharge
    void router.replace({ path: route.path, query })
  }
}, { immediate: true })
</script>
<template>
  <ElConfigProvider :locale="elementLocale">
    <a href="#console-page-title" class="console-skip-link" @click.prevent="focusContent">{{ tr('跳转到内容') }}</a>
  <RouterView v-if="standaloneLogin"/>
  <div v-else class="console-shell" :class="{ 'is-collapsed': collapsed, 'is-nav-open': mobileNav }" @keydown.esc="mobileNav = false">
    <aside id="console-navigation" class="console-nav">
      <RouterLink class="console-brand" to="/platform/models"><img src="/logo.png" alt="" width="36" height="36"/><span>Cat API</span></RouterLink>
      <nav :aria-label="tr('主导航')"><section v-for="group in groups" :key="group.title" class="console-nav-group"><h2>{{ tr(group.title) }}</h2><RouterLink v-for="link in group.links" :key="link.path" :to="link.path" :title="tr(link.label)"><component :is="link.icon" :size="18" aria-hidden="true"/><span>{{ tr(link.label) }}</span></RouterLink></section></nav>
      <div class="console-nav-footer"><RouterLink v-if="auth.user" to="/profile" class="console-user"><AppAvatar :name="name" :src="auth.user.avatar_url"/><span>{{ tr(auth.isSuperAdmin ? '超级管理员' : '普通用户') }}</span></RouterLink><button class="console-collapse" type="button" :aria-label="tr(collapsed ? '展开导航' : '收起导航')" :aria-expanded="!collapsed" @click="collapsed = !collapsed"><PanelLeftClose :size="17"/><span>{{ tr('收起导航') }}</span></button></div>
    </aside>
    <AppDialog id="console-mobile-navigation" v-model="mobileNav" drawer side="left" size="260px" :title="tr('主导航')" class="console-mobile-navigation">
      <nav :aria-label="tr('主导航')"><section v-for="group in groups" :key="group.title" class="console-nav-group"><h2>{{ tr(group.title) }}</h2><RouterLink v-for="link in group.links" :key="link.path" :to="link.path" @click="mobileNav=false"><component :is="link.icon" :size="18" aria-hidden="true"/><span>{{ tr(link.label) }}</span></RouterLink></section></nav>
    </AppDialog>
    <div class="console-workspace">
      <header class="console-topbar">
        <button class="console-mobile-menu" type="button" :aria-label="tr('打开导航')" :aria-expanded="mobileNav" aria-controls="console-mobile-navigation" @click="mobileNav = !mobileNav"><Menu :size="20"/></button>
        <div class="console-breadcrumb"><span v-if="current">{{ tr(current.group) }} <span aria-hidden="true">/</span></span><strong>{{ tr(current?.label || '登录') }}</strong></div>
        <div class="console-utilities">
          <div v-if="auth.isLoggedIn" class="console-wallet"><span>{{ tr('我的余额') }} <strong :title="'¥ ' + money(auth.balance)">¥{{ money(auth.balance, 2) }}</strong></span><AppButton variant="primary" size="sm" @click="rechargeOpen = true">{{ tr('充值') }}</AppButton></div>
          <div class="console-top-preferences"><ConsolePreferences/></div>
          <details v-if="auth.user" class="console-account-menu"><summary :aria-label="tr('账户菜单')+' · '+name"><AppAvatar :name="name" :src="auth.user.avatar_url" :size="30"/><span>{{ name }}</span><ChevronDown :size="14"/></summary><div class="console-account-popover"><RouterLink to="/profile">{{ tr('个人中心') }}</RouterLink><div class="console-mobile-preferences"><ConsolePreferences expanded/></div><button type="button" @click="auth.logout()"><LogOut :size="16"/>{{ tr('退出登录') }}</button></div></details>
          <RouterLink v-else class="console-login-link" to="/login">{{ tr('登录') }}</RouterLink>
        </div>
      </header>
      <div id="main-content" class="console-content">
        <div v-if="loginAudience!==null && route.path!=='/login'" class="phone-migration-reminder wechat-migration-reminder">
          <strong>{{ migrationTitle }}</strong>
          <AppButton size="sm" variant="danger" @click="loginPrompt=true">{{ tr(loginAudience==='guest'?'打开登录':'扫码绑定微信') }}</AppButton>
        </div>
        <p v-else-if="loginAudience===null&&auth.isLoggedIn&&auth.phoneEnabled&&!auth.phoneMasked&&route.path!=='/profile'" class="phone-migration-reminder" role="status">{{ tr('请绑定手机号，后续将使用手机号登录。') }} <RouterLink to="/profile">{{ tr('前往绑定') }}</RouterLink></p>
        <RouterView v-if="route.path!=='/login'||!loginPrompt"/>
      </div>
    </div>
    <RechargeDialog v-if="auth.isLoggedIn" v-model="rechargeOpen"/>
    <AppDialog v-if="loginAudience!==null" v-model="loginPrompt" :title="migrationTitle" width="440px" class="wechat-migration-dialog">
      <LoginPage v-if="loginAudience==='guest'" embedded/>
      <template v-else>
        <p class="wechat-migration-copy">{{ tr('请绑定 Cat API 的公众号微信登录。绑定到当前账号，保留余额、账单和 API Key。') }}</p>
        <WechatLogin :key="loginAudience" bind :agreed="true" @authenticated="finishWechatBinding"/>
        <p v-if="bindError" class="console-error" role="alert">{{ bindError }}</p>
      </template>
    </AppDialog>
  </div>
    <div class="console-notices" aria-live="polite"><AppNotice v-for="item in notice.state.notices" :key="item.id" :item="item"/></div>
    <AppConfirmDialog :dark="theme.resolvedTheme.value === 'dark'"/>
  </ElConfigProvider>
</template>
<style scoped>
.phone-migration-reminder{margin:16px 24px 0;padding:12px 16px;background:var(--app-surface-muted);border:1px solid var(--app-border);border-radius:8px;font-size:13px;line-height:1.6}
.phone-migration-reminder a{margin-inline-start:8px;text-decoration:underline;text-underline-offset:3px}
.wechat-migration-reminder{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;background:var(--app-danger-soft);color:var(--app-danger);border-color:var(--app-danger)}
:global(.wechat-migration-dialog .app-dialog-header){color:var(--app-danger);background:var(--app-danger-soft);border-bottom-color:var(--app-danger)}
.wechat-migration-copy{margin:0 0 16px;font-size:14px;line-height:1.6}
</style>
