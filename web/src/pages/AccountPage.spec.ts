import { beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import AccountPage from './AccountPage.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { request } from '@/api'
import { i18n } from '@/i18n'
vi.mock('@/api',()=>({API_BASE:'/api',getAuthToken:()=> 'fixture',request:vi.fn(),api:{me:vi.fn()}}))
beforeEach(()=>vi.mocked(request).mockReset())
async function mountPage(section:'users'|'orders'|'billing'){
  const pinia=createPinia();setActivePinia(pinia)
  const auth=useAuthStore();auth.user={id:1,username:'admin',nickname:'管理员',avatar_url:'',is_super_admin:true};auth.token='fixture'
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{template:'<div/>'}}]});await router.push('/');await router.isReady()
  return mount(AccountPage,{props:{section},global:{plugins:[pinia,router,i18n],stubs:{ElDialog:{template:'<div/>'}}}})
}
it('shows user balances without team or member columns',async()=>{
  vi.mocked(request).mockResolvedValue({code:0,data:{items:[{id:5,username:'owner',nickname:'账户用户',status:1,balance:'12.123456',total_cost:'0.25'}],pagination:{total:1,page:1,page_size:20,pages:1}}})
  const wrapper=await mountPage('users');await flushPromises()
  expect(wrapper.text()).toContain('12.123456');expect(wrapper.text()).not.toMatch(/团队|成员/)
  expect(request).toHaveBeenCalledWith(expect.stringMatching(/^\/users\?/))
  wrapper.unmount()
})
it('shows request failure and lets the user retry',async()=>{
  vi.mocked(request).mockRejectedValueOnce(new Error('连接失败')).mockResolvedValue({code:0,data:{items:[],pagination:{total:0,page:1,page_size:20,pages:0}}})
  const wrapper=await mountPage('orders');await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('连接失败')
  await wrapper.get('[role="alert"] button').trigger('click');await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false);expect(wrapper.text()).toContain('暂无记录')
  wrapper.unmount()
})
