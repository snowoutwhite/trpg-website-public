<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import CTabs, { type TabItem } from '../components/CTabs.vue'
import CNotice from '../components/CNotice.vue'
import LoadState from '../components/LoadState.vue'
import GameHero from '../components/game/GameHero.vue'
import GameActionCard from '../components/game/GameActionCard.vue'
import GameAbout from '../components/game/GameAbout.vue'
import GameRoster from '../components/game/GameRoster.vue'
import GamePhotoTab from '../components/game/GamePhotoTab.vue'
import GameReportTab from '../components/game/GameReportTab.vue'
import GameMutualTab from '../components/game/GameMutualTab.vue'
import GameReviewTab from '../components/game/GameReviewTab.vue'
import GameManageTab from '../components/game/GameManageTab.vue'
import { errorText } from '../lib/api-error'
import {
  fetchGame,
  fetchRecruitingRoster,
  fetchRoster,
  signupGame,
  submitCard,
  withdrawSignup,
  type GameDetail,
  type GMSignup,
  type RecruitingSignup,
  type RosterSignup,
} from '../api/games'
import { fetchMyCards, type MyCard } from '../api/cards'
import { useAuthStore } from '../stores/auth'
import { useSiteStore } from '../stores/site'
import { useHomeStore } from '../stores/home'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const site = useSiteStore()
const home = useHomeStore()
const { user, authenticated } = storeToRefs(auth)
const { config } = storeToRefs(site)

const gameId = computed(() => String(route.params.id ?? ''))
const game = ref<GameDetail | null>(null)
const loading = ref(true)
const error = ref('')

/** 招募中名单（登录可见）与正式名单（同团可见）；拿不到就是没这一层权限。 */
const recruiting = ref<RecruitingSignup[]>([])
const recruitingOk = ref(false)
const roster = ref<RosterSignup[]>([])
const rosterOk = ref(false)
/** GM 视角的全量名单（只有本团 GM 拿得到）。 */
const gmSignups = ref<GMSignup[]>([])

const myCards = ref<MyCard[]>([])

const busy = ref(false)
const actionError = ref('')
const actionOk = ref('')

/** 标签页 */
const DEFAULT_TAB = 'about'
const tab = ref(DEFAULT_TAB)
/** 已经挂载过的面板（切回去不重新请求）。 */
const visited = ref(new Set<string>([DEFAULT_TAB]))
const photoCount = ref<number | undefined>(undefined)
const reportCount = ref<number | undefined>(undefined)
/** 吸顶标签条与面板区的 DOM，换标签后对齐滚动位置用。 */
const tabbarEl = ref<HTMLElement | null>(null)
const panelsEl = ref<HTMLElement | null>(null)

const isGm = computed(() => Boolean(game.value && user.value && game.value.gm.id === user.value.id))
const isStaff = computed(() => user.value?.is_staff === true)
const likeOn = computed(() => config.value.like_feature_enabled !== false)
const preset = computed(() => home.presetByName(game.value?.rule_system))
const loginTo = computed(() => '/auth/login?next=' + encodeURIComponent(route.fullPath))

/** 我是不是本团的到场成员（GM 永远算到场，与后端 `reviews.services.role_of` 同口径）。 */
const isAttendee = computed(
  () => isGm.value || game.value?.my_signup?.attended === true,
)
/** 评价窗口还开着（后端 `in_review_window`：结团时间 + 站级 `review_window_days`）。 */
const reviewWindowOpen = computed(() => {
  const ends = game.value?.review_window_ends_at
  if (!ends || game.value?.status !== 'finished') return false
  return Date.now() <= new Date(ends).getTime()
})

const tabs = computed<TabItem[]>(() => {
  const g = game.value
  if (!g) return []
  const list: TabItem[] = [
    { key: 'about', label: '团介绍' },
    { key: 'roster', label: '名单', count: g.occupied_seats },
    { key: 'photos', label: '相册', count: photoCount.value },
    { key: 'reports', label: '战报', count: reportCount.value },
  ]
  if (g.mutual_review && likeOn.value) list.push({ key: 'mutual', label: '互见' })
  if (likeOn.value && reviewWindowOpen.value && isAttendee.value) {
    list.push({ key: 'reviews', label: '评价' })
  }
  if (isGm.value) list.push({ key: 'manage', label: '管理' })
  return list
})

// --------------------------------------------------------------------------
// hash ⇄ 标签（不经路由，见文件头）
// --------------------------------------------------------------------------

