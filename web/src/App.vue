<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '@/features/auth/authStore'
import { useAppThemeController } from '@/shared/appTheme'
import { notice } from '@/shared/notice'
import { tr } from '@/i18n'
import { Cat, Layers, BookOpen, ChartNoAxesCombined, KeyRound, Receipt, UserRound, Users, Settings, Moon, Sun, LogOut } from 'lucide-vue-next'
import AppConfirmDialog from '@/components/AppConfirmDialog.vue'
import AppNotice from '@/components/AppNotice.vue'
const auth=useAuthStore()
const theme=useAppThemeController()
const links=computed(()=>[
  ...(auth.isLoggedIn ? [{path:'/platform/usage',label:'用量概览',icon:ChartNoAxesCombined},{path:'/platform/keys',label:'API Keys',icon:KeyRound}]:[]),
  {path:'/platform/models',label:'模型目录',icon:Layers},{path:'/platform/docs',label:'接口文档',icon:BookOpen},
  ...(auth.isLoggedIn ? [{path:'/billing',label:'消费账单',icon:Receipt},{path:'/orders',label:'充值订单',icon:Receipt},{path:'/profile',label:'个人账户',icon:UserRound},{path:'/legacy-works',label:'历史作品迁移',icon:Layers}]:[{path:'/login',label:'登录',icon:UserRound}]),
  ...(auth.isSuperAdmin ? [{path:'/users',label:'用户管理',icon:Users},{path:'/settings',label:'模型配置',icon:Settings}]:[]),
])
</script>
<template>
  <div class="console-shell">
    <aside class="console-nav">
      <RouterLink class="console-brand" to="/platform/models"><Cat :size="28"/><span>Cat API<small>模型开放平台</small></span></RouterLink>
      <nav aria-label="主导航"><RouterLink v-for="link in links" :key="link.path" :to="link.path"><component :is="link.icon" :size="19"/><span>{{tr(link.label)}}</span></RouterLink></nav>
      <div class="console-nav-footer">
        <RouterLink v-if="auth.user" to="/profile" class="console-user"><span>{{auth.user.nickname || auth.user.username}}</span><strong>¥ {{Number(auth.balance).toFixed(2)}}</strong></RouterLink>
        <button type="button" aria-label="切换明暗主题" @click="theme.setPreference(theme.resolvedTheme.value==='dark'?'light':'dark')"><Sun v-if="theme.resolvedTheme.value==='dark'" :size="18"/><Moon v-else :size="18"/><span>切换外观</span></button>
        <button v-if="auth.isLoggedIn" type="button" @click="auth.logout()"><LogOut :size="18"/><span>退出登录</span></button>
      </div>
    </aside>
    <div class="console-content"><RouterView/></div>
    <div class="console-notices" aria-live="polite"><AppNotice v-for="item in notice.state.notices" :key="item.id" :item="item"/></div>
    <AppConfirmDialog/>
  </div>
</template>
