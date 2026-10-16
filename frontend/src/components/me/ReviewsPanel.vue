<script setup lang="ts">
/** 我的记录 · 评价（v2 `me.html` 的 `#sp-given` + `#sp-received` 合成一屏两栏）。 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'
import CNotice from '../CNotice.vue'
import CPill from '../CPill.vue'
import CEmpty from '../CEmpty.vue'
import LoadState from '../LoadState.vue'
import ReviewForm from '../game/ReviewForm.vue'
import { errorText } from '../../lib/api-error'
import { formatDate, timeLeft } from '../../lib/datetime'
import {
  fetchGivenReviews,
  fetchPendingReviews,
  fetchReceivedReviews,
  fetchReviewQuota,
  submitReview,
  type AnonymousReview,
  type GivenReview,
  type PendingGame,
  type ReviewQuota,
  type Verdict,
} from '../../api/reviews'
import { useSiteStore } from '../../stores/site'

const DAY_MS = 86_400_000

const site = useSiteStore()
const { config } = storeToRefs(site)

const loading = ref(true)
const error = ref('')
const pending = ref<PendingGame[]>([])
const given = ref<GivenReview[]>([])
const received = ref<AnonymousReview[]>([])
const hiddenCount = ref(0)
const visibleAfter = ref(3)
const quota = ref<ReviewQuota | null>(null)
const busyKey = ref('')
const actionError = ref('')
const actionOk = ref('')

const likeOn = computed(() => config.value.like_feature_enabled !== false)

async function loadAll(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [p, g, r, q] = await Promise.all([
      fetchPendingReviews(),
      fetchGivenReviews(),
      fetchReceivedReviews(),
      fetchReviewQuota(),
    ])
    pending.value = p.results
    given.value = g.results
    received.value = r.results
    hiddenCount.value = r.hidden_count
    visibleAfter.value = r.visible_after_games
    quota.value = q
  } catch (e) {
    error.value = errorText(e, '评价数据暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await site.load()
  if (!likeOn.value) {
    loading.value = false
    return
  }
  await loadAll()
})

/** 团 id → 后端下发的窗口截止时刻（只有 `pending` 里出现过的团才有）。 */
const windowFromPending = computed(() => {
  const map = new Map<number, string>()
  for (const group of pending.value) map.set(group.game.id, group.window_ends_at)
  return map
})

/** 这条评价所属团的窗口截止时刻；算不出就返回空串。 */
function windowEndsAt(item: GivenReview): string {
  const fromBackend = windowFromPending.value.get(item.game.id)
  if (fromBackend) return fromBackend
  if (!item.game.finished_at) return ''
  const days = config.value.review_window_days
  if (!days) return ''
  const ends = new Date(item.game.finished_at).getTime() + days * DAY_MS
  if (Number.isNaN(ends)) return ''
  return new Date(ends).toISOString()
}

function isClosed(item: GivenReview): boolean {
  const ends = windowEndsAt(item)
  if (!ends) return true
  return new Date(ends).getTime() <= Date.now()
}

/** 「我收到的」按团分组：可见的那些自带 `game`，所以能分组；被锁的后端只给了一个总数。 */
const receivedByGame = computed(() => {
  const groups = new Map<number, { title: string; id: number; items: AnonymousReview[] }>()
  for (const item of received.value) {
    const group = groups.get(item.game.id) ?? {
      id: item.game.id,
      title: item.game.title,
      items: [],
    }
    group.items.push(item)
    groups.set(item.game.id, group)
  }
  return [...groups.values()]
})

async function onSubmit(
  gameId: number,
  revieweeId: number,
  key: string,
  payload: { verdict: Verdict; text: string },
): Promise<void> {
  if (busyKey.value) return
  busyKey.value = key
  actionError.value = ''
  actionOk.value = ''
  try {
    await submitReview({ game: gameId, reviewee: revieweeId, ...payload })
    actionOk.value = '评价已保存。评价窗口关闭之前你还可以回来修改，但已提交的评价无法撤回。'
    await loadAll()
  } catch (e) {
    actionError.value = errorText(e, '提交失败，请稍后再试。')
  } finally {
    busyKey.value = ''
  }
}
</script>

