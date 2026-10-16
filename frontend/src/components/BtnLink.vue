<script setup lang="ts">
/**
 * 按钮样子的链接（v2 各页大量的 `<a class="btn">`）。
 * 变体与 `CButton.vue` 共用 `styles/base.css` 的 `.c-btn*`，两者换着用不会有视觉差。
 *
 * 站内用 `to`（渲染 RouterLink，走前端路由，不整页刷新）；
 * 站外用 `href`，**必须**过 `lib/url-guard.ts` 的 `safeExternalUrl()`：
 * 值可能来自后端可写字段（如规则预设的 `official_url`），`javascript:` 是点一下就中。
 * 地址没过白名单时整个元素退化成 `<span>`，而不是渲染成 `href=""`（那会指向当前页）。
 * （模板里直接调 `safeExternalUrl()` 而不是先算进 computed：
 *  `scripts/security-check.mjs` 的 C3 规则按 `:href="safeExternalUrl(` 这个写法放行。）
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { safeExternalUrl } from '../lib/url-guard'

const props = withDefaults(
  defineProps<{
    /** 站内路由。与 href 二选一，同时给时 to 优先。 */
    to?: string
    /** 站外地址，过协议白名单后才渲染。 */
    href?: string
    variant?: 'primary' | 'ghost' | 'light' | 'danger' | 'text'
    block?: boolean
  }>(),
  { variant: 'primary', block: false },
)

const classes = computed(() => [
  'c-btn',
  props.variant === 'primary' ? null : 'c-btn--' + props.variant,
  props.block ? 'c-btn--block' : null,
])
</script>

<template>
  <RouterLink v-if="to" :to="to" :class="classes"><slot /></RouterLink>
  <a
    v-else-if="safeExternalUrl(href)"
    :href="safeExternalUrl(href)"
    :class="classes"
    target="_blank" rel="noopener noreferrer"
  >
    <slot />
  </a>
  <span v-else :class="classes" class="c-btn--inert" aria-disabled="true"><slot /></span>
</template>

<style scoped>
/* 地址没过协议白名单时退化成这个：看得出来点不动，不要伪装成一个能点的按钮 */
.c-btn--inert {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
