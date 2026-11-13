import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import ApiKeyCreateDialog from './ApiKeyCreateDialog.vue'
import { request } from '@/api'
import { setLocale } from '@/i18n'

vi.mock('@/api',()=>({request:vi.fn()}))
const models=[{id:'nv-1',name:'Alpha',kinds:['image'],pricing:{}},{id:'nv-2',name:'Beta',kinds:['text'],pricing:{}}]
const wrappers: ReturnType<typeof mount>[]=[]
beforeEach(()=>{
  setLocale('zh');vi.mocked(request).mockReset()
  vi.mocked(request).mockImplementation(async(_path,init)=>({code:0,message:'ok',data:init?.method==='POST'
    ? {id:1,name:'Test',preview:'fixture',created_at:'',key:'fixture-only-key'} : models}))
})
afterEach(()=>{wrappers.forEach(wrapper=>wrapper.unmount());wrappers.length=0;document.body.innerHTML=''})
async function show(){
  const wrapper=mount(ApiKeyCreateDialog,{props:{modelValue:true},attachTo:document.body});wrappers.push(wrapper)
  await flushPromises();return wrapper
}
function field(selector:string){return new DOMWrapper(document.querySelector(selector)!)}
async function submit(){await field('form.key-create-form').trigger('submit');await flushPromises()}
function posted(){return vi.mocked(request).mock.calls.filter(([,init])=>init?.method==='POST')}
async function chooseDuration(text:string){
  await field('button[aria-label="有效期"]').trigger('click');await flushPromises()
  Array.from(document.querySelectorAll<HTMLButtonElement>('[role=option]')).find(option=>option.textContent?.trim()===text)!.click();await flushPromises()
}

it('defaults to never expiring when creating a key with selected model IDs',async()=>{
  const wrapper=await show()
  expect(document.querySelector('button[aria-label="有效期"]')?.textContent).toContain('永不过期')
  await field('input[name=key_name]').setValue('Test')
  await submit()
  expect(posted()).toHaveLength(0)
  expect(document.querySelector('[role=alert]')?.textContent).toContain('请至少选择一个模型')
  await field('input[value="nv-2"]').setValue(true)
  await submit()
  const body=JSON.parse(posted()[0]![1]!.body as string)
  expect(body.allowed_model_ids).toEqual(['nv-2']);expect(body).not.toHaveProperty('purpose')
  expect(body.expires_at).toBeNull()
  expect(wrapper.emitted('created')).toHaveLength(1)
  expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
})

it('still supports a 30-day expiry and resets to never expiring when reopened',async()=>{
  const wrapper=await show()
  await chooseDuration('30 天')
  await field('input[name=key_name]').setValue('Temporary')
  await field('input[value="nv-1"]').setValue(true)
  await submit()
  expect(Math.abs(Date.parse(JSON.parse(posted()[0]![1]!.body as string).expires_at)-Date.now()-30*86400000)).toBeLessThan(5000)
  await wrapper.setProps({modelValue:false});await flushPromises()
  await wrapper.setProps({modelValue:true});await flushPromises()
  expect(document.querySelector('button[aria-label="有效期"]')?.textContent).toContain('永不过期')
  expect(document.querySelector('button[aria-label="模型排序"]')?.textContent).toContain('折扣优先')
})

it('converts a custom Beijing expiry into an explicit UTC timestamp',async()=>{
  await show()
  await field('input[name=key_name]').setValue('Custom')
  await field('input[value="nv-1"]').setValue(true)
  await chooseDuration('自定义时间')
  await field('input[type=datetime-local]').setValue('2035-01-02T12:30')
  await submit()
  expect(JSON.parse(posted()[0]![1]!.body as string).expires_at).toBe('2035-01-02T04:30:00.000Z')
})

it('supports all models without expiry and preserves the form when creation fails',async()=>{
  const wrapper=await show()
  await field('input[name=key_name]').setValue('All models')
  await field('input[name=model_scope][value=all]').setValue(true)
  await chooseDuration('永不过期')
  vi.mocked(request).mockRejectedValueOnce(new Error('创建失败，请重试'))
  await submit()
  expect(JSON.parse(posted()[0]![1]!.body as string)).toEqual({name:'All models',allowed_model_ids:null,expires_at:null})
  expect((document.querySelector('input[name=key_name]') as HTMLInputElement).value).toBe('All models')
  expect(document.activeElement?.textContent).toContain('创建失败，请重试')
  expect(wrapper.emitted('created')).toBeUndefined()
})

