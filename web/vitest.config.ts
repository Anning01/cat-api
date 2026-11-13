import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
export default defineConfig({plugins:[vue({template:{compilerOptions:{isCustomElement:tag=>tag==='search'}}})],resolve:{alias:{'@':fileURLToPath(new URL('./src',import.meta.url))}},test:{environment:'jsdom',setupFiles:['./src/testSetup.ts']}})
