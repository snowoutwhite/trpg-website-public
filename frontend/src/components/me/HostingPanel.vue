<script setup lang="ts">
/** 我的团 · 我主持的（v2 `me.html` 的 `#sp-hosting`）。 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import CChip from '../CChip.vue'
import CPill from '../CPill.vue'
import LoadState from '../LoadState.vue'
import PagerBar from '../PagerBar.vue'
import MeRow from './MeRow.vue'
import { errorText } from '../../lib/api-error'
import { formatDateTime } from '../../lib/datetime'
import {
  fetchGames,
  GAME_STATUS_OPTIONS,
  type GameListItem,
  type GameStatus,
} from '../../api/games'

const props = defineProps<{ userId: number | null }>()

const games = ref<GameListItem[]>([])
const count = ref(0)
const page = ref(1)
const hasNext = ref(false)
const loading = ref(true)
const error = ref('')
const status = ref<GameStatus | ''>('')

const myId = computed(() => props.userId ?? 0)

/** 团状态 → 胶囊色档；文案仍用后端 `status_display`。 */
function toneOf(item: GameListItem): 'ok' | 'wait' | 'warn' | 'off' {
  if (item.status === 'recruiting') return 'ok'
  if (item.status === 'closed_signup' || item.status === 'running') return 'wait'
  if (item.status === 'cancelled') return 'off'
  return 'off'
}

function metaOf(item: GameListItem): string[] {
  const meta = [item.rule_system, '开团 ' + formatDateTime(item.start_at), item.mode_display]
  meta.push('占位 ' + item.occupied_seats + ' / ' + item.max_players)
  meta.push('已通过 ' + item.accepted_count)
  for (const tag of item.tags) meta.push(tag)
  return meta
}

async function load(): Promise<void> {
  if (!myId.value) return
  loading.value = true
  error.value = ''
  try {
    const data = await fetchGames({ gm: myId.value, status: status.value, page: page.value })
    games.value = data.results
    count.value = data.count
    hasNext.value = Boolean(data.next)
  } catch (e) {
    error.value = errorText(e, '团列表暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.userId, load)
watch(status, () => {
  page.value = 1
  void load()
})
watch(page, load)
</script>

<template>
  <section aria-labelledby="hosting-head">
    <div class="head">
      <h2 id="hosting-head" class="u-h-card">我主持的团</h2>
      <RouterLink class="c-textlink" to="/games/new">放一个新团 →</RouterLink>
    </div>

    <div class="c-chips" role="group" aria-label="按状态筛选">
      <CChip
        v-for="option in GAME_STATUS_OPTIONS"
        :key="option.value"
        :active="status === option.value"
        @click="status = option.value"
      >
        {{ option.label }}
      </CChip>
    </div>

    <LoadState
      :loading="loading"
      :error="error"
      :empty="!games.length"
      empty-title="当前筛选条件下没有你主持的团"
      empty-text="你发布过的团都会列在此处。审批报名名单和结团，请在对应团页面的「管理」标签中操作。"
    >
      <template #empty-actions>
        <RouterLink class="c-btn" to="/games/new">放一个新团</RouterLink>
      </template>

      <MeRow
        v-for="item in games"
        :key="item.id"
        :title="item.title"
        :to="'/games/' + item.id"
        :rule="item.rule_system"
        :meta="metaOf(item)"
        :sub="item.status === 'finished' ? '此团已结团。结团后的一段时间内，成员可以向团相册上传照片，也可以互相评价。' : ''"
      >
        <template #marks>
          <CPill :tone="toneOf(item)">{{ item.status_display }}</CPill>
        </template>
        <template #act>
          <RouterLink class="c-btn c-btn--ghost" :to="'/games/' + item.id + '#manage'">管理</RouterLink>
          <RouterLink class="c-textlink" :to="'/games/' + item.id + '/edit'">改公告 →</RouterLink>
        </template>
      </MeRow>

      <PagerBar :page="page" :count="count" :has-next="hasNext" @go="page = $event" />
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
  margin: 0 0 var(--sp-4);
}
</style>
