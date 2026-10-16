<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import BlurStage from '../components/BlurStage.vue'
import CButton from '../components/CButton.vue'
import CNotice from '../components/CNotice.vue'
import CTabs, { type TabItem } from '../components/CTabs.vue'
import AbusePanel from '../components/me/AbusePanel.vue'
import GmCardPanel from '../components/me/GmCardPanel.vue'
import HostingPanel from '../components/me/HostingPanel.vue'
import IdentityPanel from '../components/me/IdentityPanel.vue'
import MailPrefPanel from '../components/me/MailPrefPanel.vue'
import NotifPanel from '../components/me/NotifPanel.vue'
import PlayerCardPanel from '../components/me/PlayerCardPanel.vue'
import ReviewsPanel from '../components/me/ReviewsPanel.vue'
import SecurityPanel from '../components/me/SecurityPanel.vue'
import SignupsPanel from '../components/me/SignupsPanel.vue'
import TodoCards from '../components/me/TodoCards.vue'
import { loadTodoCards, type TodoCard } from '../lib/todos'
import { useAuthStore } from '../stores/auth'
import { useHomeStore } from '../stores/home'
import { useSiteStore } from '../stores/site'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const site = useSiteStore()
const home = useHomeStore()
const { user, isGm, authenticated } = storeToRefs(auth)
const { config } = storeToRefs(site)

const GROUPS: TabItem[] = [
  { key: 'games', label: '我的团' },
  { key: 'cards', label: '我的卡' },
  { key: 'records', label: '我的记录' },
  { key: 'account', label: '账户与通知' },
]

/** 每组的默认子标签（hash 里省略不写）；账户组没有子标签。 */
const DEFAULT_SUB: Record<string, string> = {
  games: 'signups',
  cards: 'player',
  records: 'reports',
  account: '',
}

const likeOn = computed(() => config.value.like_feature_enabled !== false)

/** 待办（与首页「我的当下」同一份数据，见 `lib/todos.ts`）。 */
const todos = ref<TodoCard[]>([])
let todosLoading = false

const group = ref('games')
const sub = ref(DEFAULT_SUB.games)
const visited = ref(new Set<string>())
const unread = ref(0)
const loggingOut = ref(false)

const tabbarEl = ref<HTMLElement | null>(null)
const panelsEl = ref<HTMLElement | null>(null)

/** 某一组的子标签集合。GM 专属的两格随身份出现，评价那格随站级赞开关出现。 */
function subsFor(name: string): TabItem[] {
  if (name === 'games') {
    return [
      { key: 'signups', label: '我报名的' },
      ...(isGm.value ? [{ key: 'hosted', label: '我主持的' }] : []),
      { key: 'todo', label: '待办', count: todos.value.length || undefined },
    ]
  }
  if (name === 'cards') {
    return [
      { key: 'player', label: '玩家卡' },
      ...(isGm.value ? [{ key: 'gm', label: 'GM 卡' }] : []),
      { key: 'roles', label: '角色卡' },
    ]
  }
  if (name === 'records') {
    return [
      { key: 'reports', label: '战报' },
      ...(likeOn.value ? [{ key: 'reviews', label: '评价' }] : []),
      { key: 'abuse', label: '举报' },
    ]
  }
  return []
}

const subs = computed(() => subsFor(group.value))

/** 「组-子」的组合键；账户组没有子标签，就只有组名。 */
const at = computed(() => (sub.value ? group.value + '-' + sub.value : group.value))

function splitKey(key: string): [string, string] {
  const dash = key.indexOf('-')
  if (dash < 0) return [key, '']
  return [key.slice(0, dash), key.slice(dash + 1)]
}

/** 这一格当前身份下存在吗（面板 `v-if` 必须同时判它与 `visited`）。 */
function has(key: string): boolean {
  const [g, s] = splitKey(key)
  if (!GROUPS.some((item) => item.key === g)) return false
  const list = subsFor(g)
  if (!s) return list.length === 0
  return list.some((item) => item.key === s)
}

async function loadTodos(): Promise<void> {
  if (todosLoading || todos.value.length || authenticated.value !== true) return
  todosLoading = true
  try {
    todos.value = await loadTodoCards({
      isGm: isGm.value,
      userId: user.value?.id ?? null,
      galleryUploadWindowDays: config.value.gallery_upload_window_days,
    })
    const notif = todos.value.find((card) => card.key === 'notifications')
    unread.value = notif ? notif.days : 0
  } finally {
    todosLoading = false
  }
}

