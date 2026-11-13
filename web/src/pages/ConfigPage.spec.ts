import { expect,it,vi } from 'vitest'
import { mount,flushPromises } from '@vue/test-utils'
import ConfigPage from './ConfigPage.vue'
import { api } from '@/api'
import { i18n,setLocale } from '@/i18n'
vi.mock('@/api',()=>({api:{configs:vi.fn(),enums:vi.fn(),generationCapabilities:vi.fn()}}))
it('renders retained models after all settings dependencies load and switches categories',async()=>{
  setLocale('zh')
  vi.mocked(api.configs).mockResolvedValue({code:0,message:'ok',data:{items:[
    {id:1,name:'现有文本模型',task_type:7,task_types:[7],model:'chat',api_protocol:'openai_compatible',is_active:true,concurrency:1,supports_json_output:true,pricing:{type:'text',currency:'CNY',input_price_per_1m:2,output_price_per_1m:8,discount:0.5},created_at:'',updated_at:''},
    {id:2,name:'现有视频模型',task_type:4,task_types:[4],model:'video',api_protocol:'volcengine_ark',video_model_type:'seedance_2_mini',is_active:true,concurrency:1,supports_json_output:false,created_at:'',updated_at:''},
  ],pagination:{total:2,page:1,page_size:100,pages:1}}})
  vi.mocked(api.enums).mockResolvedValue({code:0,message:'ok',data:{task_status:[],asset_type:[],image_source:[],workflow_status:[],ai_task_type:[{value:7,label:'文本'},{value:4,label:'视频'}],video_model_type:[{value:'seedance_2_mini',label:'Mini'}],image_model_type:[]}})
  vi.mocked(api.generationCapabilities).mockResolvedValue({code:0,message:'ok',data:{image:{},video:{seedance_2_mini:['480p']}}})
  const wrapper=mount(ConfigPage,{global:{plugins:[i18n]}});await flushPromises()
  expect(wrapper.text()).toContain('现有文本模型')
  expect(wrapper.get('table caption').text()).toBe('模型配置列表')
  const row=wrapper.get('tbody tr')
  expect(row.text()).toContain('5 折')
  expect(row.get('.config-prices').text()).toContain('输入单价')
  expect(row.get('.config-prices .unit-price strong').text()).toContain('¥1.00')
  expect(row.get('.config-prices del').text()).toContain('¥2.00')
  expect(row.findAll('.status-badge')).toHaveLength(1)
  expect(row.find('button[aria-label="编辑配置"]').exists()).toBe(true)
  expect(row.find('button[aria-label="删除配置"]').exists()).toBe(true)
  await wrapper.findAll('.model-category-card').find(button=>button.text().includes('视频模型'))!.trigger('click')
  expect(wrapper.text()).toContain('现有视频模型')
  expect(api.configs).toHaveBeenCalledOnce();expect(api.enums).toHaveBeenCalledOnce();expect(api.generationCapabilities).toHaveBeenCalledOnce()
  wrapper.unmount()
})
