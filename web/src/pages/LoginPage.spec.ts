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
