<script setup lang="ts">
/**
 * 单篇新人指南（v2 长文版式：单栏 800 净宽、16px/1.7 正文墨）。
 * 正文是 Markdown，交给 `MarkdownView`（marked + DOMPurify 白名单）—— 全站唯一的 v-html 出口。
 *
 * 顺带拉一次指南目录，为了 v2 `guide.html` 的两件事：标题上方的「第 N 篇 / 共 M 篇」，
 * 与正文末尾的上一篇 / 下一篇。目录拉失败不影响正文（那两块自己隐藏）。
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import LoadState from '../components/LoadState.vue'
import MarkdownView from '../components/MarkdownView.vue'
import { fetchGuide, fetchGuides, type GuideDetail, type GuideSummary } from '../api/content'
import { errorText } from '../lib/api-error'

const route = useRoute()
const guide = ref<GuideDetail | null>(null)
const siblings = ref<GuideSummary[]>([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  const [detail, list] = await Promise.allSettled([
    fetchGuide(String(route.params.slug ?? '')),
    fetchGuides(),
  ])
  if (detail.status === 'fulfilled') guide.value = detail.value
  else error.value = errorText(detail.reason, '这篇指南暂时无法读取，请刷新后重试。')
  if (list.status === 'fulfilled') siblings.value = list.value
  loading.value = false
})

/** 本篇在目录里的位置；目录没拉到（或这篇未发布）时是 -1，上下篇与序号一起隐藏。 */
const at = computed(() =>
  guide.value ? siblings.value.findIndex((item) => item.slug === guide.value?.slug) : -1,
)

const indexLabel = computed(() =>
  at.value >= 0 ? '第 ' + (at.value + 1) + ' 篇 / 共 ' + siblings.value.length + ' 篇' : '',
)

const prev = computed(() => (at.value > 0 ? siblings.value[at.value - 1] : null))
const next = computed(() =>
  at.value >= 0 && at.value < siblings.value.length - 1 ? siblings.value[at.value + 1] : null,
)

function formatDate(value?: string): string {
  if (!value) return ''
  return new Date(value).toLocaleDateString('zh-CN')
}
</script>

<template>
  <div class="l-narrow doc u-rise">
    <RouterLink class="c-back" to="/guide">
      <AppIcon name="back" :size="16" />
      手册 · 新人指南
    </RouterLink>

    <LoadState :loading="loading" :error="error">
      <article v-if="guide">
        <p v-if="indexLabel" class="u-kicker">{{ indexLabel }}</p>
        <h1 class="u-h-display doc__title">{{ guide.title }}</h1>
        <p class="u-small doc__stamp">最后更新 {{ formatDate(guide.updated_at) }}</p>

        <div class="doc__body">
          <MarkdownView :source="guide.body_markdown" />
        </div>

        <nav v-if="at >= 0" class="doc__nav" aria-label="上一篇 / 下一篇">
          <RouterLink v-if="prev" class="c-textlink" :to="'/guide/' + prev.slug">
            ← {{ prev.title }}
          </RouterLink>
          <span v-else class="u-small">已是第一篇</span>
          <RouterLink v-if="next" class="c-textlink doc__next" :to="'/guide/' + next.slug">
            {{ next.title }} →
          </RouterLink>
          <span v-else class="u-small doc__next">已是最后一篇</span>
        </nav>
      </article>
    </LoadState>
  </div>
</template>

<style scoped>
.doc__title {
  margin: var(--sp-2) 0 var(--sp-3);
}

.doc__stamp {
  margin: 0 0 var(--sp-6);
}

/** 业务界面遵循后端权限与隐私约束。 */
.doc__body :deep(.md p),
.doc__body :deep(.md li) {
  line-height: var(--lh-read);
}

.doc__nav {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--sp-3) var(--sp-4);
  margin-top: var(--sp-6);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--line);
}

.doc__next {
  margin-left: auto;
  text-align: right;
}
</style>
