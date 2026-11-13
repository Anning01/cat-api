<script setup lang="ts">
import { useId } from 'vue'
import { Globe, Sun, Moon } from 'lucide-vue-next'
import AppSelect from '@/components/AppSelect.vue'
import { locale, setUserLocale, tr, type AppLocale } from '@/i18n'
import { useAppThemeController, type AppThemePreference } from '@/shared/appTheme'
defineProps<{ expanded?: boolean }>()
const theme = useAppThemeController()
const formId=useId()
</script>
<template>
  <div class="console-preferences" :class="{ 'is-expanded': expanded }">
    <label :for="formId+'-field-1'"><span v-if="expanded">{{ tr('界面语言') }}</span><Globe v-else :size="17" aria-hidden="true" />
      <AppSelect :id="formId+'-field-1'" :ariaLabel="tr('界面语言')" :model-value="locale" :options="[{value:'zh',label:'简体中文'},{value:'en',label:'English'}]" :menuWidth="expanded?undefined:'auto'" density="compact" align="end" @update:model-value="setUserLocale($event as AppLocale)"/>
    </label>
    <label :for="formId+'-field-2'"><span v-if="expanded">{{ tr('外观') }}</span><Moon v-else-if="theme.resolvedTheme.value === 'dark'" :size="17" aria-hidden="true"/><Sun v-else :size="17" aria-hidden="true"/>
      <AppSelect :id="formId+'-field-2'" :ariaLabel="tr('外观')" :model-value="theme.preference.value" :options="[{value:'light',label:tr('浅色')},{value:'dark',label:tr('深色')},{value:'system',label:tr('跟随系统')}]" :menuWidth="expanded?undefined:'auto'" density="compact" align="end" @update:model-value="theme.setPreference($event as AppThemePreference)"/>
    </label>
  </div>
</template>