<template>
  <section aria-labelledby="reviews-head">
    <div class="head">
      <h2 id="reviews-head" class="u-h-card">团后评价</h2>
      <RouterLink class="c-textlink" to="/guide">查看评价规则 →</RouterLink>
    </div>

    <CNotice v-if="!likeOn" title="站主关闭了赞功能">
      评价功能目前无法使用。已有的评价只是暂时隐藏，不会被删除。
    </CNotice>

    <LoadState v-else :loading="loading" :error="error">
      <p v-if="quota" class="quota">
        <CPill tone="off">配额 {{ quota.quota }}</CPill>
        <CPill tone="off">已用 {{ quota.used }}</CPill>
        <CPill tone="ok">还剩 {{ quota.remaining }}</CPill>
        <span class="u-small">你可以提交的评价总数，等于你参加过的各个团中其他到场成员人数的总和（不包括你自己）。在同一个团里，你对每个人只能评价一次。</span>
      </p>

      <CNotice v-if="actionError" tone="danger">{{ actionError }}</CNotice>
      <CNotice v-else-if="actionOk" tone="ok">{{ actionOk }}</CNotice>

      <!-- —— 还没评的（窗口内） —— -->
      <div v-if="pending.length" class="block">
        <h3 class="u-h-card block__title">尚未评价的成员</h3>
        <p class="u-small block__note">
          每个团结团后的 {{ config.review_window_days }} 天内为评价窗口，你可以在此期间评价同团成员。评价只有三种结果：「赞」「倒赞」和「无评价」。<strong>如果你在评价窗口关闭前没有提交，就会记为「无评价」</strong>。「无评价」既不算赞，也不算倒赞，但会计入对方的被评价次数。赞级别按赞和倒赞各自占被评价次数的比例算出，因此「无评价」会同时拉低赞所占的比例和倒赞所占的比例，使对方的赞级别更接近中间的「中性」。
        </p>
        <div v-for="group in pending" :key="group.game.id" class="game">
          <div class="game__head">
            <RouterLink class="game__title" :to="'/games/' + group.game.id">
              {{ group.game.title }}
            </RouterLink>
            <span class="u-small">
              评价窗口在 {{ formatDate(group.window_ends_at) }} 关闭（{{ timeLeft(group.window_ends_at) }}）
            </span>
          </div>
          <ReviewForm
            v-for="target in group.targets"
            :key="target.user.id"
            :user="target.user"
            :role-display="target.role_display"
            :busy="busyKey === group.game.id + ':' + target.user.id"
            @submit="
              onSubmit(group.game.id, target.user.id, group.game.id + ':' + target.user.id, $event)
            "
          />
        </div>
      </div>

      <!-- —— 两栏：给出 / 收到 —— -->
      <div class="two">
        <!-- 左：我给出的 -->
        <div class="col">
          <div class="col__head">
            <h3 class="u-h-card">我给出的</h3>
            <span class="u-kicker">我写给别人的</span>
          </div>
          <p class="u-small col__note">
            对方只能看到评价结果和文字内容，看不到是谁写的。本栏保留你写过的每一条评价，方便你自己核对。评价窗口关闭之前可以修改；评价窗口关闭后，评价内容将固定，无法再修改。
          </p>

          <CEmpty v-if="!given.length" compact title="你暂时没有写过评价" text="团结束后的评价窗口内，需要你评价的同团成员会显示在本页上方。" />
          <div v-for="item in given" :key="item.id" class="given">
            <p class="given__where">
              <RouterLink class="c-textlink" :to="'/games/' + item.game.id">
                {{ item.game.title }}
              </RouterLink>
              <span v-if="!isClosed(item)" class="u-small">
                · 可修改至 {{ formatDate(windowEndsAt(item)) }}
              </span>
              <span v-else class="u-small">· 评价窗口已关闭，无法再修改</span>
            </p>
            <ReviewForm
              :user="item.reviewee"
              :role-display="item.reviewee_role === 'gm' ? 'GM' : 'PL'"
              :existing="item"
              :readonly="isClosed(item)"
              :busy="busyKey === item.game.id + ':' + item.reviewee.id"
              @submit="
                onSubmit(item.game.id, item.reviewee.id, item.game.id + ':' + item.reviewee.id, $event)
              "
            />
          </div>
        </div>

        <!-- 右：我收到的 -->
        <div class="col">
          <div class="col__head">
            <h3 class="u-h-card">我收到的</h3>
            <span class="u-kicker">别人写给我的 · 匿名</span>
          </div>
          <p class="u-small col__note">
            别人给你的评价不会在结团后立即显示：在该团结团之后，你还需要再参加 {{ visibleAfter }} 个有其他成员到场的团并完成结团，才能看到这条评价。这样做是为了防止根据评价出现的时间推测出评价人是谁。
          </p>

          <p v-if="hiddenCount > 0" class="locked">
            <span class="locked__tag u-kicker">锁定中</span>
            还有 {{ hiddenCount }} 条评价尚未解锁。每条评价都需要再经过 {{ visibleAfter }} 个团结团后才会解锁；解锁之前，你看不到评价内容，也看不到它来自哪个团。
          </p>

          <CEmpty
            v-if="!received.length"
            compact
            title="目前没有可显示的评价"
            text="你需要实际到场参加团，并且等到别人给你的评价解锁之后，评价才会显示在此处。"
          />
          <div v-for="group in receivedByGame" :key="group.id" class="rgroup">
            <div class="rgroup__head">
              <RouterLink class="c-textlink" :to="'/games/' + group.id">{{ group.title }}</RouterLink>
              <span class="u-small">共 {{ group.items.length }} 条</span>
            </div>
            <div v-for="(item, i) in group.items" :key="'r' + i" class="ritem">
              <CPill :tone="item.verdict === 'like' ? 'ok' : 'warn'">{{ item.verdict_display }}</CPill>
              <CPill tone="off">{{ item.reviewee_role === 'gm' ? '作为 GM' : '作为 PL' }}</CPill>
              <p class="ritem__text">{{ item.text }}</p>
            </div>
            <p class="u-small rgroup__note">
              此处不显示评价人是谁，评价的排列顺序也与提交时间无关。
            </p>
          </div>
        </div>
      </div>
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
  margin-bottom: var(--sp-4);
}

