import { beforeEach, expect, it, vi } from 'vitest'
import { money, dateTime } from './console'
import { locale, refreshLocale, setLocale, setUserLocale } from '@/i18n'

beforeEach(() => { localStorage.clear(); setLocale('zh') })
it('retains small and negative charges and distinguishes missing balances', () => {
  expect(money('0.000001')).toBe('0.000001')
  expect(money('-0.386970')).toBe('-0.38697')
  expect(money(null)).toBe('—')
  expect(money('0')).toBe('0.00')
})
it('renders equivalent offset and platform-local dates consistently', () => {
  expect(dateTime('2026-11-13 12:30:00')).toBe(dateTime('2026-11-13T04:30:00Z'))
  expect(dateTime('not-a-date')).toBe('—')
})
it('preserves an explicit language choice when the server default refreshes', async () => {
  const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher)
  setUserLocale('en')
  await refreshLocale()
  expect(locale.value).toBe('en')
  expect(document.documentElement.lang).toBe('en')
  expect(fetcher).not.toHaveBeenCalled()
  vi.unstubAllGlobals()
})

it('uses the console default rather than a cached generation language on first visit',async()=>{
  localStorage.setItem('novelvids_locale','en');setLocale('en')
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({code:0,data:{locale:'zh'}})}))
  await refreshLocale()
  expect(locale.value).toBe('zh')
  vi.unstubAllGlobals()
})
