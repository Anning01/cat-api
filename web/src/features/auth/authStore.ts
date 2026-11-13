import { defineStore } from 'pinia'
import { api, clearAuthToken, getAuthToken, setAuthToken } from '@/api'
import type { AuthMe, AuthUser, LoginResult } from '@/types'
export const useAuthStore = defineStore('auth', {
  state: () => ({ ready:false, token:getAuthToken(), user:null as AuthUser | null,
    balance:'0', totalCost:0, qilingEnabled:false, legalReady:false, provider:'qiling' as 'qiling'|'password' }),
  getters: {
    isLoggedIn: state => Boolean(state.token && state.user),
    isSuperAdmin: state => state.user?.is_super_admin === true,
    canAccessBilling: state => Boolean(state.token && state.user),
  },
  actions: {
    applyMe(me: AuthMe) { this.user=me.user; this.balance=me.balance; this.totalCost=Number(me.total_cost) },
    async bootstrap() {
      if (this.ready) return
      const {data} = await api.authStatus()
      this.qilingEnabled=data.qiling_enabled === true; this.legalReady=data.legal_ready === true
      this.provider=data.provider ?? 'qiling'
      if (this.token) {
        try { await this.refreshMe() } catch { this.user=null; this.token=null; clearAuthToken() }
      }
      this.ready=true
    },
    async acceptSession(session: LoginResult) {
      setAuthToken(session.token); this.token=session.token
      await this.refreshMe()
    },
    async refreshMe() { this.applyMe((await api.me()).data) },
    async login(username:string,password:string) { await this.acceptSession((await api.login(username,password)).data) },
    async logout() {
      try { await api.logout() } finally { clearAuthToken(); this.token=null; this.user=null; this.balance='0'; this.totalCost=0; window.location.hash='#/login' }
    },
  },
})
