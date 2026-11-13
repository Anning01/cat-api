import { beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import PlatformConsolePage from './PlatformConsolePage.vue'
import { request } from '@/api'
import { setLocale } from '@/i18n'
import type { BillingSummary } from '@/types'

vi.mock('@/api',()=>({API_BASE:'/api',getAuthToken:()=>null,request:vi.fn(),api:{}}))

const summary: BillingSummary = {
  total_cost:12,total_records:42,by_model:[],by_task_type:[],
  by_billing_type:[{billing_type:'image',cost:12}],
  daily_trend:[{date:'2026-11-13',cost:12,records:42}],
}
beforeEach(()=>{vi.mocked(request).mockReset();setLocale('zh')})
async function mountUsage(){
  vi.mocked(request).mockResolvedValue({code:0,data:summary,message:'ok'})
  const wrapper=mount(PlatformConsolePage,{props:{section:'usage'},global:{plugins:[createPinia()]}})
  await flushPromises()
  return wrapper
}

it('replays both chart drawings after refresh with unchanged data and preserves the metric',async()=>{
  const wrapper=await mountUsage()
  await wrapper.get('.console-segmented button:nth-child(2)').trigger('click')
  const firstPlot=wrapper.get('.trend-plot').element,firstRing=wrapper.get('.distribution svg g').element
  await wrapper.findAll('.console-page-actions button').find(button=>button.text()==='刷新')!.trigger('click');await flushPromises()
  expect(wrapper.get('.trend-plot').element).not.toBe(firstPlot)
  expect(wrapper.get('.distribution svg g').element).not.toBe(firstRing)
  expect(wrapper.get('.console-segmented button:nth-child(2)').attributes('aria-pressed')).toBe('true')
  expect(wrapper.get('.trend-plot button').attributes('aria-label')).toContain('42')
  const refreshedPlot=wrapper.get('.trend-plot').element
  await wrapper.findAll('.console-page-actions button').find(button=>button.text()==='近 30 天')!.trigger('click');await flushPromises()
  expect(request).toHaveBeenLastCalledWith('/platform/usage?days=30')
  expect(wrapper.get('.trend-plot').element).not.toBe(refreshedPlot)
  expect(wrapper.get('.console-segmented button:nth-child(2)').attributes('aria-pressed')).toBe('true')
  wrapper.unmount()
})

it('keeps the existing charts when refresh fails',async()=>{
  const wrapper=await mountUsage()
  const plot=wrapper.get('.trend-plot').element,ring=wrapper.get('.distribution svg g').element
  vi.mocked(request).mockRejectedValueOnce(new Error('刷新失败'))
  await wrapper.findAll('.console-page-actions button').find(button=>button.text()==='刷新')!.trigger('click');await flushPromises()
  expect(wrapper.get('[role=alert]').text()).toContain('刷新失败')
  expect(wrapper.get('.trend-plot').element).toBe(plot)
  expect(wrapper.get('.distribution svg g').element).toBe(ring)
  wrapper.unmount()
})

it('shows key model permissions and expiry instead of purpose',async()=>{
  const expiry='2026-01-01T00:00:00Z'
  vi.mocked(request).mockImplementation(async path=>({code:0,message:'ok',data:String(path).includes('/catalog')?[]:[
    {id:1,name:'Limited',preview:'fixture-1',created_at:'2025-01-01T00:00:00Z',allowed_model_ids:['nv-3'],expires_at:expiry,is_expired:true},
    {id:2,name:'Legacy',preview:'fixture-2',created_at:'2025-01-01T00:00:00Z',allowed_model_ids:null,expires_at:null},
  ]}))
  const wrapper=mount(PlatformConsolePage,{props:{section:'keys'},global:{plugins:[createPinia()]}});await flushPromises()
  expect(wrapper.text()).not.toContain('用途')
  expect(wrapper.text()).toContain('指定 1 个模型')
  expect(wrapper.text()).toContain('已过期')
  expect(wrapper.text()).toContain('永不过期')
  wrapper.unmount()
})
