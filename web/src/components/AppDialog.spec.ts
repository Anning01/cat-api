import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AppDialog from './AppDialog.vue'
import AppSelect from './AppSelect.vue'
import { appConfirm } from '@/shared/confirmDialog'
vi.mock('@/shared/confirmDialog',()=>({appConfirm:vi.fn()}))
afterEach(()=>{document.body.innerHTML='';vi.resetAllMocks()})

it('guards edits on Escape and closes only after explicit discard',async()=>{
  const wrapper=mount(AppDialog,{props:{modelValue:true,title:'Edit',guardChanges:true},slots:{default:'<input aria-label="Name">'},attachTo:document.body})
  await flushPromises()
  const dialog=document.body.querySelector('dialog')!
  expect(dialog.open).toBe(true)
  document.body.querySelector('input')!.dispatchEvent(new Event('input',{bubbles:true}))
  vi.mocked(appConfirm).mockResolvedValueOnce(false)
  dialog.dispatchEvent(new Event('cancel',{cancelable:true}));await flushPromises()
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  vi.mocked(appConfirm).mockResolvedValueOnce(true)
  dialog.dispatchEvent(new Event('cancel',{cancelable:true}));await flushPromises()
  expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  wrapper.unmount()
})

it('keeps a select menu inside its modal so it is not made inert',async()=>{
  const select=mount(AppSelect,{props:{modelValue:'a',options:['a','b'],ariaLabel:'Choice'},attachTo:document.body})
  const modal=document.createElement('dialog');document.body.append(modal);modal.append(select.element);modal.showModal()
  await select.find('button').trigger('click');await flushPromises()
  expect(modal.querySelector('[role=listbox]')).not.toBeNull()
  select.unmount();modal.close()
})
