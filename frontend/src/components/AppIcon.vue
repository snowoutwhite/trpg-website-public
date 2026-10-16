<script setup lang="ts">
/**
 * 内联 SVG 图标，不引第三方图标库。线条 1.4px。
 * 路径表在 `./icons.ts`（那边还导出 `IconName` 供导航一类的配置做类型约束）。
 * 未知名字渲染成空 svg（不报错）：`name` 有可能来自后端的 `QuickEntry.icon`。
 */
import { computed } from 'vue'
import { ICON_PATHS } from './icons'

const props = withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })

const paths = computed<readonly string[]>(
  () => (ICON_PATHS as Record<string, readonly string[]>)[props.name] ?? [],
)
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.4"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path v-for="(d, i) in paths" :key="i" :d="d" />
  </svg>
</template>
