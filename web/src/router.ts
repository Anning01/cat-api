import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '@/features/auth/authStore'
import { notice } from '@/shared/notice'
const router=createRouter({history:createWebHashHistory(),routes:[
  ...(['usage','models','docs','keys'] as const).map(section=>({path:'/platform/'+section,component:()=>import('./pages/PlatformConsolePage.vue'),props:{section},meta:{public:['models','docs'].includes(section)}})),
  ...(['profile','orders','billing'] as const).map(section=>({path:'/'+section,component:()=>import('./pages/AccountPage.vue'),props:{section},meta:{}})),
  {path:'/users',component:()=>import('./pages/UserManagementPage.vue'),meta:{admin:true}},
  {path:'/projects',redirect:'/legacy-works'},
  {path:'/legacy-works',component:()=>import('./pages/LegacyWorksPage.vue')},
  {path:'/login',component:()=>import('./pages/LoginPage.vue'),meta:{public:true}},
  {path:'/settings',component:()=>import('./pages/ConfigPage.vue'),meta:{admin:true}},
  {path:'/:pathMatch(.*)*',redirect:'/platform/models'},
]})
router.beforeEach(async to=>{
  const auth=useAuthStore()
  await auth.bootstrap()
  if (to.path==='/legacy-works'&&!auth.legacyWorksEnabled) return '/platform/models'
  if (!to.meta.public && !auth.isLoggedIn) return {path:'/login',query:{redirect:to.fullPath}}
  if (to.meta.admin && !auth.isSuperAdmin) return '/platform/models'
  return true
})
router.onError(()=>notice.error('页面暂时无法加载，请刷新后重试'))
export default router
