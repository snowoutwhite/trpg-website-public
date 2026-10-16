<script setup lang="ts">
/** 「我的」通用行（v2 `me.html` 的 `.row`：缩略图 + 正文列 + 操作列）。 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useHomeStore } from '../../stores/home'
import { ruleArtFile } from '../../lib/rule-art'

const props = withDefaults(
  defineProps<{
    title: string
    /** 标题的站内去向；不给就是纯文字标题。 */
    to?: string
    /** 规则系统名，用来取缩略图；不给（或 `noimg`）就不渲染图。 */
    rule?: string
    /** 第二行的事实串，逐条渲染成小字。 */
    meta?: string[]
    /** 第三行的说明句。 */
    sub?: string
    /** 没有缩略图的行（评价、举报）。 */
    noimg?: boolean
  }>(),
  { to: '', rule: '', meta: () => [], sub: '', noimg: false },
)

const home = useHomeStore()

/** 同源相对路径或 http(s) 绝对地址；引号、括号、反斜杠、空白一律不收（与 BlurStage 同口径）。 */
const SAFE_IMAGE_URL = /^(?:https?:\/\/[^"'()\\\s]+|\/[^"'()\\\s]*)$/

const thumb = computed(() => {
  const image = home.presetByName(props.rule)?.image
  for (const candidate of [image?.thumb, image?.card, image?.full]) {
    if (candidate && SAFE_IMAGE_URL.test(candidate) && !/^\/[/\\]/.test(candidate)) return candidate
  }
  return ruleArtFile(props.rule)
})
</script>

<template>
  <article class="row" :class="noimg ? 'row--noimg' : null">
    <img v-if="!noimg" class="row__thumb" :src="thumb" alt="" loading="lazy" />
    <div class="row__main">
      <h3 class="row__title">
        <RouterLink v-if="to" :to="to">{{ title }}</RouterLink>
        <span v-else>{{ title }}</span>
        <slot name="marks" />
      </h3>
      <p v-if="meta.length" class="row__meta">
        <span v-for="(item, i) in meta" :key="i">{{ item }}</span>
      </p>
      <p v-if="sub || $slots.sub" class="row__sub">{{ sub }}<slot name="sub" /></p>
      <slot />
    </div>
    <div v-if="$slots.act" class="row__act"><slot name="act" /></div>
  </article>
</template>

<style scoped>
.row {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  align-items: start;
  gap: var(--sp-2) var(--sp-4);
  padding: var(--sp-4) 0;
  border-bottom: 1px solid var(--line);
}

.row:first-of-type {
  border-top: 1px solid var(--line);
}

.row--noimg {
  grid-template-columns: minmax(0, 1fr);
}

.row__thumb {
  width: 72px;
  height: 54px;
  object-fit: cover;
  border-radius: var(--radius);
  background: var(--thumb-bg);
}

.row__main {
  min-width: 0;
}

.row__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: 400;
  line-height: var(--lh-card);
}

/** 业务界面遵循后端权限与隐私约束。 */
/** 业务界面遵循后端权限与隐私约束。 */
.row__title a {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  min-height: 40px;
  overflow-wrap: anywhere;
  color: var(--ink);
  text-decoration: none;
}

.row__title a:hover {
  text-decoration: underline;
  text-underline-offset: 4px;
}

.row__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-4);
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-wide);
  color: var(--ink-muted);
}

.row__sub {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
  color: var(--ink-muted);
  overflow-wrap: anywhere;
}

.row__act {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2) var(--sp-3);
  grid-column: 1 / -1;
  align-items: center;
}

@media (min-width: 768px) {
  .row {
    grid-template-columns: 88px minmax(0, 1fr);
    align-items: center;
  }

  .row__thumb {
    width: 88px;
    height: 64px;
  }
}

/* 宽屏：正文列限宽，操作列紧跟其后并在各行对齐，不甩到窗口最右（v2 `@media (min-width:1000px)`） */
@media (min-width: 1200px) {
  .row {
    grid-template-columns: 88px minmax(0, 620px) auto;
    justify-content: start;
    column-gap: var(--sp-6);
  }

  .row--noimg {
    grid-template-columns: minmax(0, 720px) auto;
  }

  .row__act {
    grid-column: auto;
    justify-content: flex-end;
  }
}
</style>
