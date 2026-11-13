import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ModelCatalog, { type CatalogModel } from './ModelCatalog.vue'
import { i18n, setLocale } from '@/i18n'

it.each([false,true])('explains an empty platform and offers the correct next action, administrator=%s', admin => {
  setLocale('zh')
  const wrapper=mount(ModelCatalog,{props:{models:[],canManage:admin,loggedIn:admin},global:{plugins:[i18n],stubs:{RouterLink:{props:['to'],template:'<a :href="to"><slot/></a>'}}}})
  expect(wrapper.text()).toContain('尚未配置可用模型')
  expect(wrapper.find('.catalog-sidebar').exists()).toBe(false)
  expect(wrapper.get(admin?'a[href="/settings"]':'a[href="/login"]').text()).toBe(admin?'前往模型配置':'登录控制台')
  wrapper.unmount()
})

it('pairs each billed unit with its original price, including reference material', () => {
  setLocale('zh')
  const model = { id: 'sample', name: 'Sample', kinds: ['image'], pricing: {
    type: 'image' as const, currency: 'CNY' as const, prices: { '1K': 0.04 }, discount: 0.5,
    input_image: { first_free: 1, price_per_image: 0.01 },
  } }
  const wrapper = mount(ModelCatalog, { props: { models: [model] }, global: { plugins: [i18n] } })
  expect(wrapper.get('.price-line strong').text()).toContain('¥0.02')
  expect(wrapper.get('.price-line del').text()).toContain('¥0.04')
  expect(wrapper.get('.reference-prices strong').text()).toContain('¥0.005')
  wrapper.unmount()
})

it('always shows the filter sidebar beside model cards without toggle or close controls', async () => {
  setLocale('zh')
  const models: CatalogModel[] = [
    {id:'nv-1',name:'GPT-image',kinds:['image'],pricing:{type:'image' as const,currency:'CNY' as const,prices:{'1K':.04}}},
    {id:'nv-2',name:'Seedance',kinds:['video'],pricing:{type:'video' as const,currency:'CNY' as const,prices:{'720p':.1}}},
  ]
  const wrapper=mount(ModelCatalog,{props:{models},global:{plugins:[i18n]}})
  expect(wrapper.findAll('.catalog.is-grid .model-card')).toHaveLength(2)
  expect(wrapper.find('.catalog-sidebar').exists()).toBe(true)
  expect(wrapper.find('.catalog-filter-toggle').exists()).toBe(false)
  expect(wrapper.find('button[aria-label="收起筛选"]').exists()).toBe(false)
  expect(wrapper.find('.catalog-group-title').exists()).toBe(false)
  const family=wrapper.findAll('.sidebar-checkbox-label').find(label=>label.text().includes('GPT-Image'))!
  await family.get('input').setValue(true)
  expect(wrapper.findAll('.model-card')).toHaveLength(1)
  expect(wrapper.get('.model-title').text()).toBe('GPT-image')
  await wrapper.get('button[aria-label="列表视图"]').trigger('click')
  expect(wrapper.find('.catalog.is-list').exists()).toBe(true)
  await wrapper.get('.reset-filters-btn').trigger('click')
  expect(wrapper.findAll('.model-card')).toHaveLength(2)
  expect(wrapper.find('.catalog-sidebar').exists()).toBe(true)
  wrapper.unmount()
})
