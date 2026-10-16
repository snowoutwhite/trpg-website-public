<script setup lang="ts">
/**
 * 卡面（v2 全站卡片的共同底：白面 + 细线 + 6px 圆角）。
 * 视觉在 `styles/base.css` 的全局 `.c-card` / `.c-card--raised`。
 *
 * `flush` 给「整块就是一张图」的卡用（图卡、相册格）：去掉内边距并裁切溢出，
 * 免得每个用到的页面各写一遍 `padding: 0; overflow: hidden`。
 */
withDefaults(
  defineProps<{
    /** 语义标签：列表项用 article，分区用 section。 */
    as?: 'div' | 'article' | 'section' | 'li'
    /** 去描边、改用弥散阴影浮起（v2 hover 抬升的静态版）。 */
    raised?: boolean
    /** 去内边距 + 裁切溢出，用于整块是图的卡。 */
    flush?: boolean
  }>(),
  { as: 'div', raised: false, flush: false },
)
</script>

<template>
  <component
    :is="as"
    class="c-card"
    :class="[raised ? 'c-card--raised' : null, flush ? 'c-card--flush' : null]"
  >
    <slot />
  </component>
</template>

<style scoped>
.c-card--flush {
  padding: 0;
  overflow: hidden;
}
</style>
