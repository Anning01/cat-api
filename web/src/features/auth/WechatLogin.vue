<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppButton from '@/components/AppButton.vue'
import PhoneLogin from './PhoneLogin.vue'
import { request } from '@/api'
import { tr } from '@/i18n'
import { useAuthStore } from './authStore'
import type { LoginResult, SingleResponse } from '@/types'

const props=defineProps<{agreed:boolean}>()
const emit=defineEmits<{authenticated:[LoginResult]}>()
const auth=useAuthStore(), busy=ref(false),error=ref(''),qr=ref(''),url=ref(''),attempt=ref('')
const phase=ref<'idle'|'pending'|'phone'|'expired'>('idle'),seconds=ref(0)
const inWechat=/MicroMessenger/i.test(navigator.userAgent)
let operation:AbortController|undefined,timer:ReturnType<typeof setTimeout>|undefined,clock:ReturnType<typeof setInterval>|undefined
const storageKey='cat_wechat_login_attempt'
function remember(token:string,deadline:number){try{sessionStorage.setItem(storageKey,JSON.stringify({attempt:token,deadline}))}catch{/* QR polling still works without storage. */}}
function forget(){try{sessionStorage.removeItem(storageKey)}catch{/* Storage can be disabled. */}}
function stop(){operation?.abort();clearTimeout(timer);clearInterval(clock)}
function expire(){stop();forget();phase.value='expired';seconds.value=0;qr.value='';url.value='';attempt.value=''}
async function start(resume?:{attempt:string;deadline:number}){
 if(busy.value||!props.agreed)return
 if(!resume)forget()
 stop();busy.value=true;error.value='';qr.value='';phase.value='idle';url.value='';attempt.value=''
 const controller=new AbortController();operation=controller
 const active=()=>operation===controller&&!controller.signal.aborted
 try{
  const data=resume?{attempt:resume.attempt,authorization_url:'',expires_in:Math.max(0,Math.floor((resume.deadline-Date.now())/1000))}:
   (await request<SingleResponse<{attempt:string;authorization_url:string;expires_in:number}>>('/auth/wechat/start',{method:'POST',signal:controller.signal})).data
  if(!active())return
  attempt.value=data.attempt;url.value=data.authorization_url;phase.value='pending'
  let deadline=Date.now()+data.expires_in*1000
  remember(data.attempt,deadline)
  const tick=()=>{seconds.value=Math.max(0,Math.ceil((deadline-Date.now())/1000));if(!seconds.value)expire()}
  tick();clock=setInterval(tick,1000)
  if(data.authorization_url)try{const {toDataURL}=await import('qrcode');const image=await toDataURL(data.authorization_url,{width:224,margin:4});if(active())qr.value=image}catch{/* The authorization link remains usable. */}
  if(!active())return
  async function poll(){
   try{
    const {data:reply}=await request<SingleResponse<{status:string;session?:LoginResult;expires_in?:number}>>('/auth/wechat/poll',{method:'POST',body:JSON.stringify({attempt:data.attempt}),signal:controller.signal})
    if(!active())return
    if(reply.status==='pending'){timer=setTimeout(poll,3000);return}
    if(reply.status==='phone_required'){phase.value='phone';qr.value='';url.value='';deadline=Date.now()+(reply.expires_in??0)*1000;remember(data.attempt,deadline);tick();return}
    if(reply.status==='completed'&&reply.session){stop();forget();emit('authenticated',reply.session);return}
    expire();error.value=tr('微信验证未完成，请重新扫码')
   }catch(e){if(active()){expire();error.value=e instanceof Error?e.message:tr('登录失败，请重试')}}
  }
  timer=setTimeout(poll,3000)
 }catch(e){if(active()){stop();error.value=e instanceof Error?e.message:tr('登录失败，请重试')}}
 finally{if(operation===controller)busy.value=false}
}
onMounted(()=>{
 try{const cached=JSON.parse(sessionStorage.getItem(storageKey)||'null');if(cached&&typeof cached.attempt==='string'&&cached.attempt.length>=32&&Number.isFinite(cached.deadline)&&cached.deadline>Date.now()&&cached.deadline<Date.now()+600000){void start(cached);return}}catch{/* Start a fresh attempt if storage is unavailable or invalid. */}
 void start()
})
onBeforeUnmount(()=>{stop();forget()})
watch(()=>auth.token,stop)
watch(()=>props.agreed,value=>{if(!value){expire()}else if(phase.value==='expired')void start()})
</script>
<template>
 <section class="wechat-login" :aria-label="tr('微信登录')" :aria-busy="busy">
  <template v-if="phase==='pending'">
   <p>{{ tr('使用微信扫一扫，登录 Cat API') }}</p>
   <img v-if="qr" :src="qr" :alt="tr('微信登录二维码')" width="224" height="224"/>
   <p v-else role="status">{{ tr(url?'二维码暂未显示，可打开下方授权链接。':'正在确认微信登录状态') }}</p>
   <a v-if="url" :href="url" :target="inWechat?'_self':'_blank'" rel="noopener noreferrer">{{ tr('在微信中打开授权') }}</a>
   <AppButton v-else type="button" variant="secondary" @click="start()">{{tr('重新扫码')}}</AppButton>
  </template>
  <template v-else-if="phase==='phone'"><PhoneLogin :wechat-attempt="attempt" :agreed="agreed" @authenticated="session=>{forget();emit('authenticated',session)}"/></template>
  <p v-if="phase==='pending'||phase==='phone'" class="muted">{{ tr('剩余时间') }} {{Math.floor(seconds/60)}}:{{String(seconds%60).padStart(2,'0')}}</p>
  <p v-if="phase==='expired'" role="status">{{ tr('微信授权已过期，请重新扫码。') }}</p>
  <AppButton v-if="phase==='idle'||phase==='expired'" type="button" :loading="busy" @click="start()">{{ tr('获取微信登录二维码') }}</AppButton>
  <p v-if="error" role="alert" class="console-error">{{error}}</p>
 </section>
</template>
<style scoped>
.wechat-login{display:grid;justify-items:center;gap:12px;inline-size:100%}
.wechat-login img{max-inline-size:100%;block-size:auto;border-radius:8px}
.wechat-login p{margin:0;font-size:13px;line-height:1.6}
.wechat-login a{text-decoration:underline;text-underline-offset:3px;font-size:13px;min-block-size:44px;display:flex;align-items:center}
</style>
