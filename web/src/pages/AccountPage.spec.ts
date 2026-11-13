import { beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import AccountPage from './AccountPage.vue'
import UserManagementPage from './UserManagementPage.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { request } from '@/api'
import { i18n, setLocale } from '@/i18n'
vi.mock('@/api',()=>({API_BASE:'/api',getAuthToken:()=> 'fixture',request:vi.fn(),api:{me:vi.fn()}}))
beforeEach(()=>{vi.mocked(request).mockReset();setLocale('zh')})
async function mountPage(section:'users'|'orders'|'billing'){
  const pinia=createPinia();setActivePinia(pinia)
  const auth=useAuthStore(pinia);auth.user={id:1,username:'admin',nickname:'管理员',avatar_url:'',is_super_admin:true};auth.token='fixture'
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{template:'<div/>'}}]});await router.push('/');await router.isReady()
  return mount(section==='users'?UserManagementPage:AccountPage,{props:section==='users'?{}:{section},global:{plugins:[pinia,router,i18n],stubs:{ElDialog:{template:'<div/>'}}}})
}
it('shows user balances without team or member columns',async()=>{
  vi.mocked(request).mockResolvedValue({code:0,data:{items:[{id:5,username:'owner',nickname:'账户用户',status:1,balance:'12.123456',total_cost:'0.25'}],pagination:{total:1,page:1,page_size:20,pages:1}}})
  const wrapper=await mountPage('users');await flushPromises()
  expect(wrapper.find('search input[type=search]').exists()).toBe(true)
  expect(wrapper.text()).toContain('12.123456');expect(wrapper.text()).not.toMatch(/团队|成员/)
  expect(request).toHaveBeenCalledWith(expect.stringMatching(/^\/users\?/))
  wrapper.unmount()
})
it('shows request failure and lets the user retry',async()=>{
  vi.mocked(request).mockRejectedValueOnce(new Error('连接失败')).mockImplementation(async path=>({code:0,message:'ok',data:String(path).includes('/parties')?{users:[]}:{items:[],pagination:{total:0,page:1,page_size:20,pages:0}}}))
  const wrapper=await mountPage('orders');await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('连接失败')
  await wrapper.get('[role="alert"] button').trigger('click');await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false);expect(wrapper.text()).toContain('暂无记录')
  wrapper.unmount()
})

it('submits the selected account ID and order status from component filters',async()=>{
  vi.mocked(request).mockImplementation(async path=>({code:0,message:'ok',data:String(path).includes('/parties')?{users:[{id:42,name:'测试用户'}]}:{items:[],pagination:{total:0,page:1,page_size:20,pages:0}}}))
  const wrapper=await mountPage('orders');await flushPromises()
  expect(wrapper.find('select').exists()).toBe(false)
  await wrapper.get('button[aria-label="账户用户"]').trigger('click');await flushPromises()
  document.querySelector<HTMLInputElement>('[role=listbox] input')!.value='测试'
  document.querySelector<HTMLInputElement>('[role=listbox] input')!.dispatchEvent(new Event('input',{bubbles:true}));await flushPromises()
  const options=document.querySelectorAll<HTMLButtonElement>('[role=option]')
  expect(options).toHaveLength(1);options[0]!.click();await flushPromises()
  await wrapper.get('button[aria-label="订单状态"]').trigger('click');await flushPromises()
  Array.from(document.querySelectorAll<HTMLButtonElement>('[role=option]')).find(option=>option.textContent?.trim()==='已支付')!.click();await flushPromises()
  await wrapper.get('form.console-filterbar').trigger('submit');await flushPromises()
  expect(request).toHaveBeenCalledWith(expect.stringMatching(/\/account\/orders\?.*status=paid.*account_user_id=42/))
  wrapper.unmount()
})

it('immediately reloads users when component sorting changes',async()=>{
  vi.mocked(request).mockResolvedValue({code:0,message:'ok',data:{items:[],pagination:{total:0,page:1,page_size:20,pages:0}}})
  const wrapper=await mountPage('users');await flushPromises()
  await wrapper.get('button[aria-label="排序"]').trigger('click');await flushPromises()
  Array.from(document.querySelectorAll<HTMLButtonElement>('[role=option]')).find(option=>option.textContent?.includes('最早创建优先'))!.click();await flushPromises()
  expect(request).toHaveBeenCalledWith(expect.stringMatching(/\/users\?.*order_by=id/))
  wrapper.unmount()
})

