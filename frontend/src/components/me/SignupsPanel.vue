<script setup lang="ts">
/** 我的团 · 我报名的（v2 `me.html` 的 `#sp-signed`）。 */
import { onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import CChip from '../CChip.vue'
import CNotice from '../CNotice.vue'
import CPill from '../CPill.vue'
import LoadState from '../LoadState.vue'
import PagerBar from '../PagerBar.vue'
import MeRow from './MeRow.vue'
import { errorText } from '../../lib/api-error'
import { formatDateTime } from '../../lib/datetime'
import {
  fetchMySignups,
  GAME_STATUS_OPTIONS,
  type GameStatus,
  type MySignup,
  type SignupStatus,
} from '../../api/games'

const items = ref<MySignup[]>([])
const count = ref(0)
const page = ref(1)
const hasNext = ref(false)
const loading = ref(true)
const error = ref('')
const gameStatus = ref<GameStatus | ''>('')

/** 报名状态 → 胶囊色档。文案一律用后端 `status_display`，这里只决定颜色。 */
const TONE: Record<SignupStatus, 'ok' | 'wait' | 'warn' | 'off'> = {
  pending: 'warn',
  submitted: 'wait',
  accepted: 'ok',
  rejected: 'off',
  withdrawn: 'off',
  removed: 'off',
  no_card: 'off',
}

/** 这一条还需要本人动手吗（要动手的给实心按钮，其余给文字链）。 */
function needsAction(item: MySignup): boolean {
  return item.status === 'pending' || item.status === 'submitted'
}

function metaOf(item: MySignup): string[] {
  const meta = [item.game.status_display, '开团 ' + formatDateTime(item.game.start_at)]
  meta.push('报名顺序 第 ' + item.order + ' 位')
  if (!item.game.requires_card) meta.push('免交卡团')
  else if (item.card) meta.push('已交：' + item.card.name + (item.card_uploaded_by_gm ? '（GM 代传）' : ''))
  else meta.push('交卡截止 ' + formatDateTime(item.game.card_deadline))
  if (item.attended) meta.push('已登记到场')
  return meta
}

function subOf(item: MySignup): string {
  if (item.review_note) return 'GM 备注：' + item.review_note
  if (item.status === 'pending' && item.game.requires_card) {
    return '此团需要交角色卡。如果在交卡截止时间之前没有交卡，你的席位会被自动释放。'
  }
  if (item.status === 'submitted') return '你已交卡，正在等待 GM 审核。审核通过之前，你仍然可以更换角色卡。'
  if (item.withdraw_requested_at) return '你已提交退出申请，正在等待本团 GM 确认。'
  return ''
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchMySignups({ game_status: gameStatus.value, page: page.value })
    items.value = data.results
    count.value = data.count
    hasNext.value = Boolean(data.next)
  } catch (e) {
    error.value = errorText(e, '报名记录暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(gameStatus, () => {
  page.value = 1
  void load()
})
watch(page, load)
</script>

<template>
  <section aria-labelledby="signups-head">
    <div class="head">
      <h2 id="signups-head" class="u-h-card">我报名的团</h2>
      <RouterLink class="c-textlink" to="/recruit">去找新的团 →</RouterLink>
    </div>

    <CNotice title="报名分两步：先占席位，再交角色卡">
      报名成功后，你会先占到一个席位。如果该团要求交角色卡，你需要在交卡截止时间之前交卡，否则席位会被自动释放。开团时间过后如果想退出，需要本团 GM 确认。交卡、更换角色卡和退出，都请在对应的团页面中操作。
    </CNotice>

    <div class="c-chips" role="group" aria-label="按团状态筛选">
      <CChip
        v-for="option in GAME_STATUS_OPTIONS"
        :key="option.value"
        :active="gameStatus === option.value"
        @click="gameStatus = option.value"
      >
        {{ option.label }}
      </CChip>
    </div>

    <LoadState
      :loading="loading"
      :error="error"
      :empty="!items.length"
      empty-title="当前筛选条件下没有报名记录"
      empty-text="你报名过的团都会列在此处，并显示交卡状态和 GM 留下的审批备注。"
    >
      <MeRow
        v-for="item in items"
        :key="item.id"
        :title="item.game.title"
        :to="'/games/' + item.game.id"
        :meta="metaOf(item)"
        :sub="subOf(item)"
      >
        <template #marks>
          <CPill :tone="TONE[item.status]">{{ item.status_display }}</CPill>
        </template>
        <template #act>
          <RouterLink
            v-if="needsAction(item)"
            class="c-btn c-btn--ghost"
            :to="'/games/' + item.game.id"
          >
            {{ item.status === 'pending' ? '去交卡' : '更换角色卡' }}
          </RouterLink>
          <RouterLink v-else class="c-textlink" :to="'/games/' + item.game.id">查看团 →</RouterLink>
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
  margin: var(--sp-4) 0;
}
</style>
