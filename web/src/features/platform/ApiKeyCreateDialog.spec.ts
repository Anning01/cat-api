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

it('creates a key with selected model IDs and a 30-day expiry without a purpose field',async()=>{
  const wrapper=await show()
  await field('input[name=key_name]').setValue('Test')
  await submit()
  expect(posted()).toHaveLength(0)
  expect(document.querySelector('[role=alert]')?.textContent).toContain('请至少选择一个模型')
  await field('input[value="nv-2"]').setValue(true)
  await submit()
  const body=JSON.parse(posted()[0]![1]!.body as string)
  expect(body.allowed_model_ids).toEqual(['nv-2']);expect(body).not.toHaveProperty('purpose')
  expect(Math.abs(Date.parse(body.expires_at)-Date.now()-30*86400000)).toBeLessThan(5000)
  expect(wrapper.emitted('created')).toHaveLength(1)
  expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
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
