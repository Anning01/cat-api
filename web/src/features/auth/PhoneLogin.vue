<script setup lang="ts">
import { onBeforeUnmount, ref, useId, watch } from 'vue'
import AppButton from '@/components/AppButton.vue'
import { request } from '@/api'
import { useAuthStore } from './authStore'
import { tr } from '@/i18n'
import type { LoginResult, SingleResponse } from '@/types'

const props=defineProps<{bind?:boolean;agreed?:boolean;wechatAttempt?:string}>()
const emit=defineEmits<{authenticated:[LoginResult];bound:[]}>()
const auth=useAuthStore(), id=useId(), phone=ref(''),code=ref(''),challenge=ref(''),sentPhone=ref('')
const error=ref(''),message=ref(''),busy=ref(false),sending=ref(false),seconds=ref(0)
const phoneInput=ref<HTMLInputElement>(),codeInput=ref<HTMLInputElement>()
const operation=new AbortController()
let timer:ReturnType<typeof setInterval>|undefined
function countdown(){
 clearInterval(timer)
 const end=Date.now()+60000;seconds.value=60
 timer=setInterval(()=>{seconds.value=Math.max(0,Math.ceil((end-Date.now())/1000));if(!seconds.value)clearInterval(timer)},500)
}
watch(phone,()=>{challenge.value='';code.value='';message.value='';error.value=''})
onBeforeUnmount(()=>{clearInterval(timer);operation.abort()})
async function send(){
 if(sending.value||busy.value||seconds.value)return
 if(!phoneInput.value?.reportValidity())return
 if(!props.bind&&auth.legalReady&&!props.agreed){error.value=tr('请先阅读并同意用户协议和隐私政策');return}
 sending.value=true;error.value='';message.value='';challenge.value=''
 const value=phone.value
 try{
  const result=await request<SingleResponse<{challenge:string}>>(`/auth/phone/${props.bind?'bind/':''}start`,{method:'POST',body:JSON.stringify({phone:value,wechat_attempt:props.bind?props.wechatAttempt:undefined}),signal:operation.signal})
  if(operation.signal.aborted)return
  countdown()
  if(phone.value!==value)return
  challenge.value=result.data.challenge;sentPhone.value=value;message.value=tr('验证码已发送，5分钟内有效。');codeInput.value?.focus()
 }catch(e){if(!operation.signal.aborted)error.value=e instanceof Error?e.message:tr('发送失败')}
 finally{sending.value=false}
}
async function submit(){
 if(busy.value||sending.value)return
 error.value='';message.value=''
 if(!challenge.value||sentPhone.value!==phone.value){error.value=tr('请先获取验证码');return}
 if(!props.bind&&auth.legalReady&&!props.agreed){error.value=tr('请先阅读并同意用户协议和隐私政策');return}
 busy.value=true
 try{
  const result=await request<SingleResponse<LoginResult>>(`/auth/phone/${props.bind?'bind':'login'}`,{method:'POST',body:JSON.stringify({phone:phone.value,challenge:challenge.value,code:code.value,agreed:props.agreed===true,wechat_attempt:props.wechatAttempt}),signal:operation.signal})
  if(operation.signal.aborted)return
  if(props.bind&&!props.wechatAttempt)emit('bound');else emit('authenticated',result.data)
 }catch(e){if(!operation.signal.aborted)error.value=e instanceof Error?e.message:tr('验证失败')}
 finally{busy.value=false}
}
</script>
<template>
 <form class="phone-login" method="post" :action="'/api/auth/phone/'+(bind?'bind':'login')" @submit.prevent="submit" :aria-label="tr(bind?'绑定手机号':'手机验证码登录')">
  <p v-if="bind&&wechatAttempt" class="muted">{{ auth.phoneMasked?tr('微信已确认。请验证当前账号绑定的手机号 {p0}。',{p0:auth.phoneMasked}):tr('微信已确认。请验证手机号，将手机和微信一起绑定到当前账号。') }}</p>
  <p v-else-if="bind" class="muted">{{ tr('绑定到当前账号，保留余额与 API Key。绑定成功后，请使用手机号重新登录。') }}</p>
  <p v-else-if="wechatAttempt" class="muted">{{ tr('微信已确认，请验证手机号。') }}</p>
  <div class="phone-field">
    <label :for="id+'-phone'">{{ tr('手机号') }}</label>
    <p :id="id+'-hint'" class="visually-hidden">{{ tr('中国大陆手机号，不含 +86。') }}</p>
    <div class="phone-number">
      <span aria-hidden="true">+86</span>
      <input ref="phoneInput" :id="id+'-phone'" name="phone" v-model="phone" type="tel" inputmode="tel" autocomplete="tel-national" pattern="1[3-9][0-9]{9}" maxlength="11" :placeholder="tr('11 位手机号码')" required :disabled="busy||sending" :aria-describedby="id+'-hint'"/>
    </div>
  </div>
  <div class="phone-field">
    <label :for="id+'-code'">{{ tr('短信验证码') }}</label>
    <div class="phone-code-row">
      <input ref="codeInput" :id="id+'-code'" name="code" v-model="code" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" :placeholder="tr('6 位验证码')" required autocorrect="off" autocapitalize="none" :spellcheck="false" :disabled="busy"/>
      <AppButton type="button" variant="secondary" :loading="sending" :disabled="busy||seconds>0" @click="send">{{ seconds>0?`${seconds}s`:tr('获取验证码') }}</AppButton>
    </div>
  </div>
  <slot v-if="!bind" name="agreement"/>
  <p v-if="message" role="status">{{message}}</p>
  <p v-if="error" role="alert" class="console-error">{{error}}</p>
  <AppButton type="submit" variant="primary" block :loading="busy" :disabled="sending">{{ tr(bind?(wechatAttempt?'验证手机并绑定微信':'验证并绑定'):'验证并登录') }}</AppButton>
 </form>
</template>
<style scoped>
.phone-login{display:grid;gap:16px;inline-size:100%;max-inline-size:420px;text-align:start}
.phone-field{display:grid;gap:6px}
.phone-field label{font-size:13px;font-weight:650}
.phone-login input:not([type=checkbox]){inline-size:100%;min-inline-size:0;min-block-size:48px;padding:8px 12px;border:1px solid var(--app-border);border-radius:8px;background:var(--app-surface);color:var(--app-text);font-size:max(1rem,16px)}
.phone-login input::placeholder{color:var(--app-text-muted)}
.phone-login p{margin:0;font-size:13px;line-height:1.6}
.phone-login :deep(.app-button){min-block-size:48px}
.phone-number{position:relative}
.phone-number span{position:absolute;inset-inline-start:12px;inset-block-start:50%;transform:translateY(-50%);padding-inline-end:10px;border-inline-end:1px solid var(--app-border);color:var(--app-text-secondary);font-variant-numeric:tabular-nums;pointer-events:none}
.phone-number input:not([type=checkbox]){padding-inline-start:55px}
.phone-code-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px}
</style>
