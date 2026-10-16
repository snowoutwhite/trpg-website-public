<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import LoadState from '../components/LoadState.vue'
import PageHead from '../components/PageHead.vue'
import PagerBar from '../components/PagerBar.vue'
import { fetchAnnouncements, type SiteAnnouncement } from '../api/home'
import { errorText } from '../lib/api-error'
import { formatDateTime } from '../lib/datetime'

const items = ref<SiteAnnouncement[]>([])
const count = ref(0)
const page = ref(1)
const hasNext = ref(false)
const loading = ref(true)
const error = ref('')

async function load(next = page.value): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchAnnouncements({ page: next })
    items.value = data.results
    count.value = data.count
    hasNext.value = Boolean(data.next)
    page.value = next
  } catch (e) {
    error.value = errorText(e, '公告历史暂时无法读取，请刷新后重试。')
    items.value = []
  } finally {
    loading.value = false
  }
}

function go(next: number): void {
  void load(next)
  window.scrollTo({ top: 0 })
}

onMounted(() => void load(1))
</script>

<template>
  <div class="l-narrow">
    <PageHead
      eyebrow="ANNOUNCEMENTS"
      title="站长公告"
      lead="站主发布过的所有公告都会保留在本页，最新发布的排在最前面。每条公告发布时，本站所有成员都会收到一条站内通知。"
    >
      <template #aside>
        <RouterLink class="c-textlink" to="/">← 返回首页</RouterLink>
      </template>
    </PageHead>

    <LoadState
      :loading="loading"
      :error="error"
      :empty="!items.length"
      empty-title="暂时没有公告"
      empty-text="站主暂时还没有发布过公告。以后发布的公告会显示在此处，同时每位成员都会收到一条站内通知。"
    >
      <ol class="list">
        <li v-for="item in items" :key="item.id" class="row">
          <p class="row__at u-small">
            <span>{{ formatDateTime(item.published_at) }}</span>
            <span v-if="item.author">{{ item.author.nickname }}</span>
            <span v-if="item.is_read === true" class="c-tag c-tag--mute">已读</span>
          </p>
          <h2 class="row__title u-h-card">{{ item.title }}</h2>
          <p class="row__body">{{ item.body }}</p>
        </li>
      </ol>

      <PagerBar :page="page" :count="count" :has-next="hasNext" @go="go" />
    </LoadState>
  </div>
</template>

<style scoped>
.list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.row {
  padding: var(--sp-5) 0;
  border-top: 1px solid var(--line);
}

.row:last-child {
  border-bottom: 1px solid var(--line);
}

.row__at {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-3);
  margin: 0;
}

.row__title {
  margin: var(--sp-2) 0 0;
  color: var(--ink);
}

.row__body {
  margin: var(--sp-3) 0 0;
  font-size: var(--fs-base);
  line-height: var(--lh-read);
  color: var(--ink-soft);
  /* 站主敲的换行要保留：正文是纯文本字段，不走 Markdown */
  white-space: pre-line;
}

@media (min-width: 768px) {
  .row {
    padding: var(--sp-6) 0;
  }
}
</style>
