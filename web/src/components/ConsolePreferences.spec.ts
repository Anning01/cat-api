import { afterEach, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ConsolePreferences from './ConsolePreferences.vue'
import { locale, setLocale } from '@/i18n'
import { useAppThemeController } from '@/shared/appTheme'

afterEach(() => { document.body.innerHTML = ''; setLocale('zh'); useAppThemeController().setPreference('system') })

it('changes and saves language and appearance through component menus', async () => {
  setLocale('zh')
  const wrapper = mount(ConsolePreferences, { attachTo: document.body })
  expect(wrapper.find('select').exists()).toBe(false)
  await wrapper.get('button[aria-label="界面语言"]').trigger('click')
  await flushPromises()
  const english = Array.from(document.querySelectorAll<HTMLButtonElement>('[role=option]')).find(option => option.textContent?.includes('English'))!
  english.click(); await flushPromises()
  expect(locale.value).toBe('en')
  expect(localStorage.getItem('cat-api:locale-preference')).toBe('en')
  await wrapper.get('button[aria-label="Appearance"]').trigger('click')
  await flushPromises()
  const dark = Array.from(document.querySelectorAll<HTMLButtonElement>('[role=option]')).find(option => option.textContent?.trim() === 'Dark')!
  dark.click(); await flushPromises()
  expect(document.documentElement.dataset.appTheme).toBe('dark')
  expect(localStorage.getItem('novel-vids-theme')).toBe('dark')
  wrapper.unmount()
})
