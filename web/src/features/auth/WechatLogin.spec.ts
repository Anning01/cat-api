import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { toDataURL } from 'qrcode'
import { i18n, setLocale } from '@/i18n'
import { request } from '@/api'
import WechatLogin from './WechatLogin.vue'
import PhoneLogin from './PhoneLogin.vue'

vi.mock('@/api',()=>({request:vi.fn(),getAuthToken:()=>null}))
vi.mock('qrcode',()=>({toDataURL:vi.fn(async()=> 'data:image/png;base64,test')}))
afterEach(()=>{vi.clearAllMocks();vi.useRealTimers();sessionStorage.clear()})
async function setup(agreed=true, bind=false){
 vi.useFakeTimers();const pinia=createPinia();setActivePinia(pinia);setLocale('zh')
 vi.mocked(request).mockResolvedValueOnce({data:{attempt:'private-poll-secret',authorization_url:'https://open.weixin.qq.com/connect/oauth2/authorize?state=public-state',expires_in:300}})
 const wrapper=mount(WechatLogin,{props:{agreed,bind},global:{plugins:[pinia,i18n],stubs:{PhoneLogin:true}}})
 await flushPromises();return wrapper
}
it('keeps the polling secret out of the QR link and passes it only to phone verification',async()=>{
 const wrapper=await setup()
 expect(toDataURL).toHaveBeenCalledWith(expect.stringContaining('state=public-state'), expect.anything())
 expect(vi.mocked(toDataURL).mock.calls[0]![0]).not.toContain('private-poll-secret')
 vi.mocked(request).mockResolvedValueOnce({data:{status:'phone_required',expires_in:250}})
 await vi.advanceTimersByTimeAsync(3000);await flushPromises()
 expect(wrapper.findComponent(PhoneLogin).props('wechatAttempt')).toBe('private-poll-secret')
 expect(wrapper.find('img').exists()).toBe(false)
 const calls=vi.mocked(request).mock.calls.length
 await vi.advanceTimersByTimeAsync(3000)
 expect(request).toHaveBeenCalledTimes(calls)
 wrapper.unmount()
})
it('shows the QR before consent and polls only after consent',async()=>{
 const wrapper=await setup(false)
 expect(wrapper.find('img').exists()).toBe(true)
 await vi.advanceTimersByTimeAsync(3000)
 expect(request).toHaveBeenCalledTimes(1)
 await wrapper.setProps({agreed:true})
 vi.mocked(request).mockResolvedValueOnce({data:{status:'pending'}})
 await vi.advanceTimersByTimeAsync(3000)
 expect(vi.mocked(request).mock.calls[1]![0]).toBe('/auth/wechat/poll')
 wrapper.unmount()
})

it('uses the authenticated binding endpoints and advances to binding the current phone',async()=>{
 const wrapper=await setup(true, true)
 expect(vi.mocked(request).mock.calls[0]![0]).toBe('/auth/wechat/bind/start')
 vi.mocked(request).mockResolvedValueOnce({data:{status:'phone_required',expires_in:250}})
 await vi.advanceTimersByTimeAsync(3000)
 expect(vi.mocked(request).mock.calls[1]![0]).toBe('/auth/wechat/bind/poll')
 expect(wrapper.findComponent(PhoneLogin).props('bind')).toBe(true)
 wrapper.unmount()
})
it('cancels pending polling when the user leaves this method',async()=>{
 const wrapper=await setup()
 const signal=vi.mocked(request).mock.calls[0]![1]!.signal!
 wrapper.unmount()
 expect(signal.aborted).toBe(true)
 await vi.advanceTimersByTimeAsync(10000)
 expect(request).toHaveBeenCalledTimes(1)
})
it('expires the phone-link step and removes the private attempt',async()=>{
 const wrapper=await setup()
 vi.mocked(request).mockResolvedValueOnce({data:{status:'phone_required',expires_in:1}})
 await vi.advanceTimersByTimeAsync(3000);await flushPromises()
 await vi.advanceTimersByTimeAsync(2000);await flushPromises()
 expect(wrapper.findComponent(PhoneLogin).exists()).toBe(false)
 expect(wrapper.text()).toContain('过期')
 wrapper.unmount()
})

it('resumes same-tab mobile authorization without exposing a secret in the return URL',async()=>{
 vi.useFakeTimers();const pinia=createPinia();setActivePinia(pinia)
 sessionStorage.setItem('cat_wechat_login_attempt',JSON.stringify({attempt:'private-existing-attempt-123456789012345',deadline:Date.now()+60000}))
 const wrapper=mount(WechatLogin,{props:{agreed:true},global:{plugins:[pinia,i18n],stubs:{PhoneLogin:true}}})
 await flushPromises()
 expect(request).not.toHaveBeenCalled()
 vi.mocked(request).mockResolvedValueOnce({data:{status:'phone_required',expires_in:60}})
 await vi.advanceTimersByTimeAsync(3000);await flushPromises()
 expect(vi.mocked(request).mock.calls[0]![0]).toBe('/auth/wechat/poll')
 expect(wrapper.findComponent(PhoneLogin).exists()).toBe(true)
 wrapper.unmount()
 expect(sessionStorage.getItem('cat_wechat_login_attempt')).toBeNull()
})
