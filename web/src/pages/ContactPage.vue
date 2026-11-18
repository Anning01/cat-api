<script setup lang="ts">
import { computed, ref } from 'vue'
import { Copy } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import ConsolePage from '@/components/ConsolePage.vue'
import groupQr from '@/assets/contact/group.jpg'
import group from '@/assets/contact/group.json'
import officialQr from '@/assets/contact/official.png'
import personalQr from '@/assets/contact/personal.jpg'
import { dateLocale, tr } from '@/i18n'
import { notice } from '@/shared/notice'

const wechatId = 'anningforchina'
const groupExpiry = new Date(group.validBefore + 'T00:00:00+08:00')
const groupExpired = Date.now() >= groupExpiry.getTime()
const expiryDate = computed(() => new Intl.DateTimeFormat(dateLocale.value, {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: 'long', day: 'numeric',
}).format(groupExpiry))
const unavailable = ref({ personal: false, official: false, group: false })
const groupAvailable = computed(() => !groupExpired && !unavailable.value.group)

async function copyWechatId() {
  try {
    await navigator.clipboard.writeText(wechatId)
    notice.success(tr('微信号已复制'))
  } catch {
    notice.error(tr('复制失败，请手动复制微信号。'))
  }
}
</script>

<template>
  <ConsolePage :title="tr('联系我们')" class="contact-page">
    <div class="contact-layout">
      <div class="contact-panel contact-people">
        <article class="contact-channel">
          <header>
            <h2>{{ tr('个人微信') }}</h2>
            <p>{{ tr('账号找回与使用问题') }}</p>
          </header>
          <a
            v-if="!unavailable.personal"
            class="contact-image contact-portrait-image"
            :href="personalQr"
            target="_blank"
            rel="noopener"
          >
            <img
              :src="personalQr"
              :alt="tr('个人微信二维码')"
              width="888"
              height="1131"
              @error="unavailable.personal=true"
            />
          </a>
          <p v-else>{{ tr('二维码暂不可用') }}</p>
          <footer class="contact-channel-footer contact-wechat">
            <dl>
              <dt>{{ tr('微信号') }}</dt>
              <dd>{{ wechatId }}</dd>
            </dl>
            <AppButton type="button" size="sm" variant="secondary" @click="copyWechatId">
              <Copy :size="15" aria-hidden="true" />{{ tr('复制微信号') }}
            </AppButton>
          </footer>
        </article>

        <article class="contact-channel">
          <header>
            <h2>{{ tr('微信交流群') }}</h2>
            <p v-if="groupAvailable">{{ tr('微信扫一扫加入群聊') }}</p>
          </header>
          <a
            v-if="groupAvailable"
            class="contact-image contact-portrait-image"
            :href="groupQr"
            target="_blank"
            rel="noopener"
          >
            <img
              :src="groupQr"
              :alt="tr('微信群二维码')"
              width="1050"
              height="1602"
              @error="unavailable.group=true"
            />
          </a>
          <p v-else>{{ tr(groupExpired ? '群二维码已过期，请通过个人微信获取新码。' : '二维码暂不可用') }}</p>
          <footer v-if="groupAvailable" class="contact-channel-footer">
            <time :datetime="group.validBefore">{{ tr('{p0}前有效', {p0:expiryDate}) }}</time>
          </footer>
        </article>
      </div>

      <article class="contact-panel contact-channel contact-official">
        <header>
          <h2>{{ tr('猫影短剧公众号') }}</h2>
          <p v-if="!unavailable.official">{{ tr('微信扫一扫关注公众号') }}</p>
        </header>
        <a v-if="!unavailable.official" class="contact-image" :href="officialQr" target="_blank" rel="noopener">
          <img :src="officialQr" :alt="tr('公众号关注二维码')" width="1710" height="624" @error="unavailable.official=true" />
        </a>
        <p v-else>{{ tr('二维码暂不可用') }}</p>
      </article>
    </div>
  </ConsolePage>
</template>

<style scoped>
.contact-page { container-type: inline-size; }
.contact-page :deep(.console-page-header) { min-block-size: 0; }
.contact-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
  gap: 16px;
}
.contact-panel {
  min-inline-size: 0;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  background: var(--app-surface);
}
.contact-people {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.contact-people article + article { border-inline-start: 1px solid var(--app-border); }
.contact-channel {
  display: grid;
  grid-template-rows: auto 1fr auto;
  gap: 16px;
  min-inline-size: 0;
  padding: 20px;
}
.contact-channel header { display: grid; align-content: start; gap: 4px; }
.contact-channel h2 { margin: 0; font-size: 17px; line-height: 1.45; font-weight: 700; }
.contact-channel p { margin: 0; color: var(--app-text-secondary); font-size: 13px; line-height: 1.55; }
.contact-channel-footer {
  display: flex;
  align-items: center;
  min-block-size: 60px;
  padding: 10px 12px;
  color: var(--app-text-secondary);
  background: var(--app-surface-muted);
  border-radius: 8px;
  font-size: 13px;
}
.contact-wechat { flex-wrap: wrap; justify-content: space-between; gap: 8px; }
.contact-wechat dl { display: grid; gap: 2px; margin: 0; min-inline-size: 0; }
.contact-wechat dt { font-size: 12px; }
.contact-wechat dd {
  margin: 0;
  color: var(--app-text);
  font-size: 15px;
  font-weight: 700;
  overflow-wrap: anywhere;
  user-select: all;
}
.contact-image {
  display: block;
  align-self: center;
  justify-self: center;
  max-inline-size: 100%;
  overflow: clip;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: white;
}
.contact-image img { display: block; max-inline-size: 100%; block-size: auto; }
.contact-portrait-image img { inline-size: auto; max-block-size: 21rem; }
.contact-official {
  grid-template-rows: auto 1fr;
  background: color-mix(in srgb, var(--app-surface) 78%, var(--app-accent-soft));
}
.contact-official .contact-image { inline-size: min(100%, 46rem); }
@container (max-width:64rem) {
  .contact-layout { grid-template-columns: minmax(0, 1fr); }
}
@container (max-width:37rem) {
  .contact-people { grid-template-columns: minmax(0, 1fr); }
  .contact-people article + article { border-inline-start: 0; border-block-start: 1px solid var(--app-border); }
  .contact-channel { padding: 16px; }
}
</style>
