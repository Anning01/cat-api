import { expect,it,vi } from 'vitest'
import { mount,flushPromises } from '@vue/test-utils'
import { i18n, setLocale } from '@/i18n'
import LegacyWorksPage from './LegacyWorksPage.vue'
import { request } from '@/api'
vi.mock('@/api',()=>({API_BASE:'/api',getAuthToken:()=> 'fixture',request:vi.fn()}))
it('exposes retained works and both download paths without editing or deletion',async()=>{
  vi.mocked(request).mockResolvedValue({code:0,data:{items:[{id:7,name:'已付费作品',chapters:8}],pagination:{total:1}}})
  setLocale('zh')
  const wrapper=mount(LegacyWorksPage,{global:{plugins:[i18n]}});await flushPromises()
  expect(wrapper.text()).toContain('已付费作品')
  expect(wrapper.text()).toContain('下载完整作品包')
  expect(wrapper.text()).toContain('下载原始资料')
  expect(wrapper.text()).toContain('不设自动删除时间')
  expect(wrapper.text()).not.toMatch(/删除作品|重新生成|编辑作品/)
  expect(request).toHaveBeenCalledWith(expect.stringMatching(/^\/legacy-works\/projects\?/))
  wrapper.unmount()
})
