<script setup lang="ts">
import { computed, nextTick, ref, watch, watchEffect } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElConfigProvider } from 'element-plus'
import { Cat, Layers, BookOpen, ChartNoAxesCombined, KeyRound, Receipt, UserRound, Users, Settings, LogOut, PanelLeftClose, Menu, ChevronDown } from 'lucide-vue-next'
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
const auth = useAuthStore(), theme = useAppThemeController(), route = useRoute(), router = useRouter()
const mobileNav = ref(false), collapsed = ref(false)
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
  <div class="console-shell" :class="{ 'is-collapsed': collapsed, 'is-nav-open': mobileNav }" @keydown.esc="mobileNav = false">
    <aside id="console-navigation" class="console-nav">
      <RouterLink class="console-brand" to="/platform/models"><Cat :size="30" aria-hidden="true"/><span>Cat API</span></RouterLink>
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
      <div id="main-content" class="console-content"><RouterView/></div>
    </div>
    <RechargeDialog v-if="auth.isLoggedIn" v-model="rechargeOpen"/>
    <div class="console-notices" aria-live="polite"><AppNotice v-for="item in notice.state.notices" :key="item.id" :item="item"/></div>
    <AppConfirmDialog :dark="theme.resolvedTheme.value === 'dark'"/>
  </div>
  </ElConfigProvider>
</template>
