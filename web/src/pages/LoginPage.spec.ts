import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useAuthStore } from '@/features/auth/authStore'
import { i18n, setLocale } from '@/i18n'
import LoginPage from './LoginPage.vue'

it.each([false,true])('only requests agreement when documents are configured, documents=%s',async legalReady=>{
  const pinia=createPinia();setActivePinia(pinia);setLocale('zh')
  const auth=useAuthStore();auth.provider='password';auth.legalReady=legalReady
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{template:'<div/>'}}]})
  await router.push('/');await router.isReady()
  const wrapper=mount(LoginPage,{global:{plugins:[pinia,router,i18n]}})
  expect(wrapper.find('input[type=checkbox]').exists()).toBe(legalReady)
  expect(wrapper.get('button[type=submit]').attributes('disabled')!==undefined).toBe(legalReady)
  wrapper.unmount()
})

it.each([false, true])('shows the Qiling scanner when consent permits, documents=%s', async legalReady => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.qilingEnabled = true
  auth.legalReady = legalReady
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: LoginPage }] })
  await router.push('/')
  const wrapper = mount(LoginPage, { global: {
    plugins: [pinia, router, i18n],
    stubs: { QilingLogin: { template: '<div data-scanner/>' } },
  } })
  expect(wrapper.find('[data-scanner]').exists()).toBe(!legalReady)
  if (legalReady) await wrapper.get('input[type=checkbox]').setValue(true)
  expect(wrapper.find('[data-scanner]').exists()).toBe(true)
  wrapper.unmount()
})