.head h2 {
  margin: 0;
}

.quota {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-3);
  margin: 0 0 var(--sp-4);
}

.block {
  margin-bottom: var(--sp-7);
}

.block__title {
  margin: 0 0 var(--sp-2);
}

.block__note {
  margin: 0 0 var(--sp-4);
  line-height: var(--lh-body);
  color: var(--ink-muted);
}

.game {
  margin-bottom: var(--sp-5);
}

.game__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-2);
  padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--line-2);
}

.game__title {
  display: inline-flex;
  align-items: center;
  min-height: 40px;
  font-size: var(--fs-lg);
  color: var(--ink);
  text-decoration: none;
}

.game__title:hover {
  text-decoration: underline;
  text-underline-offset: 4px;
}

.two {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-7);
}

.col__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--sp-3);
  padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--line-2);
}

.col__head h3 {
  margin: 0;
}

.col__note {
  margin: var(--sp-3) 0 var(--sp-4);
  line-height: var(--lh-body);
  color: var(--ink-muted);
}

.given {
  margin-bottom: var(--sp-4);
}

.given__where {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--sp-2);
  margin: 0;
  font-size: var(--fs-sm);
}

.locked {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--sp-2);
  margin: 0 0 var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
  color: var(--ink-muted);
  background: var(--bg-2);
  border-left: 2px solid var(--line-2);
  border-radius: 0 var(--radius) var(--radius) 0;
}

.locked__tag {
  color: var(--ink-soft);
}

.rgroup {
  padding: var(--sp-4);
  margin-bottom: var(--sp-3);
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.rgroup__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-2);
  margin-bottom: var(--sp-2);
}

.ritem {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-3) 0;
  border-top: 1px solid var(--line);
}

.ritem__text {
  flex: 1 1 100%;
  margin: 0;
  font-size: var(--fs-md);
  line-height: var(--lh-read);
  color: var(--ink-soft);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.rgroup__note {
  margin: var(--sp-3) 0 0;
  color: var(--ink-faint);
}

@media (min-width: 1200px) {
  .two {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--sp-8);
  }
}
</style>
