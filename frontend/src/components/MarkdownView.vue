<script setup lang="ts">
/** Markdown 正文渲染。**全站唯一允许使用 v-html 的组件**。 */
import { computed } from 'vue'
import { renderMarkdown } from '../lib/markdown'

const props = defineProps<{ source: string }>()

const html = computed(() => renderMarkdown(props.source))
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- 内容已经过 renderMarkdown 白名单 sanitize -->
  <div class="md" v-html="html" />
</template>

<style scoped>
/* ---- 长文正文：16 / 1.7 / --read-ink（v2 report.html、guide 正文同一套） ---- */
.md {
  font-size: var(--fs-lg);
  line-height: var(--lh-body);
  color: var(--read-ink);
}

.md :deep(h1),
.md :deep(h2),
.md :deep(h3),
.md :deep(h4) {
  font-family: var(--font-sans);
  line-height: var(--lh-tight);
  letter-spacing: var(--ls-section);
  margin: var(--sp-6) 0 var(--sp-3);
}

.md :deep(h1) {
  font-size: var(--fs-h-section);
}

/* v2 的正文 h2 靠一条**上**分隔线分段（不是下划线），本站没有 24px 这一档令牌，
   取最接近的 --fs-2xl（20px），不为一页新造令牌。 */
.md :deep(h2) {
  font-size: var(--fs-2xl);
  margin-top: var(--sp-7);
  padding-top: var(--sp-5);
  border-top: 1px solid var(--line);
}

.md :deep(h3),
.md :deep(h4) {
  font-size: var(--fs-xl);
  color: var(--ink-soft);
}

.md :deep(:first-child) {
  margin-top: 0;
}

/* 首段就是 h2 时，上分隔线会贴在正文最顶上，去掉 */
.md :deep(h2:first-child) {
  padding-top: 0;
  border-top: 0;
}

.md :deep(p) {
  margin: 0 0 var(--sp-4);
}

.md :deep(ul),
.md :deep(ol) {
  margin: 0 0 var(--sp-4);
  padding-left: var(--sp-5);
}

.md :deep(li) {
  margin-bottom: var(--sp-2);
}

.md :deep(li)::marker {
  color: var(--brand);
}

/* 引用块：v2 长文只留一条左竖线，不做成框（原来是朱砂批注框，旧方向已作废） */
.md :deep(blockquote) {
  margin: 0 0 var(--sp-4);
  padding: 2px 0 2px var(--sp-5);
  border: 0;
  border-left: 2px solid var(--line-2);
  background: none;
  line-height: var(--lh-read);
  color: var(--ink-soft);
}

.md :deep(blockquote p:last-child) {
  margin-bottom: 0;
}

.md :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.92em;
  padding: 1px 4px;
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.md :deep(pre) {
  margin: 0 0 var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  background: var(--bg-2);
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
  /* 宽内容自己滚，页面 body 永远不横向滚动 */
  overflow-x: auto;
}

.md :deep(pre code) {
  padding: 0;
  border: 0;
  background: none;
}

/* 表格同样自带横向滚动容器 */
.md :deep(table) {
  display: block;
  width: max-content;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
  margin: 0 0 var(--sp-4);
  font-size: var(--fs-md);
}

.md :deep(th),
.md :deep(td) {
  border: 1px solid var(--line);
  padding: var(--sp-2) var(--sp-3);
  text-align: left;
}

.md :deep(th) {
  background: var(--bg-2);
  font-weight: 600;
}

.md :deep(hr) {
  border: 0;
  border-top: 1px solid var(--line);
  margin: var(--sp-6) 0;
}

/* 正文插图按整栏走（v2 report.html 的 .post img），图未载入时露出底色而不是空洞 */
.md :deep(img) {
  width: 100%;
  border: 0;
  border-radius: var(--radius);
  background: var(--bg-2);
}

/* 正文里的行内链接：品牌墨绿 + 够大的触控区（≥40px，移动端硬约束） */
.md :deep(a) {
  display: inline-block;
  min-height: 40px;
  padding: var(--sp-2) 0;
  line-height: 24px;
  color: var(--brand-ink);
}
</style>
