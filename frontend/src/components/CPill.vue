<script setup lang="ts">
/** 状态胶囊（v2 `me.html` 的 `.pill` 三态 + 本站补的两档）。 */
const TONE_CLASS = {
  ok: 'c-pill--ok',
  wait: 'c-pill--warn',
  warn: 'c-pill--danger',
  danger: 'c-pill--strong',
  off: 'c-pill--off',
} as const

withDefaults(defineProps<{ tone?: keyof typeof TONE_CLASS }>(), { tone: 'off' })
</script>

<template>
  <span class="c-pill" :class="TONE_CLASS[tone]"><slot /></span>
</template>