it('distinguishes same-name configurations by ID, discount and full tariff details',async()=>{
  vi.mocked(request).mockResolvedValueOnce({code:0,message:'ok',data:[
    {id:'nv-11',name:'Same image',kinds:['image'],image_model_type:'gpt_image_2',concurrency:3,reference_image_urls:true,pricing:{type:'image',currency:'CNY',discount:.5,prices:{'1K':.04,'2K':.08,'4K':.12},input_image:{first_free:1,price_per_image:.008}}},
    {id:'nv-12',name:'Same image',kinds:['image'],pricing:{type:'image',currency:'CNY',discount:.6,prices:{'1K':.04}}},
    {id:'nv-13',name:'Text rates',kinds:['text'],tool_calls:true,json_output:true,pricing:{type:'text',currency:'CNY',input_price_per_1m:6,output_price_per_1m:30,cache_input_price_per_1m:0}},
    {id:'nv-14',name:'Video rates',kinds:['video'],pricing:{type:'video',currency:'CNY',billing_unit:'second',discount:.5,prices:{'720p':.2},video_reference_prices:{'720p':.1}}},
    {id:'nv-15',name:'ASR rates',kinds:['asr'],pricing:{type:'asr',currency:'CNY',price_per_minute:.015}},
    {id:'nv-16',name:'Enhancement rates',kinds:['media_processing'],pricing:{type:'media_processing',currency:'CNY',discount:.8,tiers:[{short_side_max:1080,fps_max:30,price:5},{short_side_max:2160,fps_max:60,price:10}]}},
  ]})
  await show()
  const options=['nv-11','nv-12','nv-13','nv-14','nv-15','nv-16'].map(value=>document.querySelector(`input[value="${value}"]`)!.closest('.key-model-option')!)
  expect(options[0]!.textContent).toContain('nv-11');expect(options[0]!.textContent).toContain('折扣 5折')
  expect(options[1]!.textContent).toContain('nv-12');expect(options[1]!.textContent).toContain('折扣 6折')
  expect(options[0]!.textContent).toContain('并发 3')
  const rates=options[0]!.querySelectorAll('.key-price-row')
  expect(rates).toHaveLength(4)
  expect(rates[0]!.textContent).toContain('1K');expect(rates[0]!.querySelector('strong')!.textContent).toContain('¥0.02');expect(rates[0]!.querySelector('del')!.textContent).toContain('¥0.04')
  expect(rates[2]!.textContent).toContain('4K');expect(rates[2]!.querySelector('strong')!.textContent).toContain('¥0.06')
  expect(rates[3]!.textContent).toContain('输入图前 1 张免费');expect(rates[3]!.querySelector('strong')!.textContent).toContain('¥0.004')
  expect(options[2]!.textContent).toContain('输入单价');expect(options[2]!.textContent).toContain('输出单价');expect(options[2]!.textContent).toContain('缓存输入');expect(options[2]!.textContent).toContain('¥0.00')
  expect(options[3]!.textContent).toContain('输入参考视频');expect(options[3]!.textContent).toContain('/ 秒')
  expect(options[4]!.textContent).toContain('¥0.015');expect(options[4]!.textContent).toContain('/ 分钟')
  expect(options[5]!.textContent).toContain('≤1080p · ≤30fps');expect(options[5]!.textContent).toContain('≤2160p · ≤60fps')
  expect(options[5]!.querySelector('strong.discounted')!.textContent).toContain('¥4.00')
  await field('input[name=key_name]').setValue('Specific channel')
  await field('input[value="nv-12"]').setValue(true)
  await submit()
  expect(JSON.parse(posted()[0]![1]!.body as string).allowed_model_ids).toEqual(['nv-12'])
})

it('puts discounted configurations first by default and preserves selection when sorting',async()=>{
  vi.mocked(request).mockResolvedValueOnce({code:0,message:'ok',data:[
    {id:'nv-1',name:'Zeta',kinds:['image'],pricing:{discount:1}},
    {id:'nv-2',name:'Alpha',kinds:['image'],pricing:{discount:.8}},
    {id:'nv-3',name:'Beta',kinds:['image'],pricing:{discount:.5}},
    {id:'nv-4',name:'Alpha',kinds:['image'],pricing:{discount:.5}},
  ]})
  await show()
  const ids=()=>Array.from(document.querySelectorAll<HTMLInputElement>('input[name=allowed_models]')).map(input=>input.value)
  expect(ids()).toEqual(['nv-4','nv-3','nv-2','nv-1'])
  await field('input[value="nv-3"]').setValue(true)
  const selectedInput=document.querySelector('input[value="nv-3"]')
  for(const [label,expected] of [['名称 A–Z',['nv-2','nv-4','nv-3','nv-1']],['最近添加',['nv-4','nv-3','nv-2','nv-1']]] as const){
    await field('button[aria-label="模型排序"]').trigger('click');await flushPromises()
    Array.from(document.querySelectorAll<HTMLButtonElement>('[role=option]')).find(option=>option.textContent?.trim()===label)!.click();await flushPromises()
    expect(ids()).toEqual(expected)
    expect(document.querySelector('input[value="nv-3"]')).toBe(selectedInput)
    expect((selectedInput as HTMLInputElement).checked).toBe(true)
  }
  await field('input[name=key_name]').setValue('Sorted selection');await submit()
  expect(JSON.parse(posted()[0]![1]!.body as string).allowed_model_ids).toEqual(['nv-3'])
})
