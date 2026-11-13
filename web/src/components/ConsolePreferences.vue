<script setup lang="ts">
import { useId } from 'vue'
import { Globe, Sun, Moon } from 'lucide-vue-next'
import { locale, setUserLocale, tr, type AppLocale } from '@/i18n'
import { useAppThemeController, type AppThemePreference } from '@/shared/appTheme'
defineProps<{ expanded?: boolean }>()
const theme = useAppThemeController()
const formId=useId()
</script>
<template>
  <div class="console-preferences" :class="{ 'is-expanded': expanded }">
    <label :for="formId+'-field-1'"><span v-if="expanded">{{ tr('界面语言') }}</span><Globe v-else :size="17" aria-hidden="true" />
      <select name="field-1" :id="formId+'-field-1'" :aria-label="tr('界面语言')" :value="locale" @change="setUserLocale(($event.target as HTMLSelectElement).value as AppLocale)"><option value="zh">简体中文</option><option value="en">English</option></select>
    </label>
    <label :for="formId+'-field-2'"><span v-if="expanded">{{ tr('外观') }}</span><Moon v-else-if="theme.resolvedTheme.value === 'dark'" :size="17" aria-hidden="true"/><Sun v-else :size="17" aria-hidden="true"/>
      <select name="field-2" :id="formId+'-field-2'" :aria-label="tr('外观')" :value="theme.preference.value" @change="theme.setPreference(($event.target as HTMLSelectElement).value as AppThemePreference)"><option value="light">{{ tr('浅色') }}</option><option value="dark">{{ tr('深色') }}</option><option value="system">{{ tr('跟随系统') }}</option></select>
    </label>
  </div>
</template>
