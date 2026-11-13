import { afterEach, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AppSelect from './AppSelect.vue'

afterEach(() => { document.body.innerHTML = '' })

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
