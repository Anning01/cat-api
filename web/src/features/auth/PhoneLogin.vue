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
const error=ref(''),message=ref(''),busy=ref(false),sending=ref(false),seconds=ref(0),register=ref(false)
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
  const result=await request<SingleResponse<{challenge:string}>>(`/auth/phone/${props.bind?'bind/':''}start`,{method:'POST',body:JSON.stringify({phone:value}),signal:operation.signal})
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
  const result=await request<SingleResponse<LoginResult>>(`/auth/phone/${props.bind?'bind':'login'}`,{method:'POST',body:JSON.stringify({phone:phone.value,challenge:challenge.value,code:code.value,register:register.value,agreed:props.agreed===true,wechat_attempt:props.wechatAttempt}),signal:operation.signal})
  if(operation.signal.aborted)return
  if(props.bind)emit('bound');else emit('authenticated',result.data)
 }catch(e){if(!operation.signal.aborted)error.value=e instanceof Error?e.message:tr('验证失败')}
 finally{busy.value=false}
}
</script>
<template>
 <form class="phone-login" method="post" :action="'/api/auth/phone/'+(bind?'bind':'login')" @submit.prevent="submit" :aria-label="tr(bind?'绑定手机号':'手机验证码登录')">
  <p v-if="bind" class="muted">{{ tr('绑定到当前账号，保留余额与 API Key。绑定成功后，请使用手机号重新登录。') }}</p>
  <p v-else-if="wechatAttempt" class="muted">{{ tr('微信验证成功。请验证手机号，将此微信绑定到该手机号的账号。老用户请使用已绑定的手机号。') }}</p>
  <p v-else class="muted">{{ tr('老用户请先通过原登录入口进入个人中心绑定手机，避免创建新账号。') }}</p>
  <label :for="id+'-phone'">{{ tr('手机号') }}</label>
  <input ref="phoneInput" :id="id+'-phone'" name="phone" v-model="phone" type="tel" inputmode="tel" autocomplete="tel-national" pattern="1[3-9][0-9]{9}" maxlength="11" required :disabled="busy||sending" :aria-describedby="id+'-hint'"/>
  <p :id="id+'-hint'" class="muted">{{ tr('中国大陆手机号，不含 +86。') }}</p>
  <label :for="id+'-code'">{{ tr('短信验证码') }}</label>
  <div class="phone-code-row">
   <input ref="codeInput" :id="id+'-code'" name="code" v-model="code" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required autocorrect="off" autocapitalize="none" :spellcheck="false" :disabled="busy"/>
   <AppButton type="button" variant="secondary" :loading="sending" :disabled="busy||seconds>0" @click="send">{{ seconds>0?`${seconds}s`:tr('获取验证码') }}</AppButton>
  </div>
  <label v-if="!bind&&auth.phoneSignupEnabled" class="phone-register"><input name="register" type="checkbox" v-model="register"/>{{ tr('我是新用户，注册独立账号') }}</label>
  <AppButton type="submit" variant="primary" :loading="busy" :disabled="sending">{{ tr(bind?'验证并绑定':wechatAttempt?'验证手机并绑定微信':register?'验证并注册':'验证并登录') }}</AppButton>
  <p v-if="message" role="status">{{message}}</p>
  <p v-if="error" role="alert" class="console-error">{{error}}</p>
 </form>
</template>
<style scoped>
.phone-login{display:grid;gap:10px;inline-size:100%;max-inline-size:420px;text-align:start}
.phone-login>label{font-size:13px;font-weight:500}
.phone-login input:not([type=checkbox]){inline-size:100%;min-inline-size:0;min-block-size:48px;font-size:1rem}
.phone-login p{margin:0;font-size:13px;line-height:1.6}
.phone-login :deep(.app-button){min-block-size:48px}
.phone-code-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px}
.phone-register{display:flex;align-items:center;gap:8px;min-block-size:44px}
</style>