function hashKey(): string {
  return route.hash.replace(/^#/, '')
}

/** hash 指到一个当前存在的标签就跟过去；指不到就留在原处。 */
function syncFromHash(): void {
  const key = hashKey()
  if (key && key !== tab.value && tabs.value.some((t) => t.key === key)) go(key)
}

function go(key: string): void {
  tab.value = key
  visited.value.add(key)
}

/** 这个标签当前身份能不能看见。 */
function hasTab(name: string): boolean {
  return tabs.value.some((item) => item.key === name)
}

/** 业务界面遵循后端权限与隐私约束。 */
watch(tab, (k) => {
  visited.value.add(k)
  const hash = k === DEFAULT_TAB ? '' : '#' + k
  if (route.name === 'game-detail' && route.hash !== hash) {
    void router.replace({ path: route.path, query: route.query, hash })
  }
  void nextTick(alignToPanels)
})

/** 前进后退 / 手改地址栏：hash 指到哪一格就跟过去（原来是 `hashchange` 监听）。 */
watch(
  () => route.hash,
  () => {
    if (route.name !== 'game-detail') return
    if (!hashKey()) {
      if (tabs.value.some((item) => item.key === DEFAULT_TAB)) go(DEFAULT_TAB)
      return
    }
    syncFromHash()
  },
)

/**
 * 换标签之后，如果视口已经滚过标签条（标签条正吸在顶栏下面），就把视口拉回**新面板的开头**。
 *
 * 不做这一步的话：从一个很长的面板（相册几十张图）切到一个很短的面板（名单两行），
 * 文档高度骤降，浏览器把滚动位置夹到新的最大值 —— 用户点完标签直接掉进页脚。
 * 只在「已经滚过去了」时才动，否则在首屏点标签会把首屏莫名其妙地顶走。
 */
function alignToPanels(): void {
  const panels = panelsEl.value
  const bar = tabbarEl.value
  if (!panels || !bar) return
  const headerH =
    parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--header-h')) || 54
  const target = window.scrollY + panels.getBoundingClientRect().top - headerH - bar.offsetHeight
  if (window.scrollY > target) window.scrollTo({ top: Math.max(0, target) })
}

/** 标签集合变化（名单/身份判完之后「管理」「评价」才出现）时再对一次 hash。 */
watch(tabs, syncFromHash)

// --------------------------------------------------------------------------
// 数据
// --------------------------------------------------------------------------

async function loadGame(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    game.value = await fetchGame(gameId.value)
  } catch (e) {
    error.value = errorText(e, '本团暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
}

/** 名单按登录态分别尝试；401/403 是正常的「没这一层」，不当整页错误（端到端缺陷 D2）。 */
async function loadRosters(): Promise<void> {
  recruitingOk.value = false
  rosterOk.value = false
  gmSignups.value = []
  if (authenticated.value !== true) return
  try {
    const data = await fetchRecruitingRoster(gameId.value)
    recruiting.value = data.results
    recruitingOk.value = true
  } catch {
    recruitingOk.value = false
  }
  // 正式名单只给本团 GM 与**已录取**的成员；其余身份必然 403。
  // 这个结论从公开详情里就能得出（`my_signup.status`），所以不发那一发注定失败的请求 ——
  // 少一条浏览器控制台的红字，也少一次后端限速配额。
  if (!isGm.value && game.value?.my_signup?.status !== 'accepted') return
  try {
    const data = await fetchRoster(gameId.value)
    if (data.is_gm) {
      // ⚠️ GM 视角（`gm_roster()`）回的是**全量报名** —— 含已退出 / 被拒 / 被移除 / 还没交卡的人。
      // 「名单」标签里的「正式名单（成功报团）」只能是 `accepted` 那一档，两者不是一回事：
      // `gmSignups` 保留全量 —— 管理面板要处理的正是那些非 accepted 的条目。
      const all = data.results as GMSignup[]
      gmSignups.value = all
      roster.value = all.filter((item) => item.status === 'accepted')
    } else {
      roster.value = data.results as RosterSignup[]
    }
    rosterOk.value = true
  } catch {
    rosterOk.value = false
  }
}

async function loadMyCards(): Promise<void> {
  if (authenticated.value !== true) return
  try {
    myCards.value = (await fetchMyCards({ status: 'alive' })).results
  } catch {
    myCards.value = []
  }
}

async function reload(): Promise<void> {
  await loadGame()
  await loadRosters()
}

onMounted(async () => {
  // 进页先认一次 hash：`/games/1#photos` 与旧路径重定向过来的都靠它落位
  const key = hashKey()
  if (key) {
    tab.value = key
    visited.value.add(key)
  }
  await Promise.all([site.load(), auth.refresh()])
  await home.load(authenticated.value)
  await reload()
  await loadMyCards()
  // 标签集合这时才算齐（管理/评价依赖身份），再对一次 hash
  syncFromHash()
  if (!tabs.value.some((t) => t.key === tab.value)) go(DEFAULT_TAB)
})

// --------------------------------------------------------------------------
// PL 侧动作（报名 / 交卡 / 退出）
// --------------------------------------------------------------------------

async function run(fn: () => Promise<unknown>, okText: string, fallback: string): Promise<void> {
  if (busy.value) return
  busy.value = true
  actionError.value = ''
  actionOk.value = ''
  try {
    await fn()
    actionOk.value = okText
    await reload()
  } catch (e) {
    actionError.value = errorText(e, fallback)
  } finally {
    busy.value = false
  }
}

function onSignup(): void {
  void run(() => signupGame(gameId.value), '报名已提交。', '报名失败')
}

function onSubmitCard(cardId: number): void {
  void run(() => submitCard(gameId.value, cardId), '角色卡已交。', '交卡失败')
}

async function onWithdraw(reason: string): Promise<void> {
  if (busy.value) return
  busy.value = true
  actionError.value = ''
  actionOk.value = ''
  try {
    const result = await withdrawSignup(gameId.value, reason)
    actionOk.value = result.pending_gm_confirm
      ? '交卡已截止，退出申请已提交，等 GM 确认。'
      : '已退出本团。'
    await reload()
  } catch (e) {
    actionError.value = errorText(e, '退出失败，请稍后再试。')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="gd">
    <div v-if="!game" class="gd__pad">
      <LoadState :loading="loading" :error="error" />
    </div>

    <template v-else>
      <GameHero :game="game" :preset="preset">
        <template #action>
          <GameActionCard
            :game="game"
            :authenticated="authenticated"
            :is-gm="isGm"
            :my-cards="myCards"
            :busy="busy"
            :notice-error="actionError"
            :notice-ok="actionOk"
            :login-to="loginTo"
            @signup="onSignup"
            @submit-card="onSubmitCard"
            @withdraw="onWithdraw"
            @go-tab="go"
          />
        </template>
      </GameHero>

      <div ref="tabbarEl" class="gd__tabbar">
        <CTabs v-model="tab" :items="tabs" aria-label="团内容" />
      </div>

      <div ref="panelsEl" class="gd__panels">
        <CNotice v-if="game.status === 'cancelled'" tone="danger" title="本团已被 GM 取消">
          {{ game.cancel_reason || 'GM 取消本团时没有填写理由。' }}
        </CNotice>

        <section
          v-if="visited.has('about') && hasTab('about')"
          v-show="tab === 'about'"
          id="panel-about"
          role="tabpanel"
          aria-labelledby="tab-about"
          tabindex="-1"
        >
          <GameAbout :game="game" :like-on="likeOn" />
        </section>

        <section
          v-if="visited.has('roster') && hasTab('roster')"
          v-show="tab === 'roster'"
          id="panel-roster"
          role="tabpanel"
          aria-labelledby="tab-roster"
          tabindex="-1"
        >
          <GameRoster
            :game="game"
            :authenticated="authenticated"
            :recruiting="recruiting"
            :recruiting-ok="recruitingOk"
            :roster="roster"
            :roster-ok="rosterOk"
            :login-to="loginTo"
          />
        </section>

        <section
          v-if="visited.has('photos') && hasTab('photos')"
          v-show="tab === 'photos'"
          id="panel-photos"
          role="tabpanel"
          aria-labelledby="tab-photos"
          tabindex="-1"
        >
          <GamePhotoTab
            :game="game"
            :authenticated="authenticated"
            :is-gm="isGm"
            :is-staff="isStaff"
            :config="config"
            :login-to="loginTo"
            @count="photoCount = $event"
          />
        </section>

        <section
          v-if="visited.has('reports') && hasTab('reports')"
          v-show="tab === 'reports'"
          id="panel-reports"
          role="tabpanel"
          aria-labelledby="tab-reports"
          tabindex="-1"
        >
          <GameReportTab
            :game="game"
            :user="user"
            :is-gm="isGm"
            :preset="preset"
            @count="reportCount = $event"
          />
        </section>

        <section
          v-if="visited.has('mutual') && hasTab('mutual')"
          v-show="tab === 'mutual'"
          id="panel-mutual"
          role="tabpanel"
          aria-labelledby="tab-mutual"
          tabindex="-1"
        >
          <GameMutualTab :game="game" :authenticated="authenticated" :login-to="loginTo" />
        </section>

        <section
          v-if="visited.has('reviews') && hasTab('reviews')"
          v-show="tab === 'reviews'"
          id="panel-reviews"
          role="tabpanel"
          aria-labelledby="tab-reviews"
          tabindex="-1"
        >
          <GameReviewTab :game="game" />
        </section>

        <section
          v-if="visited.has('manage') && hasTab('manage')"
          v-show="tab === 'manage'"
          id="panel-manage"
          role="tabpanel"
          aria-labelledby="tab-manage"
          tabindex="-1"
        >
          <GameManageTab :game="game" :signups="gmSignups" @reload="reload" />
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* 本页挂 `route.meta.flush`：主体没有左右/顶部留白，各段自己给（`base.css` 的 .l-main--flush） */
.gd__pad {
  padding: var(--sp-6) var(--pad);
}

/* 吸顶标签条（v2 `.tabbar`：贴在玻璃顶栏下面） */
.gd__tabbar {
  position: sticky;
  top: var(--header-h);
  z-index: 20;
  padding: 0 var(--pad);
  background: var(--bg);
  border-bottom: 1px solid var(--line);
}

.gd__panels {
  padding: var(--sp-6) var(--pad) var(--sp-8);
}

.gd__panels [role="tabpanel"]:focus {
  /* 带 hash 进来时浏览器会给 tabindex=-1 的容器画一圈轮廓 */
  outline: none;
}

.gd__panels :deep(.c-note) {
  margin-bottom: var(--sp-4);
}

@media (min-width: 768px) {
  .gd__panels {
    padding-top: var(--sp-7);
  }
}
</style>
