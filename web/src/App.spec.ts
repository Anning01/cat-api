import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from './App.vue'
import { useAuthStore } from './features/auth/authStore'
import { i18n } from './i18n'
import { request, setAuthToken } from './api'

beforeEach(()=>{
  localStorage.clear()
  vi.stubGlobal('matchMedia',vi.fn(()=>({matches:false,addEventListener:vi.fn(),removeEventListener:vi.fn()})))
})
describe('Individual console',()=>{
  it.each([false,true])('contains only user navigation, super admin=%s', async admin=>{
    const pinia=createPinia();setActivePinia(pinia)
    const auth=useAuthStore();auth.user={id:1,username:'user',nickname:'用户',avatar_url:'',is_super_admin:admin};auth.token='fixture';auth.legacyWorksEnabled=true;auth.balance='12.123456'
    const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{template:'<div />'}}]})
    await router.push('/platform/models');await router.isReady()
    const wrapper=mount(App,{global:{plugins:[pinia,router,i18n]}})
    expect(wrapper.text()).not.toMatch(/团队|成员|短剧/)
    expect(wrapper.find('a[href="/users"]').exists()).toBe(admin)
    expect(wrapper.find('a[href="/settings"]').exists()).toBe(admin)
    expect(wrapper.find('a[href="/profile"]').exists()).toBe(true)
    expect(wrapper.find('a[href="/legacy-works"]').exists()).toBe(true)
    wrapper.unmount()
  })
  it('sends no legacy team header even if cached from the former console',async()=>{
    localStorage.setItem('novelvids_active_team','99');setAuthToken('fixture')
    const fetcher=vi.fn().mockResolvedValue({ok:true,json:async()=>({code:0,data:{balance:'1.25'}})})
    vi.stubGlobal('fetch',fetcher)
    await request('/account/balance')
    const headers=fetcher.mock.calls[0]![1].headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer fixture')
    expect(headers.has('X-Team-Id')).toBe(false)
  })
  it('reports an unavailable service instead of exposing a JSON parser error',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,json:async()=>{throw new SyntaxError('empty response')}}))
    await expect(request('/auth/status')).rejects.toThrow('服务暂时不可用，请刷新后重试')
  })

})
