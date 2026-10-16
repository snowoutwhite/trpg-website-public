<script setup lang="ts">
/** 账户与通知 · 通知列表（v2 `me.html` 的 `#notif-block`）。 */
import { computed, onMounted, ref, watch } from 'vue'
import CChip from '../CChip.vue'
import CEmpty from '../CEmpty.vue'
import LoadState from '../LoadState.vue'
import PagerBar from '../PagerBar.vue'
import {
  fetchEmailPreference,
  fetchNotifications,
  markRead,
  type NotificationItem,
} from '../../api/notifications'
import { errorText } from '../../lib/api-error'
import { formatDateTime } from '../../lib/datetime'

const emit = defineEmits<{ read: [unread: number] }>()

const items = ref<NotificationItem[]>([])
const count = ref(0)
const page = ref(1)
const hasNext = ref(false)
const loading = ref(true)
const error = ref('')
const acting = ref(false)
const onlyUnread = ref(false)
/** 空串 = 不筛事件。 */
const eventFilter = ref('')
const eventLabels = ref<{ event: string; label: string }[]>([])

/**
 * 不筛事件时各次加载里见过的事件。筛选改走服务端之后，选中某个事件时 `items` 里只剩这一种，
 * 若筹码仍只按当前 `items` 算，其余筹码会全部消失、只能先点「全部」才能换档。
 */
const seenEvents = ref<Set<string>>(new Set())

const unreadOnPage = computed(() => items.value.filter((item) => !item.read_at).length)

/** 只留「本人确实收到过」的事件，免得筛选条列出 14 个多半为空的档。 */
const availableChips = computed(() =>
  eventLabels.value.filter((row) => seenEvents.value.has(row.event) || row.event === eventFilter.value),
)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchNotifications({
      unread: onlyUnread.value ? '1' : undefined,
      event: eventFilter.value || undefined,
      page: page.value,
    })
    items.value = data.results
    count.value = data.count
    hasNext.value = Boolean(data.next)
    if (!eventFilter.value) {
      seenEvents.value = new Set([...seenEvents.value, ...data.results.map((item) => item.event)])
    }
  } catch (e) {
    error.value = errorText(e, '通知列表暂时无法读取，请刷新页面后重试。')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await load()
  try {
    eventLabels.value = (await fetchEmailPreference()).available_events ?? []
  } catch {
    // 拿不到清单就只剩「全部」一个筹码，不影响列表本体
    eventLabels.value = []
  }
})

watch([onlyUnread, eventFilter], () => {
  page.value = 1
  void load()
})
watch(page, load)

async function run(ids?: number[]): Promise<void> {
  if (acting.value) return
  acting.value = true
  try {
    const result = await markRead(ids)
    emit('read', result.unread)
    await load()
  } catch (e) {
    error.value = errorText(e, '标记已读没有成功，请稍后再试一次。')
  } finally {
    acting.value = false
  }
}

function messageOf(item: NotificationItem): string {
  const message = item.payload?.message
  return typeof message === 'string' ? message : ''
}
</script>

<template>
  <section aria-labelledby="notif-head">
    <div class="head">
      <h2 id="notif-head" class="u-h-card">通知</h2>
      <button
        class="c-btn c-btn--text"
        type="button"
        :disabled="acting"
        @click="run()"
      >
        全部标为已读
      </button>
    </div>

    <div class="c-chips" role="group" aria-label="按事件类型筛选通知">
      <CChip :active="eventFilter === ''" @click="eventFilter = ''">全部</CChip>
      <CChip
        v-for="row in availableChips"
        :key="row.event"
        :active="eventFilter === row.event"
        @click="eventFilter = row.event"
      >
        {{ row.label }}
      </CChip>
      <CChip :active="onlyUnread" @click="onlyUnread = !onlyUnread">只看未读</CChip>
    </div>

    <LoadState :loading="loading" :error="error">
      <p class="u-small tally">
        本页 {{ items.length }} 条 · 未读 {{ unreadOnPage }} 条 · 共 {{ count }} 条
      </p>

      <CEmpty
        v-if="!items.length"
        compact
        title="当前筛选条件下暂时没有通知"
        text="报名结果、开团与交卡提醒、评价窗口开放、站长公告等消息都会显示在这里。切换上方的筛选条件，可以查看其他类型的通知。"
      />

      <article
        v-for="item in items"
        :key="item.id"
        class="notif"
        :class="item.read_at ? null : 'notif--unread'"
      >
        <span class="notif__dot" aria-hidden="true"></span>
        <div class="notif__body">
          <p class="u-kicker notif__event">{{ item.title }}</p>
          <p v-if="messageOf(item)" class="notif__text">{{ messageOf(item) }}</p>
          <p v-if="item.actor" class="u-small notif__actor">来自 {{ item.actor.nickname }}</p>
        </div>
        <div class="notif__side">
          <time class="u-small" :datetime="item.created_at">{{ formatDateTime(item.created_at) }}</time>
          <button
            v-if="!item.read_at"
            class="c-btn c-btn--text"
            type="button"
            :disabled="acting"
            @click="run([item.id])"
          >
            标为已读
          </button>
        </div>
      </article>

      <PagerBar
        :page="page"
        :count="count"
        :has-next="hasNext"
        @go="page = $event"
      />
    </LoadState>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-bottom: var(--sp-3);
}

.head h2 {
  margin: 0;
}

.c-chips {
  margin-bottom: var(--sp-4);
}

.tally {
  margin: 0 0 var(--sp-3);
  color: var(--ink-muted);
}

.notif {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr);
  gap: var(--sp-2) var(--sp-3);
  align-items: start;
  padding: var(--sp-4) 0;
  border-bottom: 1px solid var(--line);
}

.notif:first-of-type {
  border-top: 1px solid var(--line);
}

.notif__dot {
  width: 7px;
  height: 7px;
  margin-top: 7px;
  border-radius: 50%;
  background: transparent;
}

.notif--unread .notif__dot {
  background: var(--danger);
}

/* 正文限宽只为可读性；行本身撑满面板，时间与「标为已读」才会贴到右缘，
   与标题行右侧的「全部标为已读」同一列（v2 上手检查 2026-09-23：原先整行限 860px，
   宽屏上按钮落在屏幕中央）。 */
.notif__body {
  min-width: 0;
  max-width: 72ch;
}

.notif__event {
  margin: 0 0 var(--sp-2);
  color: var(--ink-soft);
}

.notif__text {
  margin: 0;
  font-size: var(--fs-md);
  line-height: var(--lh-body);
  overflow-wrap: anywhere;
}

.notif__actor {
  margin: var(--sp-2) 0 0;
  color: var(--ink-faint);
}

.notif__side {
  grid-column: 2;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3);
  color: var(--ink-faint);
}

@media (min-width: 768px) {
  .notif {
    grid-template-columns: 8px minmax(0, 1fr) auto;
  }

  .notif__side {
    grid-column: auto;
    flex-direction: column;
    align-items: flex-end;
    gap: var(--sp-1);
    white-space: nowrap;
  }
}
</style>