it('shows billing usage and references directly without detail actions, including zero and false values',async()=>{
  vi.mocked(request).mockImplementation(async path=>({code:0,message:'ok',data:String(path).includes('/parties')?{users:[]}:{items:[
    {id:7,user_name:'测试用户',created_at:'2026-11-12T15:18:51Z',billing_type:'text',cost:'2.100991',balance_after:'0.952936',usage_record_id:1444,usage:{input_tokens:0,output_tokens:55496,missing_usage:false}},
    {id:8,created_at:'2026-11-12T15:18:52Z',billing_type:'image',cost:'0.123456',balance_after:'0',usage:{}},
  ],pagination:{total:2,page:1,page_size:20,pages:1}}}))
  const wrapper=await mountPage('billing');await flushPromises()
  const rows=wrapper.findAll('.console-data-table tbody tr')
  expect(rows[0]!.text()).toContain('1444')
  expect(rows[0]!.text()).toContain('2.100991')
  expect(rows[0]!.text()).toContain('0.952936')
  expect(rows[0]!.get('.billing-identity').text()).toContain('2026/11/12 23:18:51')
  expect(rows[0]!.get('.billing-usage').text()).toContain('输入 Tokens0')
  expect(rows[0]!.get('.billing-usage').text()).toContain('输出 Tokens55496')
  expect(rows[0]!.get('.billing-usage').text()).toContain('用量缺失否')
  expect(rows[1]!.text()).toContain('历史记录未提供详细用量。')
  expect(wrapper.find('.table-link').exists()).toBe(false)
  expect(wrapper.findAll('button').some(button=>button.text()==='详情')).toBe(false)
  expect(wrapper.findAll('th[scope=col]').some(header=>header.text()==='操作')).toBe(false)
  wrapper.unmount()
})

it('continues loading recharge order details from their own endpoint',async()=>{
  const order={id:9,out_trade_no:'fixture-order',amount:'12.34',status:'paid',created_at:'2026-11-12T15:18:51Z',transaction_id:'fixture-transaction'}
  vi.mocked(request).mockImplementation(async path=>({code:0,message:'ok',data:String(path).includes('/parties')?{users:[]}:String(path).includes('/recharge/')?order:{items:[order],pagination:{total:1,page:1,page_size:20,pages:1}}}))
  const wrapper=await mountPage('orders');await flushPromises()
  await wrapper.get('.table-link').trigger('click');await flushPromises()
  expect(request).toHaveBeenCalledWith('/account/recharge/fixture-order')
  expect(document.querySelector('dialog[open]')?.textContent).toContain('订单详情')
  expect(document.querySelector('dialog[open]')?.textContent).toContain('fixture-transaction')
  wrapper.unmount()
})

it.each([['余额预警（≤ ¥10）','low'],['欠费账户','negative']])('combines %s with user filters and resets without view tabs',async(label,value)=>{
  vi.mocked(request).mockImplementation(async path=>({code:0,message:'ok',data:String(path)==='/users/stats'
    ?{user_count:50,balance_total:'731.21736',user_total_cost:571.94893}
    :{items:[],pagination:{total:0,page:1,page_size:20,pages:0}}}))
  const wrapper=await mountPage('users');await flushPromises()
  expect(wrapper.find('[aria-label="用户视图"]').exists()).toBe(false)
  expect(wrapper.find('.console-summary').exists()).toBe(false)
  expect(wrapper.get('.users-summary').text()).toContain('731.21736')
  expect(wrapper.find('.console-table-panel.is-compact').exists()).toBe(true)
  await wrapper.get('input[type=search]').setValue('Alice')
  for(const [control,choice] of [['状态','已停用'],['身份','普通用户'],['余额筛选',label]]){
    await wrapper.get(`button[aria-label="${control}"]`).trigger('click');await flushPromises()
    Array.from(document.querySelectorAll<HTMLButtonElement>('[role=option]')).find(option=>option.textContent?.trim()===choice)!.click();await flushPromises()
  }
  const lastQuery=()=>new URLSearchParams(String(vi.mocked(request).mock.calls.map(([path])=>path).filter(path=>String(path).startsWith('/users?')).at(-1)).split('?')[1])
  expect(Object.fromEntries(lastQuery())).toMatchObject({search:'Alice',status:'0',role:'user',balance_view:value})
  await wrapper.findAll('button').find(button=>button.text()==='重置')!.trigger('click');await flushPromises()
  expect(lastQuery().has('balance_view')).toBe(false)
  expect(lastQuery().has('search')).toBe(false)
  expect(lastQuery().has('status')).toBe(false)
  expect(lastQuery().has('role')).toBe(false)
  wrapper.unmount()
})
