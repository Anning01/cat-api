import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { i18n, setLocale } from '@/i18n'
import { useAuthStore } from './authStore'
import PhoneLogin from './PhoneLogin.vue'
import { request } from '@/api'

vi.mock('@/api',()=>({request:vi.fn(),getAuthToken:()=>null}))
afterEach(()=>vi.clearAllMocks())
function setup(bind=false,agreed=true){
 const pinia=createPinia();setActivePinia(pinia);setLocale('zh')
 const auth=useAuthStore();auth.legalReady=true;auth.phoneSignupEnabled=true
 return mount(PhoneLogin,{props:{bind,agreed},global:{plugins:[pinia,i18n]},attachTo:document.body})
}
it('requires consent before spending an SMS and preserves leading zero codes',async()=>{
 const wrapper=setup(false,false)
 await wrapper.get('input[name=phone]').setValue('13800138000')
 await wrapper.findAll('button')[0]!.trigger('click')
 expect(request).not.toHaveBeenCalled()
 expect(wrapper.get('[role=alert]').text()).toContain('同意')
 await wrapper.setProps({agreed:true})
 vi.mocked(request).mockResolvedValueOnce({data:{challenge:'challenge'}})
 await wrapper.findAll('button')[0]!.trigger('click');await flushPromises()
 expect(wrapper.get('input[name=code]').attributes('type')).toBe('text')
 expect(wrapper.get('input[name=code]').attributes('autocomplete')).toBe('one-time-code')
 await wrapper.get('input[name=code]').setValue('012345')
 vi.mocked(request).mockResolvedValueOnce({data:{token:'session',user:{id:1}}})
 await wrapper.get('form').trigger('submit');await flushPromises()
 const args=vi.mocked(request).mock.calls[1]!
 expect(args[0]).toBe('/auth/phone/login')
 expect(JSON.parse(String(args[1]?.body))).toMatchObject({code:'012345',register:false,agreed:true})
 expect(wrapper.emitted('authenticated')).toHaveLength(1)
 wrapper.unmount()
})
it('changing a phone number invalidates its challenge and never submits the old code',async()=>{
 const wrapper=setup(true)
 await wrapper.get('input[name=phone]').setValue('13800138000')
 vi.mocked(request).mockResolvedValueOnce({data:{challenge:'original'}})
 await wrapper.findAll('button')[0]!.trigger('click');await flushPromises()
 await wrapper.get('input[name=phone]').setValue('13900139000')
 await wrapper.get('input[name=code]').setValue('012345')
 await wrapper.get('form').trigger('submit');await flushPromises()
 expect(request).toHaveBeenCalledTimes(1)
 expect(wrapper.get('[role=alert]').text()).toContain('先获取')
 expect(wrapper.find('input[name=register]').exists()).toBe(false)
 wrapper.unmount()
})
