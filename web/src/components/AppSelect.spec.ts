import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AppSelect from './AppSelect.vue'

afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })

it('associates labels with the trigger and supports keyboard selection and dismissal', async () => {
  const wrapper = mount(AppSelect, {
    props: { id: 'status', modelValue: '', ariaLabel: '状态', options: [{ value: '', label: '全部' }, { value: '0', label: '已停用' }] },
    attachTo: document.body,
  })
  const trigger = wrapper.get('button')
  expect(trigger.attributes('id')).toBe('status')
  await trigger.trigger('keydown', { key: 'ArrowDown' })
  await flushPromises()
  const list = document.querySelector('[role=listbox]')!
  expect(trigger.attributes('aria-controls')).toBe(list.id)
  expect(document.activeElement?.textContent).toContain('全部')
  document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
  expect(document.activeElement?.textContent).toContain('已停用')
  ;(document.activeElement as HTMLButtonElement).click()
  await flushPromises()
  expect(wrapper.emitted('update:modelValue')).toEqual([['0']])
  expect(document.activeElement).toBe(trigger.element)
  expect(document.querySelector('[role=listbox]')).toBeNull()
  await trigger.trigger('click')
  await flushPromises()
  document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  await flushPromises()
  expect(document.querySelector('[role=listbox]')).toBeNull()
  expect(document.activeElement).toBe(trigger.element)
  wrapper.unmount()
})

it('matches the trigger width by default and updates it on resize', async () => {
  const wrapper=mount(AppSelect,{props:{modelValue:'a',options:['a','b'],ariaLabel:'Width'},attachTo:document.body})
  const rect=vi.spyOn(wrapper.element,'getBoundingClientRect').mockReturnValue(new DOMRect(20,40,320,36))
  await wrapper.get('button').trigger('click');await flushPromises()
  const list=document.querySelector<HTMLElement>('[role=listbox]')!
  expect(list.style.width).toBe('320px')
  rect.mockReturnValue(new DOMRect(20,40,440,36))
  window.dispatchEvent(new Event('resize'));await flushPromises()
  expect(list.style.width).toBe('440px')
  wrapper.unmount()
})

it.each([['auto','max-content'],[260,'260px']] as const)('honors an explicit menu width of %s', async(menuWidth,expected)=>{
  const wrapper=mount(AppSelect,{props:{modelValue:'a',options:['a','b'],ariaLabel:'Width',menuWidth},attachTo:document.body})
  await wrapper.get('button').trigger('click');await flushPromises()
  expect(document.querySelector<HTMLElement>('[role=listbox]')!.style.width).toBe(expected)
  wrapper.unmount()
})
