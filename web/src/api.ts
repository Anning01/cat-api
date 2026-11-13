import { locale, tr } from './i18n'
import type { AiModelConfig, AllEnums, AuthMe, AuthStatus, GenerationCapabilities, LoginResult, PaginationResponse, QilingAttempt, QilingPoll, SingleResponse } from './types'
export const API_BASE = ((import.meta.env.VITE_API_BASE ?? '') as string).replace(/\/+$/, '') + '/api'
const TOKEN_KEY = 'novelvids_token'
export const getAuthToken = () => localStorage.getItem(TOKEN_KEY)
export const setAuthToken = (value: string) => localStorage.setItem(TOKEN_KEY, value)
export const clearAuthToken = () => localStorage.removeItem(TOKEN_KEY)
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Accept-Language', locale.value === 'zh' ? 'zh-CN' : 'en')
  const token = getAuthToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(API_BASE + path, { ...options, headers })
  let body
  try { body = await response.json() }
  catch { throw new Error(tr('服务暂时不可用，请刷新后重试')) }
  if (!response.ok || body.code !== 0) {
    if (body.code === 401) window.location.hash = '#/login'
    throw new Error(tr(body.message || '请求失败，请重试'))
  }
  return body as T
}
export const api = {
  authStatus: () => request<SingleResponse<AuthStatus>>('/auth/status'),
  me: () => request<SingleResponse<AuthMe>>('/auth/me'),
  login: (username: string, password: string) => request<SingleResponse<LoginResult>>('/auth/login', { method:'POST', body:JSON.stringify({username,password}) }),
  logout: () => request('/auth/logout', {method:'POST'}),
  qilingStart: (bind: boolean) => request<SingleResponse<QilingAttempt>>(`/auth/qiling/${bind ? 'bind/' : ''}start`, { method:'POST' }),
  qilingPoll: (bind: boolean, attempt: string, signal: AbortSignal) => request<SingleResponse<QilingPoll>>(`/auth/qiling/${bind ? 'bind/' : ''}poll`, { method:'POST', body:JSON.stringify({attempt}), signal }),
  configs: () => request<PaginationResponse<AiModelConfig>>('/config?page=1&page_size=100'),
  enums: () => request<SingleResponse<AllEnums>>('/config/enums/all'),
  generationCapabilities: () => request<SingleResponse<GenerationCapabilities>>('/config/generation/capabilities'),
  createConfig: (data: Partial<AiModelConfig>) => request<SingleResponse<AiModelConfig>>('/config', { method:'POST',body:JSON.stringify(data) }),
  updateConfig: (id: number, data: Partial<AiModelConfig>) => request<SingleResponse<AiModelConfig>>(`/config/${id}`, {method:'PATCH',body:JSON.stringify(data)}),
  activateConfig: (id: number) => request(`/config/${id}/activate`, {method:'POST'}),
  deactivateConfig: (id: number) => request(`/config/${id}/deactivate`, {method:'POST'}),
  deleteConfig: (id: number) => request(`/config/${id}`, {method:'DELETE'}),
}