// --------------------------------------------------------------------------
// hash ↔ 标签
// --------------------------------------------------------------------------

function hashKey(): string {
  return route.hash.replace(/^#/, '')
}

/**
 * 认一次 hash。接受三种写法：
 *   `#games`（组 + 该组默认子标签）/ `#games-hosted`（组 + 指定子标签）/
 *   `#notifications`（v2 稿的旧写法，落到账户组）
 * 指不到的 hash 一律忽略，留在原处。
 */
function syncFromHash(): void {
  const raw = hashKey()
  if (!raw) return
  if (raw === 'notifications' || raw === 'account-notifications') {
    go('account', '')
    return
  }
  const [g, s] = splitKey(raw)
  if (!GROUPS.some((item) => item.key === g)) return
  const wanted = s || DEFAULT_SUB[g]
  if (wanted && !subsFor(g).some((item) => item.key === wanted)) {
    // 目标子标签这个身份下没有（例如非 GM 开 `#cards-gm`）：退回该组默认格
    go(g, DEFAULT_SUB[g])
    return
  }
  go(g, wanted)
}

function go(nextGroup: string, nextSub: string): void {
  group.value = nextGroup
  sub.value = nextSub
  visited.value.add(nextSub ? nextGroup + '-' + nextSub : nextGroup)
}

/**
 * 点身份条上的头像 = 去换头像（v2 上手检查 2026-09-23）：切到「账户与通知」组，
 * 等面板挂上后把头像那一行滚进视野并把焦点交给「换一张」，不用再在页面里找。
 */
/** 为真时 `alignToPanels()` 让路：头像跳转的滚动目标比标签栏更靠下，两者不能抢。 */
let seekingAvatar = false

function goAvatar(): void {
  go('account', '')
  seekingAvatar = true
  // 账户面板首次进入时才挂载，里面的头像行要等资料读回来才在 DOM 里，所以轮询几帧再滚
  let tries = 0
  const seek = (): void => {
    const target = document.getElementById('avatar-row')
    if (!target) {
      if (tries++ < 30) window.setTimeout(seek, 50)
      else seekingAvatar = false
      return
    }
    // 直接跳而不用平滑滚动：账户组其余面板还在陆续读数据、页面高度一直在变，
    // 平滑滚动会在中途被布局变化打断停在半路（真浏览器实测停在 1425px，目标在 3700px）
    target.scrollIntoView({ behavior: 'auto', block: 'center' })
    target.querySelector<HTMLElement>('label, button')?.focus({ preventScroll: true })
    // 面板读完数据后再校正一次位置，然后把对齐让回去
    window.setTimeout(() => {
      target.scrollIntoView({ behavior: 'auto', block: 'center' })
      seekingAvatar = false
    }, 700)
  }
  void nextTick(seek)
}

/** 换组时把子标签落到该组的默认格（或第一个还存在的格）。 */
function reseat(): void {
  const list = subs.value
  if (!list.length) {
    sub.value = ''
    return
  }
  if (list.some((item) => item.key === sub.value)) return
  sub.value = list.some((item) => item.key === DEFAULT_SUB[group.value])
    ? DEFAULT_SUB[group.value]
    : list[0].key
}

watch(group, reseat)
/** 身份判完之后（GM 的两格才出现）子标签集合会变，别停在一个已经消失的格上。 */
watch(subs, reseat)

/** 业务界面遵循后端权限与隐私约束。 */
watch(at, (k) => {
  visited.value.add(k)
  if (k === 'games-todo') void loadTodos()
  const hash = k === 'games-' + DEFAULT_SUB.games ? '' : '#' + k
  if (route.name === 'me' && route.hash !== hash) {
    void router.replace({ path: route.path, query: route.query, hash })
  }
  void nextTick(alignToPanels)
})

/** 前进后退 / 手改地址栏：hash 指到哪一格就跟过去（原来是 `hashchange` 监听）。 */
watch(
  () => route.hash,
  () => {
    if (route.name !== 'me') return
    if (!hashKey()) {
      go('games', DEFAULT_SUB.games)
      return
    }
    syncFromHash()
  },
)

/** 换标签之后，如果视口已经滚过标签条（标签条正吸在顶栏下面），就把视口拉回**新面板的开头**。 */
function alignToPanels(): void {
  if (seekingAvatar) return
  const panels = panelsEl.value
  const bar = tabbarEl.value
  if (!panels || !bar) return
  const headerH =
    parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--header-h')) || 54
  const target = window.scrollY + panels.getBoundingClientRect().top - headerH - bar.offsetHeight
  if (window.scrollY > target) window.scrollTo({ top: Math.max(0, target) })
}

// --------------------------------------------------------------------------
// 进页
// --------------------------------------------------------------------------

onMounted(async () => {
  syncFromHash()
  visited.value.add(at.value)
  await Promise.all([site.load(), auth.refresh()])
  await home.load(authenticated.value === true)
  // 身份齐了再对一次 hash（`#cards-gm` 之类要等 isGm 才知道存不存在）
  syncFromHash()
  reseat()
  await loadTodos()
})


/**
 * 身份条的铺底图：站主配的第一个规则预设（`GET /home/` 的 `rule_presets`）。
 * v2 `me.html` 写死成 `art-coc`，这里改成跟着站主的配置走；一条都没配时
 * `BlurStage` 自己回落到 `lib/rule-art.ts` 的默认图。
 */
const bandPreset = computed(() => home.rulePresets[0] ?? null)

/** 没头像时用昵称首字占位。 */
const initial = computed(() => (user.value?.nickname ?? '').slice(0, 1) || '·')

const joinedAt = computed(() => {
  const iso = user.value?.date_joined
  if (!iso) return ''
  const time = new Date(iso)
  if (Number.isNaN(time.getTime())) return ''
  return time.getFullYear() + ' 年 ' + (time.getMonth() + 1) + ' 月'
})

async function onLogout(): Promise<void> {
  if (loggingOut.value) return
  loggingOut.value = true
  try {
    await auth.logout()
    await router.replace({ name: 'home' })
  } finally {
    loggingOut.value = false
  }
}
</script>

<template>
  <div class="me">
    <!-- ============ 身份条 ============ -->
    <BlurStage
      class="idband"
      tone="dark"
      :foreground="false"
      as="section"
      :image="bandPreset?.image ?? null"
    >
      <div class="idband__row">
        <button
          class="idband__face-btn"
          type="button"
          title="更换头像"
          aria-label="更换头像"
          @click="goAvatar"
        >
          <img v-if="user?.avatar" class="idband__face" :src="user.avatar" alt="" />
          <span v-else class="idband__face idband__face--blank" aria-hidden="true">{{ initial }}</span>
          <span class="idband__face-hint" aria-hidden="true">更换</span>
        </button>

        <div class="idband__who">
          <p class="u-kicker idband__kicker">Your own page · 我的</p>
          <h1 class="idband__name">{{ user?.nickname || '未命名' }}</h1>
          <p class="idband__marks">
            <span class="idtag idtag--solid">PL</span>
            <span v-if="isGm" class="idtag idtag--solid">GM</span>
            <span v-if="joinedAt" class="idtag">加入于 {{ joinedAt }}</span>
            <span v-if="user && !user.email_verified" class="idtag idtag--warn">邮箱待验证</span>
            <span v-if="unread" class="idtag idtag--warn">{{ unread }} 条未读</span>
          </p>
        </div>

        <div class="idband__side">
          <RouterLink v-if="user" class="c-textlink idband__link" :to="'/users/' + user.id">
            查看我的公开页 →
          </RouterLink>
          <span class="u-small idband__note">其他成员看到的是你的公开页。公开页不显示你的邮箱，也不显示任何一条评价是谁写的。</span>
          <CButton variant="light" :disabled="loggingOut" @click="onLogout">
            {{ loggingOut ? '登出中…' : '登出' }}
          </CButton>
        </div>
      </div>
    </BlurStage>

    <div v-if="!user" class="warn">
      <CNotice tone="warn" title="账号资料暂时无法读取">
        你仍处于登录状态，但这次没有成功读取你的账号资料。请刷新页面后重试。
      </CNotice>
    </div>

    <!-- ============ 一级：四组（吸在顶栏下） ============ -->
    <div ref="tabbarEl" class="tabbar">
      <CTabs v-model="group" :items="GROUPS" aria-label="我的" />
    </div>

    <!-- ============ 二级 + 面板 ============ -->
    <div ref="panelsEl" class="panels">
      <div v-if="subs.length" class="subtabs">
        <CTabs v-model="sub" :items="subs" aria-label="分区" />
      </div>

      <!-- ---------- 我的团 ---------- -->
      <div
        v-show="group === 'games'"
        id="panel-games"
        role="tabpanel"
        tabindex="-1"
        aria-labelledby="tab-games"
      >
        <div
          v-if="visited.has('games-signups') && has('games-signups')"
          v-show="at === 'games-signups'"
          id="panel-signups"
          role="tabpanel"
          tabindex="-1"
          aria-labelledby="tab-signups"
        >
          <SignupsPanel />
        </div>

        <div
          v-if="visited.has('games-hosted') && has('games-hosted')"
          v-show="at === 'games-hosted'"
          id="panel-hosted"
          role="tabpanel"
          tabindex="-1"
          aria-labelledby="tab-hosted"
        >
          <HostingPanel :user-id="user?.id ?? null" />
        </div>

        <div
          v-if="visited.has('games-todo') && has('games-todo')"
          v-show="at === 'games-todo'"
          id="panel-todo"
          role="tabpanel"
          tabindex="-1"
          aria-labelledby="tab-todo"
        >
          <div class="head">
            <h2 class="u-h-card">待办</h2>
            <RouterLink class="c-textlink" to="/">在首页「我的当下」中查看 →</RouterLink>
          </div>
          <TodoCards :cards="todos" />
        </div>
      </div>

      <!-- ---------- 我的卡 ---------- -->
      <div
        v-show="group === 'cards'"
        id="panel-cards"
        role="tabpanel"
        tabindex="-1"
        aria-labelledby="tab-cards"
      >
        <div
          v-if="visited.has('cards-player') && has('cards-player')"
          v-show="at === 'cards-player'"
          id="panel-player"
          role="tabpanel"
          tabindex="-1"
          aria-labelledby="tab-player"
        >
          <PlayerCardPanel />
        </div>

        <div
          v-if="visited.has('cards-gm') && has('cards-gm')"
          v-show="at === 'cards-gm'"
          id="panel-gm"
          role="tabpanel"
          tabindex="-1"
          aria-labelledby="tab-gm"
        >
          <GmCardPanel />
        </div>

        <div
          v-if="visited.has('cards-roles') && has('cards-roles')"
          v-show="at === 'cards-roles'"
          id="panel-roles"
          role="tabpanel"
          tabindex="-1"
          aria-labelledby="tab-roles"
        >
          <div class="head">
            <h2 class="u-h-card">我的角色卡</h2>
            <RouterLink class="c-textlink" to="/me/cards">打开角色卡列表 →</RouterLink>
          </div>
          <CNotice title="角色卡有自己的页面">
            新建角色卡、更换卡的文件、设置公开或撕卡，以及查看参团记录，都在「我的角色卡」页面中进行。每张卡只保留最近 3 个文件版本；更换文件不会改变这张卡本身，这张卡的参团记录也会继续保留。
            <template #actions>
              <RouterLink class="c-btn" to="/me/cards">去我的角色卡</RouterLink>
              <RouterLink class="c-textlink" to="/cards">浏览公开的角色卡池 →</RouterLink>
            </template>
          </CNotice>
        </div>
      </div>

      <!-- ---------- 我的记录 ---------- -->
      <div
        v-show="group === 'records'"
        id="panel-records"
        role="tabpanel"
        tabindex="-1"
        aria-labelledby="tab-records"
      >
        <div
          v-if="visited.has('records-reports') && has('records-reports')"
          v-show="at === 'records-reports'"
          id="panel-reports"
          role="tabpanel"
          tabindex="-1"
          aria-labelledby="tab-reports"
        >
          <div class="head">
            <h2 class="u-h-card">我的战报</h2>
            <RouterLink class="c-textlink" to="/me/reports">打开战报列表 →</RouterLink>
          </div>
          <CNotice title="战报有自己的页面">
            每个人在每个团中可以写一份战报，写完后可以随时修改。你可以把每份战报设为公开、仅登录成员可见或仅自己可见。
            <template #actions>
              <RouterLink class="c-btn" to="/me/reports">去我的战报</RouterLink>
              <RouterLink class="c-textlink" to="/reports">查看其他成员写的战报 →</RouterLink>
            </template>
          </CNotice>
        </div>

        <div
          v-if="visited.has('records-reviews') && has('records-reviews')"
          v-show="at === 'records-reviews'"
          id="panel-reviews"
          role="tabpanel"
          tabindex="-1"
          aria-labelledby="tab-reviews"
        >
          <ReviewsPanel />
        </div>

        <div
          v-if="visited.has('records-abuse') && has('records-abuse')"
          v-show="at === 'records-abuse'"
          id="panel-abuse"
          role="tabpanel"
          tabindex="-1"
          aria-labelledby="tab-abuse"
        >
          <AbusePanel />
        </div>
      </div>

      <!-- ---------- 账户与通知（不分子标签，四块顺排） ---------- -->
      <div
        v-show="group === 'account'"
        id="panel-account"
        role="tabpanel"
        tabindex="-1"
        aria-labelledby="tab-account"
      >
        <div v-if="visited.has('account')" class="stack">
          <NotifPanel @read="unread = $event" />
          <MailPrefPanel />
          <SecurityPanel />
          <IdentityPanel />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.me {
  padding-bottom: var(--sp-8);
}

/** 业务界面遵循后端权限与隐私约束。 */
.idband {
  padding: var(--sec-y-tight) var(--pad);
  color: var(--on-dark);
}

/** 纯白底图时 1.3–2.9:1。换成 83% 满铺（--scrim-3），与 `/users/:id` 的 `.head` 同款。 */
.idband::after {
  background: var(--scrim-3);
}

.idband__kicker {
  color: var(--on-dark-kicker);
}

.idband__link {
  color: var(--on-dark);
}

.idtag {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 11px;
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps);
  color: var(--on-dark);
  background: var(--glass-dark-2);
  border: 1px solid var(--glass-line);
  border-radius: var(--radius-pill);
}

