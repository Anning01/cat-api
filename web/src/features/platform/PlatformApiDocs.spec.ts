import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PlatformApiDocs from './PlatformApiDocs.vue'
import { request } from '@/api'
import { i18n, setLocale } from '@/i18n'

vi.mock('@/api',()=>({request:vi.fn()}))
beforeEach(()=>{vi.mocked(request).mockReset();setLocale('zh')})
afterEach(()=>{document.body.innerHTML='';vi.unstubAllGlobals();vi.useRealTimers()})
function render(url='',canManage=false){
 vi.mocked(request).mockResolvedValue({code:0,message:'ok',data:{url}})
 return mount(PlatformApiDocs,{props:{baseUrl:'http://127.0.0.1:3001/v1',canManage},global:{plugins:[i18n]},attachTo:document.body})
}
it('embeds only the published public page without passing credentials or modifying its URL',async()=>{
 const wrapper=render('https://rjvutktiur.apifox.cn/');await flushPromises()
 const frame=wrapper.get('iframe')
 expect(frame.attributes('src')).toBe('https://rjvutktiur.apifox.cn/')
 expect(frame.attributes('title')).toBe('Cat API 在线接口文档')
 expect(frame.attributes('referrerpolicy')).toBe('no-referrer')
 expect(frame.attributes('sandbox')).not.toContain('allow-top-navigation')
 expect(wrapper.find('a[target="_blank"]').attributes('rel')).toBe('noopener noreferrer')
 expect(wrapper.text()).not.toContain('文档设置')
 await frame.trigger('load')
 expect(wrapper.find('.docs-frame-loading').exists()).toBe(false)
 wrapper.unmount()
})
it('shows a restrained unpublished state with export and admin configuration controls',async()=>{
 const wrapper=render('',true);await flushPromises()
 expect(wrapper.find('iframe').exists()).toBe(false)
 expect(wrapper.text()).toContain('在线文档待发布')
 expect(wrapper.get('a[download]').attributes('href')).toBe('http://127.0.0.1:3001/api/platform/openapi-export')
 expect((wrapper.get('input[readonly]').element as HTMLInputElement).value).toBe('http://127.0.0.1:3001/v1/openapi.json')
 await wrapper.findAll('button').find(b=>b.text()==='配置在线文档')!.trigger('click');await flushPromises()
 expect(document.querySelector('dialog[open] input[type=url]')).not.toBeNull()
 wrapper.unmount()
})
it('persists the administrator link and reloads to apply the new CSP origin',async()=>{
 const wrapper=render('',true);await flushPromises()
 await wrapper.findAll('button').find(b=>b.text()==='文档设置')!.trigger('click');await flushPromises()
 const input=document.querySelector<HTMLInputElement>('dialog input[type=url]')!
 input.value='https://rjvutktiur.apifox.cn/';input.dispatchEvent(new Event('input',{bubbles:true}))
 const reload=vi.fn();vi.stubGlobal('location',{origin:'http://127.0.0.1:3001',reload})
 document.querySelector<HTMLFormElement>('dialog form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await flushPromises()
 expect(request).toHaveBeenCalledWith('/platform/documentation',{method:'PATCH',body:JSON.stringify({url:'https://rjvutktiur.apifox.cn/'})})
 expect(reload).toHaveBeenCalledOnce()
 wrapper.unmount()
})
it('reports failed reads and allows retry',async()=>{
 vi.mocked(request).mockRejectedValueOnce(new Error('连接失败')).mockResolvedValue({data:{url:''}})
 const wrapper=mount(PlatformApiDocs,{props:{baseUrl:'/v1'},global:{plugins:[i18n]}});await flushPromises()
 expect(wrapper.get('[role=alert]').text()).toContain('连接失败')
 await wrapper.findAll('button').find(b=>b.text()==='重试')!.trigger('click');await flushPromises()
 expect(wrapper.find('[role=alert]').exists()).toBe(false)
 wrapper.unmount()
})
it.each(['javascript:alert(1)','https://private:token@example.com/','http://example.com/'])('does not embed unsafe metadata %s',async(url)=>{
 const wrapper=render(url);await flushPromises()
 expect(wrapper.find('iframe').exists()).toBe(false)
 wrapper.unmount()
})
