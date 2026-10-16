<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { storeToRefs } from 'pinia'
import { computed } from 'vue'
import EditableText from './edit/EditableText.vue'
import { CONFIG_MAX } from '../api/homeAdmin'
import { useEditStore } from '../stores/edit'
import { useHomeStore } from '../stores/home'
import { useSiteStore } from '../stores/site'

const site = useSiteStore()
const home = useHomeStore()
const edit = useEditStore()
const { config } = storeToRefs(site)

const siteName = computed(() => home.site?.site_name || config.value.site_name)
const tagline = computed(() => home.footerTagline)

function toTop(): void {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
</script>

<template>
  <footer class="c-foot-bar" :class="{ 'is-editing': edit.active }">
    <p class="c-foot-bar__line">
      <span v-if="!edit.active" class="c-foot-bar__name">{{ siteName }}</span>
      <EditableText
        v-else
        class="c-foot-bar__name"
        inline
        :value="edit.configValue('site_name') ?? ''"
        label="站名"
        :max="CONFIG_MAX.site_name"
        :error="edit.fieldErrors['config.site_name'] ?? ''"
        @update:value="edit.setConfig('site_name', $event)"
      />
      <template v-if="tagline && !edit.active">
        <span class="c-foot-bar__sep" aria-hidden="true">·</span>
        <span>{{ tagline }}</span>
      </template>
      <template v-else-if="edit.active">
        <span class="c-foot-bar__sep" aria-hidden="true">·</span>
        <EditableText
          inline
          :value="edit.configValue('footer_tagline') ?? ''"
          label="页脚署名句"
          :max="CONFIG_MAX.footer_tagline"
          :error="edit.fieldErrors['config.footer_tagline'] ?? ''"
          @update:value="edit.setConfig('footer_tagline', $event)"
        />
      </template>
    </p>

    <p v-if="config.icp_beian" class="c-foot-bar__line">
      <a
        class="c-foot-bar__link"
        href="https://beian.miit.gov.cn/"
        target="_blank" rel="noopener noreferrer"
      >
        {{ config.icp_beian }}
      </a>
    </p>

    <p class="c-foot-bar__line">
      <button class="c-foot-bar__link c-foot-bar__top" type="button" @click="toTop">
        返回顶部 ↑
      </button>
    </p>
  </footer>
</template>

<style scoped>
.c-foot-bar {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--sp-2) var(--sp-5);
  /* 手机上让开固定底栏 + 安全区 */
  padding: var(--sp-5) var(--pad) calc(var(--sp-5) + var(--bottom-nav-h) + var(--safe-bottom));
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-faint);
  background: var(--bg);
  border-top: 1px solid var(--line);
}

.c-foot-bar__line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
}

.c-foot-bar__name {
  letter-spacing: var(--ls-caps);
  color: var(--ink-muted);
}

.c-foot-bar__sep {
  color: var(--line-2);
}

/** 业务界面遵循后端权限与隐私约束。 */
.c-foot-bar__link {
  display: inline-flex;
  align-items: center;
  min-height: 40px;
  padding: 0;
  font: inherit;
  letter-spacing: inherit;
  color: inherit;
  background: none;
  border: 0;
  text-decoration: none;
}

.c-foot-bar__link:hover {
  color: var(--brand-ink);
}

/* 编辑态：按保存条**实测的**高度让路（`--edit-bar-h` 由 `edit/EditBar.vue` 在运行时写，
   它自己的高度已经含安全区，所以这里不再叠 --safe-bottom）。手机底栏此时是隐藏的。 */
.c-foot-bar.is-editing {
  padding-bottom: calc(var(--sp-5) + var(--edit-bar-h, 76px));
}

@media (min-width: 768px) {
  .c-foot-bar {
    /* ≥768px 底栏隐藏，不再预留它的高度 */
    padding-bottom: var(--sp-5);
  }

  .c-foot-bar.is-editing {
    padding-bottom: calc(var(--sp-5) + var(--edit-bar-h, 76px));
  }
}
</style>