.idtag--solid {
  color: var(--brand-ink);
  background: var(--white);
  border-color: var(--white);
}

.idtag--warn {
  border-color: var(--warn-line);
}

.idband__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-5);
}

/* 头像本身就是「换头像」的入口：按钮外壳不带任何自己的外观，悬停时露出一角小字 */
.idband__face-btn {
  position: relative;
  flex: none;
  padding: 0;
  margin: 0;
  border: 0;
  border-radius: var(--radius-pill);
  background: none;
  cursor: pointer;
  color: inherit;
  font: inherit;
  overflow: hidden;
}

.idband__face-btn:focus-visible {
  outline: 2px solid var(--on-dark);
  outline-offset: 3px;
}

.idband__face {
  display: block;
}

.idband__face-hint {
  position: absolute;
  inset: auto 0 0;
  padding: 2px 0 4px;
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps-sm);
  text-align: center;
  color: var(--on-dark);
  background: var(--scrim-3);
  opacity: 0;
  transition: opacity 0.15s;
}

.idband__face-btn:hover .idband__face-hint,
.idband__face-btn:focus-visible .idband__face-hint {
  opacity: 1;
}

.idband__face {
  flex: none;
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: var(--radius-pill);
  background: var(--avatar-bg);
}

.idband__face--blank {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--fs-h-section);
  color: var(--ink-soft); /** 业务界面遵循后端权限与隐私约束。 */
}

