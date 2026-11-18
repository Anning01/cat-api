import { expect, it, vi } from 'vitest'
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

it.each([['zh', '音色设计'], ['en', 'Voice design']] as const)('labels and filters voice design in %s', async (locale, label) => {
  setLocale(locale)
  const models: CatalogModel[] = [
    { id: 'nv-1', name: 'GPT-image', kinds: ['image'], pricing: { type: 'image', currency: 'CNY', prices: { '1K': 0.04 } } },
    { id: 'nv-2', name: 'MiMo VoiceDesign', kinds: ['voice_design'], pricing: { type: 'voice_design', currency: 'CNY', price_per_second: 0.012 } },
  ]
  const wrapper = mount(ModelCatalog, { props: { models }, global: { plugins: [i18n] } })
  const filter = wrapper.findAll('.filter-pill').find(button => button.text().startsWith(label))!
  expect(filter.get('.pill-badge').text()).toBe('1')
  await filter.trigger('click')
  expect(filter.attributes('aria-pressed')).toBe('true')
  expect(wrapper.findAll('.model-card')).toHaveLength(1)
  expect(wrapper.get('.model-kind-pill').text()).toBe(label)
  expect(wrapper.get('.model-title').text()).toBe('MiMo VoiceDesign')
  wrapper.unmount()
})

it('estimates the discounted price per second at the lowest configured video resolution', () => {
  setLocale('zh')
  const models: CatalogModel[] = [{
    id: 'nv-1', name: 'Seedance 2.0 Mini', kinds: ['video'], pricing: {
      type: 'video', currency: 'CNY', prices: { '720p': 23, '480p': 23, '360p': 1 },
      video_reference_prices: { '480p': 14 }, discount: 0.5,
    },
  }]
  const wrapper = mount(ModelCatalog, { props: { models }, global: { plugins: [i18n] } })
  expect(wrapper.findAll('.model-card > .model-prices .price-line')).toHaveLength(1)
  expect(wrapper.get('.model-card > .model-prices dt').text()).toBe('480p · 无参考素材')
  expect(wrapper.get('.model-card > .model-prices strong').text()).toContain('约 ¥0.116')
  expect(wrapper.get('.model-card > .model-prices small').text()).toBe('/ 秒')
  expect(wrapper.get('.reference-prices summary').text()).toBe('更多价格')
  expect(wrapper.get('.reference-prices').text()).toContain('720p · 无参考素材')
  expect(wrapper.get('.reference-prices').text()).toContain('含参考视频 · 480p')
  expect(wrapper.get('.reference-prices').text()).toContain('秒（输入与输出合计）')
  expect(wrapper.text()).not.toContain('token')
  wrapper.unmount()
})

it('shows the exact second-based rate and skips disabled output tiers', () => {
  setLocale('zh')
  const models: CatalogModel[] = [{
    id: 'nv-1', name: 'Wan', kinds: ['video'], pricing: {
      type: 'video', currency: 'CNY', billing_unit: 'second', prices: { '1080P': 0.8, '480P': 0, '720P': 0.5 },
      video_reference_prices: { '480P': 0.5, '720P': 0 }, discount: 0.6,
    },
  }]
  const wrapper = mount(ModelCatalog, { props: { models }, global: { plugins: [i18n] } })
  expect(wrapper.get('.model-card > .model-prices dt').text()).toBe('720P · 无参考素材')
  expect(wrapper.get('.model-card > .model-prices strong').text()).toBe('折后价¥0.30')
  const reference = wrapper.findAll('.reference-prices .price-line').find(row => row.get('dt').text() === '输入参考视频 · 720P')!
  expect(reference.get('strong').text()).toBe('¥0.00')
  expect(reference.get('small').text()).toBe('/ 秒')
  expect(wrapper.text()).not.toContain('480P')
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


it('copies and searches the readable call name while retaining the canonical model identity',async()=>{
 setLocale('zh')
 const writeText=vi.fn().mockResolvedValue(undefined)
 Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText}})
 const wrapper=mount(ModelCatalog,{props:{models:[{id:'nv-27',alias:'seedream-5.5',name:'Doubao Seedream 5.5',kinds:['image'],pricing:{type:'image',currency:'CNY',prices:{'1K':.13}}}]},global:{plugins:[i18n]}})
 expect(wrapper.get('[data-model-id="nv-27"] .model-id').text()).toContain('seedream-5.5')
 expect(wrapper.get('.model-title').text()).toBe('Doubao Seedream 5.5')
 await wrapper.get('.model-id').trigger('click')
 expect(writeText).toHaveBeenCalledWith('seedream-5.5')
 await wrapper.get('.catalog-search input').setValue('seedream-5.5')
 expect(wrapper.find('[data-model-id="nv-27"]').exists()).toBe(true)
 wrapper.unmount()
})
