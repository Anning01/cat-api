import '@fontsource-variable/manrope'
import '@fontsource-variable/noto-sans-sc'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { i18n, initializeLocale } from './i18n'
import { initializeAppTheme } from './shared/appTheme'
import router from './router'
import './styles.css'
import './app-theme.css'
import './console.css'
import './shared/dialog.css'
initializeAppTheme()
void initializeLocale().then(()=>createApp(App).use(i18n).use(createPinia()).use(router).mount('#app'))
