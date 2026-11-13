import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ModelCatalog from './ModelCatalog.vue'
import { i18n, setLocale } from '@/i18n'

it.each([false,true])('explains an empty platform and offers the correct next action, administrator=%s', admin => {
  setLocale('zh')
  const wrapper=mount(ModelCatalog,{props:{models:[],canManage:admin,loggedIn:admin},global:{plugins:[i18n],stubs:{RouterLink:{props:['to'],template:'<a :href="to"><slot/></a>'}}}})
  expect(wrapper.text()).toContain('尚未配置可用模型')
  expect(wrapper.find('.catalog-sidebar').exists()).toBe(false)
  expect(wrapper.get(admin?'a[href="/settings"]':'a[href="/login"]').text()).toBe(admin?'前往模型配置':'登录控制台')
  wrapper.unmount()
})
