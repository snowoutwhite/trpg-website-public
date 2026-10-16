<script setup lang="ts">
/**
 * 战报列表里的一行（目录条目形态，不是卡片）。
 * 战报列表、团内战报、我的战报三处共用，别再各写一遍。
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from './AppIcon.vue'
import UserChip from './UserChip.vue'
import type { ReportListItem } from '../api/reports'
import { formatDate } from '../lib/datetime'

const props = withDefaults(defineProps<{ report: ReportListItem; showGame?: boolean }>(), {
  showGame: true,
})

/**
 * 摘要是后端截的 Markdown 原文前 200 字，直接显示会带着 `## ` `> ` 这些记号。
 * 这里只做「去掉行首记号、把换行压成空格」的朴素清理——**仍然是插值渲染**，
 * 不解析 Markdown、不产出 HTML（列表里没必要为一行摘要拉起 sanitize 那一整套）。
 */
const excerpt = computed(() =>
  (props.report.excerpt || '')
    .split('\n')
    .map((line) => line.replace(/^\s*(#{1,6}\s+|>\s?|[-*+]\s+|\d+\.\s+)/, '').trim())
    .filter(Boolean)
    .join(' ')
    .replace(/[*_`]/g, ''),
)
</script>

<template>
  <RouterLink class="c-entry" :to="'/reports/' + report.id">
    <AppIcon class="mark" name="notice" :size="18" />
    <span class="c-entry__body">
      <span class="c-entry__title">
        {{ report.title }}
        <span v-if="report.is_featured" class="c-tag c-tag--seal">精选</span>
        <span v-if="report.visibility === 'same_game'" class="c-tag c-tag--mute">仅同团可见</span>
      </span>
      <span v-if="excerpt" class="c-entry__desc">{{ excerpt }}</span>
      <span class="c-meta">
        <UserChip :user="report.author" :link="false" :size="22" />
        <span v-if="showGame">《{{ report.game.title }}》</span>
        <span v-if="report.attachment_count">附件 {{ report.attachment_count }}</span>
        <span>{{ formatDate(report.created_at) }}</span>
      </span>
    </span>
    <AppIcon class="c-entry__arrow" name="arrow" :size="18" />
  </RouterLink>
</template>

<style scoped>
.mark {
  flex: none;
  width: 2.4em;
  color: var(--brand);
  align-self: flex-start;
  margin-top: 2px;
}

.c-entry__title .c-tag {
  margin-left: var(--sp-2);
  vertical-align: middle;
}
</style>