.idband__who {
  min-width: 0;
  flex: 1 1 260px;
}

.idband__name {
  margin: var(--sp-2) 0 var(--sp-3);
  font-size: var(--fs-h-display);
  font-weight: 400;
  line-height: var(--lh-tight);
  letter-spacing: var(--ls-display);
  overflow-wrap: anywhere;
}

.idband__marks {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin: 0;
}

.idband__side {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-2);
}

.idband__note {
  max-width: 34ch;
  line-height: var(--lh-body);
  color: var(--on-dark-2);
}

.warn {
  padding: var(--sp-4) var(--pad) 0;
}

/* ---------- 吸顶的一级标签条 ---------- */
.tabbar {
  position: sticky;
  top: var(--header-h);
  z-index: 20;
  padding: 0 var(--pad);
  background: var(--bg);
  border-bottom: 1px solid var(--line);
}

/* 吸顶条自己有底线，内层标签条那条去掉，免得双线 */
.tabbar :deep(.c-tabs) {
  border-bottom: 0;
}

/* ---------- 面板 ---------- */
.panels {
  padding: var(--sec-y-tight) var(--pad) 0;
}

.subtabs {
  margin-bottom: var(--sp-6);
}

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

.stack {
  display: flex;
  flex-direction: column;
  gap: var(--sp-8);
}

@media (min-width: 768px) {
  .idband {
    padding: var(--sec-y) var(--pad);
  }

  .idband__face {
    width: 104px;
    height: 104px;
  }

  .idband__side {
    margin-left: auto;
    align-items: flex-end;
    text-align: right;
  }
}
</style>
