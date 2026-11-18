<script setup lang="ts">
import { useId } from 'vue'
import { tr } from '@/i18n'

const agreed = defineModel<boolean>({ required: true })
const id = useId()
</script>

<template>
  <div class="login-agreement">
    <input :id="id" v-model="agreed" name="agreed" type="checkbox" />
    <label :for="id">{{ tr('我已阅读并同意') }}
      <a href="/api/auth/legal/terms" target="_blank" rel="noopener">{{ tr('用户协议') }}</a>
      {{ tr('和') }}
      <a href="/api/auth/legal/privacy" target="_blank" rel="noopener">{{ tr('隐私政策') }}</a>
    </label>
  </div>
</template>

<style scoped>
.login-agreement{display:flex;align-items:baseline;gap:8px;color:var(--app-text-secondary);font-size:13px;line-height:1.6}
.login-agreement input{flex:none;margin:0;inline-size:16px;block-size:16px;align-self:flex-start;margin-block-start:3px}
.login-agreement label{flex:1;cursor:pointer}
.login-agreement a{color:var(--app-accent);text-decoration:underline;text-underline-offset:3px}
</style>
