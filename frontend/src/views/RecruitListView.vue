<script setup lang="ts">
/** 页面布局与交互。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import BtnLink from '../components/BtnLink.vue'
import CButton from '../components/CButton.vue'
import LoadState from '../components/LoadState.vue'
import { errorText } from '../lib/api-error'
import { formatDateTime } from '../lib/datetime'
import {
  fetchGames,
  fetchTags,
  GAME_ORDERING_DEFAULT,
  GAME_ORDERING_OPTIONS,
  GAME_STATUS_OPTIONS,
  type GameListItem,
  type GameMode,
  type GameOrdering,
  type GameStatus,
  type GameTag,
} from '../api/games'
import type { RuleSystemPreset } from '../api/home'
import { useAuthStore } from '../stores/auth'
import { useHomeStore } from '../stores/home'
import { useSiteStore } from '../stores/site'

/** 「其他」哨兵：后端 `apps/siteconfig/services.OTHER_SENTINEL`，**大小写敏感**。 */
const OTHER = '__other__'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const home = useHomeStore()
const site = useSiteStore()
const { authenticated, isGm } = storeToRefs(auth)
const { config } = storeToRefs(site)

// —— 筛选状态：初值一律从地址栏读，之后再写回地址栏 ——
const ruleSystem = ref(readQuery('rule_system'))
const status = ref(readQuery('status') as GameStatus | '')
const mode = ref(readQuery('mode') as GameMode | '')
const tag = ref(readQuery('tag'))
const ordering = ref<GameOrdering>(readOrdering())
const page = ref(readPage())

const games = ref<GameListItem[]>([])
const presetTags = ref<GameTag[]>([])
const count = ref(0)
const hasNext = ref(false)
const loading = ref(true)
const error = ref('')

function readQuery(key: string): string {
  const value = route.query[key]
  return typeof value === 'string' ? value : ''
}

function readOrdering(): GameOrdering {
  const raw = readQuery('ordering')
  return GAME_ORDERING_OPTIONS.some((o) => o.value === raw)
    ? (raw as GameOrdering)
    : GAME_ORDERING_DEFAULT
}

function readPage(): number {
  const n = Number(readQuery('page'))
  return Number.isInteger(n) && n > 0 ? n : 1
}

/** 规则筹码：全部 / 站级预设 / 其他。预设优先用站长内容接口，拿不到就退回 siteconfig 的名字列表。 */
const rulePresets = computed<{ id: string; name: string }[]>(() => {
  const fromHome = home.rulePresets as RuleSystemPreset[]
  if (fromHome.length) return fromHome.map((p) => ({ id: 'p' + p.id, name: p.name }))
  return (config.value.rule_system_presets ?? []).map((name) => ({ id: name, name }))
})

/**
 * 地址栏里的规则不在站级预设里时（站主删过预设、或 GM 填的自定义规则名），临时补一枚筹码，
 * 否则从首页「了解该规则」跳过来的人看不到自己正处在哪个筛选里（v2 recruit.html 同样的处理）。
 */
const strayRule = computed(() => {
  const value = ruleSystem.value
  if (!value || value === OTHER) return ''
  return rulePresets.value.some((p) => p.name.toLowerCase() === value.toLowerCase()) ? '' : value
})

const modeOptions: { value: GameMode | ''; label: string }[] = [
  { value: '', label: '不限' },
  { value: 'online', label: '线上' },
  { value: 'offline', label: '线下' },
]

const dirty = computed(
  () =>
    Boolean(ruleSystem.value || status.value || mode.value || tag.value) ||
    ordering.value !== GAME_ORDERING_DEFAULT,
)

const totalPages = computed(() => Math.max(1, Math.ceil(count.value / 20)))

const countText = computed(() => {
  const parts = ['共 ' + count.value + ' 个团']
  if (totalPages.value > 1) parts.push('第 ' + page.value + ' / ' + totalPages.value + ' 页')
  const open = games.value.filter((g) => g.status === 'recruiting').length
  parts.push(open ? '本页 ' + open + ' 个正在招募' : '本页没有正在招募的')
  return parts.join(' · ')
})

/** 当前筛选对应的地址栏 query（地址栏是这一页的真源）。 */
function toQuery(): Record<string, string> {
  const q: Record<string, string> = {}
  if (ruleSystem.value) q.rule_system = ruleSystem.value
  if (status.value) q.status = status.value
  if (mode.value) q.mode = mode.value
  if (tag.value) q.tag = tag.value
  if (ordering.value !== GAME_ORDERING_DEFAULT) q.ordering = ordering.value
  if (page.value > 1) q.page = String(page.value)
  return q
}

/** 两个 query 是不是同一组值（用来分辨「地址栏是自己刚写进去的」）。 */
function sameQuery(a: Record<string, string>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(route.query)])
  for (const k of keys) {
    const b = route.query[k]
    if ((a[k] ?? '') !== (typeof b === 'string' ? b : '')) return false
  }
  return true
}

/** 把当前筛选写进地址栏（`router.replace`，不堆历史条目；见文件头注释）。 */
function syncUrl(): void {
  const q = toQuery()
  if (sameQuery(q)) return
  void router.replace({ path: route.path, query: q })
}

/**
 * 请求序号：只认最后一次发出的请求。单选项可以用方向键连续切换，
 * 每切一下就发一次请求，先发的晚回来时不能把后发的结果盖掉。
 */
let loadSeq = 0

async function load(): Promise<void> {
  const mine = ++loadSeq
  loading.value = true
  error.value = ''
  try {
    const data = await fetchGames({
      rule_system: ruleSystem.value,
      status: status.value,
      mode: mode.value,
      tag: tag.value,
      ordering: ordering.value,
      page: page.value,
    })
    if (mine !== loadSeq) return
    games.value = data.results
    count.value = data.count
    hasNext.value = Boolean(data.next)
    expanded.value = new Set()
  } catch (e) {
    if (mine !== loadSeq) return
    error.value = errorText(e, '招募列表暂时无法读取，请刷新后重试。')
    games.value = []
    count.value = 0
    hasNext.value = false
  } finally {
    if (mine === loadSeq) loading.value = false
  }
}

onMounted(async () => {
  // 站级预设（规则筹码）拿不到也不挡列表：两条都用各自的兜底继续渲染。
  void site.load()
  void home.load(authenticated.value)
  await load()
  try {
    presetTags.value = (await fetchTags()).results.filter((t) => t.is_preset)
  } catch {
    presetTags.value = []
  }
})

/** 正在按地址栏回填筛选：这一轮别再把状态写回地址栏，也别把页码归 1。 */
let fromUrl = false

watch([ruleSystem, status, mode, tag, ordering], () => {
  if (fromUrl) return
  page.value = 1
  syncUrl()
  void load()
})

/**
 * 前进后退（或有人直接改地址栏）：地址栏是真源，按它把筛选读回来并重拉。
 *
 * 只有「地址栏与当前筛选不一致」时才回填 —— 一致就说明这一次 query 变化是
 * 上面 `syncUrl()` 自己写进去的，回填会白跑一轮。
 */
watch(
  () => route.query,
  () => {
    if (route.name !== 'recruit') return
    if (sameQuery(toQuery())) return
    fromUrl = true
    ruleSystem.value = readQuery('rule_system')
    status.value = readQuery('status') as GameStatus | ''
    mode.value = readQuery('mode') as GameMode | ''
    tag.value = readQuery('tag')
    ordering.value = readOrdering()
    page.value = readPage()
    void nextTick(() => {
      fromUrl = false
    })
    void load()
  },
)

/**
 * 翻页。没有用 `watch(page)`：换筛选时也要把页码归一，两处都监听的话
 * 「在第 3 页换筛选」会先因 page 变化请求一次、再因筛选变化请求一次。
 */
function goPage(next: number): void {
  if (next === page.value || next < 1) return
  page.value = next
  syncUrl()
  void load()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function resetAll(): void {
  mode.value = ''
  ruleSystem.value = ''
  status.value = ''
  tag.value = ''
  ordering.value = GAME_ORDERING_DEFAULT
  // 五条筛选都在上面的 watch 里：有任何一条真的变了就会归页、同步地址、重拉，这里不用再补。
}

/** 报名门槛一行（两项各自可不设）。文案用后端的 `min_level_display`。 */
function gateText(game: GameListItem): string {
  const parts: string[] = []
  if (game.min_play_count) parts.push('团次数 ≥ ' + game.min_play_count)
  if (game.min_level_display) parts.push(game.min_level_display + '及以上')
  return parts.length ? parts.join(' · ') : '无门槛'
}

/** 展开后的事实表。枚举一律用后端 `*_display`，前端不另建中文映射表。 */
function facts(game: GameListItem): { k: string; v: string }[] {
  const card = game.requires_card
    ? '需要交卡' + (game.card_deadline ? '，截止 ' + formatDateTime(game.card_deadline) : '')
    : '不需要'
  return [
    { k: '开团时间', v: formatDateTime(game.start_at) },
    { k: '形式', v: game.mode_display + (game.location ? ' · ' + game.location : '') },
    { k: '占位', v: game.occupied_seats + ' / ' + game.max_players + ' 人' },
    { k: '人数要求', v: game.min_players + '–' + game.max_players + ' 人' },
    { k: '报名方式', v: game.signup_mode_display },
    { k: '报名门槛', v: gateText(game) },
    { k: '角色卡', v: card },
  ]
}

/** 行里的开团日期：「09-25 19:00」，不是今年的团前面补年份。本地时区，与 `formatDateTime` 一致。 */
function shortDate(value: string): string {
  const time = new Date(value)
  if (Number.isNaN(time.getTime())) return ''
  const two = (n: number) => String(n).padStart(2, '0')
  const day = two(time.getMonth() + 1) + '-' + two(time.getDate())
  const clock = two(time.getHours()) + ':' + two(time.getMinutes())
  const year = time.getFullYear() === new Date().getFullYear() ? '' : time.getFullYear() + '-'
  return year + day + ' ' + clock
}

// —— 原地展开：可以同时展开多行，翻页 / 换筛选后全部收起 ——
const expanded = ref<Set<number>>(new Set())

function isOpen(id: number): boolean {
  return expanded.value.has(id)
}

function toggle(id: number): void {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

// —— 筛选分组（桌面是目录式单选列表，手机是一条横向滑动的带；同一份数据、同一套单选框）——
type FilterKey = 'rule' | 'status' | 'mode' | 'tag'

interface FilterGroup {
  key: FilterKey
  label: string
  aria: string
  value: string
  options: { value: string; label: string }[]
}

const filterGroups = computed<FilterGroup[]>(() => {
  const rules = [
    { value: '', label: '全部' },
    ...rulePresets.value.map((p) => ({ value: p.name, label: p.name })),
    { value: OTHER, label: '其他' },
  ]
  if (strayRule.value) rules.push({ value: strayRule.value, label: strayRule.value })
  return [
    { key: 'rule', label: '规则', aria: '按规则系统筛选', value: ruleSystem.value, options: rules },
    {
      key: 'status',
      label: '状态',
      aria: '按状态筛选',
      value: status.value,
      // 文案照抄后端 GAME_STATUS_CHOICES（api/games.ts 的 GAME_STATUS_OPTIONS），
      // 与行里的 status_display 一字不差；筛选项拿不到实例，只能用这份常量。
      options: GAME_STATUS_OPTIONS,
    },
    { key: 'mode', label: '形式', aria: '按线上线下筛选', value: mode.value, options: modeOptions },
    {
      key: 'tag',
      label: '标签',
      aria: '按标签筛选',
      value: tag.value,
      options: [
        { value: '', label: '全部' },
        ...presetTags.value.map((t) => ({ value: t.name, label: t.name })),
        { value: OTHER, label: '其他' },
      ],
    },
  ]
})

/** 排序单独放在「/ 列表」标题行右侧（它管的是列表怎么排，不是筛掉哪些团）。 */
function onOrdering(event: Event): void {
  ordering.value = (event.target as HTMLSelectElement).value as GameOrdering
}

// —— 横向滑动筛选带（<1200）：两端渐隐提示「还有」，竖向滚轮转横向 ——
const strip = ref<HTMLElement | null>(null)
const fadeLeft = ref(false)
const fadeRight = ref(false)

/**
 * 让右缘截断处落在某个选项的半中间（而不是恰好落在两项之间的空隙，看起来像「已经完整」）：
 * 右缘正好卡在空隙里时，把带子右侧收窄一点（`--strip-trim`），让最后一个完整可见的选项露出约一半。
 * 只按「滚动到最左」时的布局算，结果稳定，不会和 ResizeObserver 来回震荡。
 */
function trimEdge(el: HTMLElement): void {
  const current = parseFloat(el.style.getPropertyValue('--strip-trim')) || 0
  const box = el.getBoundingClientRect()
  const edge = box.right + current
  const items = Array.from(el.querySelectorAll<HTMLElement>('.fopt')).map((node) => {
    const r = node.getBoundingClientRect()
    return { left: r.left + el.scrollLeft, right: r.right + el.scrollLeft }
  })
  const overflow = items.length > 0 && items[items.length - 1]!.right > edge + 1
  let trim = 0
  if (overflow && !items.some((i) => i.left < edge - 8 && i.right > edge + 8)) {
    const last = [...items].reverse().find((i) => i.right <= edge)
    if (last) trim = Math.max(0, Math.round(edge - (last.left + (last.right - last.left) * 0.5)))
  }
  if (trim !== current) el.style.setProperty('--strip-trim', trim + 'px')
}

function updateFade(): void {
  const el = strip.value
  if (!el) return
  if (el.scrollLeft <= 1) trimEdge(el)
  const max = el.scrollWidth - el.clientWidth
  fadeLeft.value = max > 1 && el.scrollLeft > 1
  fadeRight.value = max > 1 && el.scrollLeft < max - 1
}

/**
 * 竖向滚轮转成横滚。只在「带子确实能横滚、且这个方向还没到头」时拦截，
 * 到头之后放行，页面照常上下滚 —— 不劫持整页滚动。触控板的横向手势（deltaX 为主）不管。
 */
function onStripWheel(event: WheelEvent): void {
  const el = strip.value
  if (!el || Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return
  const max = el.scrollWidth - el.clientWidth
  if (max <= 1) return
  const atStart = el.scrollLeft <= 0 && event.deltaY < 0
  const atEnd = el.scrollLeft >= max - 1 && event.deltaY > 0
  if (atStart || atEnd) return
  event.preventDefault()
  el.scrollLeft += event.deltaY
}

let stripObserver: ResizeObserver | null = null
onMounted(() => {
  document.documentElement.classList.add('rec-page')
  updateFade()
  if (typeof ResizeObserver !== 'undefined' && strip.value) {
    stripObserver = new ResizeObserver(updateFade)
    stripObserver.observe(strip.value)
  }
})
onBeforeUnmount(() => {
  document.documentElement.classList.remove('rec-page')
  stripObserver?.disconnect()
})
// 预设规则与标签是异步到的，带子变宽之后重算一次两端渐隐
watch(filterGroups, () => void nextTick(updateFade))

function setFilter(key: FilterKey, value: string): void {
  if (key === 'rule') ruleSystem.value = value
  else if (key === 'status') status.value = value as GameStatus | ''
  else if (key === 'mode') mode.value = value as GameMode | ''
  else tag.value = value
}

const emptyText =
  '换个规则、把状态放宽到「全部」，或者清掉筛选再看看。有人放团时会出现在最前面。'

/** 分页条上的页码（首尾 + 当前页附近，其余折成省略号）。 */
const pageItems = computed<(number | 'gap')[]>(() => {
  const total = totalPages.value
  const current = page.value
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const keep = new Set([1, total, current, current - 1, current + 1])
  const out: (number | 'gap')[] = []
  for (let n = 1; n <= total; n += 1) {
    if (keep.has(n)) out.push(n)
    else if (out[out.length - 1] !== 'gap') out.push('gap')
  }
  return out
})

const loginNext = '/auth/login?next=' + encodeURIComponent('/recruit')
</script>


<template>
  <div class="rec u-rise">
    <!-- 页头：超大标题 + 右上角数量角标（仿 stripe.dev「Featured (20)」） -->
    <header class="rec__head">
      <p class="u-kicker">Open tables · 招募</p>
      <h1 class="rec__title">
        招募<sup v-if="!loading || count" class="rec__count" aria-hidden="true">({{ count }})</sup>
        <span v-if="!loading || count" class="u-hidden">，共 {{ count }} 个团</span>
      </h1>
    </header>

    <p class="u-lead rec__lead">
      站内所有已发布的团。按规则、状态和时间筛一遍，点开一行看要求，进详情页看完整公告和交卡截止。
    </p>

    <div class="rec__aside">
      <BtnLink v-if="isGm" class="rec__aside-gm" to="/games/new">我要开团 →</BtnLink>
      <span v-else-if="authenticated === false" class="u-small rec__side-note">
        开团需要 GM 身份。注册后申请，或作为玩家参团
        {{ config.gm_auto_promote_threshold }} 次自动获得。
      </span>
      <span v-else class="u-small rec__side-note">
        还不是 GM：参团 {{ config.gm_auto_promote_threshold }} 次自动获得，也可以在账号设置里申请。
      </span>
    </div>

    <!-- 筛选：桌面目录式单选列表 / 平板分组横排 / 手机一条横向滑动的带 -->
    <section class="rec__filters" aria-labelledby="rec-filters-h">
      <div class="rec-sh rec-sh--bar">
        <h2 id="rec-filters-h" class="rec-sh__t">/ 筛选</h2>
        <button class="rec-act" type="button" :disabled="!dirty" @click="resetAll">清空筛选</button>
      </div>
      <div
        ref="strip"
        class="fgroups"
        :class="{ 'is-fade-l': fadeLeft, 'is-fade-r': fadeRight }"
        @scroll.passive="updateFade"
        @wheel="onStripWheel"
      >
        <div
          v-for="group in filterGroups"
          :key="group.key"
          class="fgroup"
          role="radiogroup"
          :aria-label="group.aria"
        >
          <span class="fgroup__k" aria-hidden="true">{{ group.label }}</span>
          <label
            v-for="(option, index) in group.options"
            :key="group.key + '-' + index"
            class="fopt"
          >
            <input
              class="fopt__input"
              type="radio"
              :name="'rec-f-' + group.key"
              :value="option.value"
              :checked="group.value === option.value"
              @change="setFilter(group.key, option.value)"
            />
            <span class="fopt__text">{{ option.label }}</span>
          </label>
        </div>
      </div>
    </section>

    <section class="rec__list" aria-labelledby="rec-list-h">
      <div class="rec-sh rec-sh--bar">
        <h2 id="rec-list-h" class="rec-sh__t">/ 列表</h2>
        <p class="rec-sh__count" aria-live="polite">{{ countText }}</p>
        <label class="rec-sort">
          <span class="rec-sort__k">排序</span>
          <select class="rec-sort__sel" :value="ordering" @change="onOrdering">
            <option v-for="option in GAME_ORDERING_OPTIONS" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
      </div>


      <LoadState
        :loading="loading"
        :error="error"
        :empty="!games.length"
        empty-title="这组条件下没有团"
        :empty-text="emptyText"
      >
        <template #empty-actions>
          <CButton v-if="dirty" variant="ghost" @click="resetAll">清空筛选</CButton>
          <RouterLink v-if="isGm" class="c-textlink" to="/games/new">不如自己开一个 →</RouterLink>
        </template>

        <div class="rows__head" aria-hidden="true">
          <span class="rows__h rows__h--date">开团</span>
          <span class="rows__h rows__h--title">团名</span>
          <span class="rows__h rows__h--rule">规则</span>
          <span class="rows__h rows__h--status">状态</span>
          <span class="rows__h rows__h--seats">人数</span>
        </div>

        <ul class="rows">
          <li
            v-for="game in games"
            :key="game.id"
            class="row"
            :class="{
              'row--dim': game.status === 'finished' || game.status === 'cancelled',
              'is-open': isOpen(game.id),
            }"
          >
            <button
              :id="'rec-row-' + game.id"
              class="row__bar"
              type="button"
              :aria-expanded="isOpen(game.id) ? 'true' : 'false'"
              :aria-controls="'rec-panel-' + game.id"
              @click="toggle(game.id)"
            >
              <span class="row__title">{{ game.title }}</span>
              <span class="row__meta">
                <span class="row__date">{{ shortDate(game.start_at) }}</span>
                <span class="row__rule">{{ game.rule_system || '未填规则' }}</span>
                <span class="row__status" :class="'row__status--' + game.status">
                  {{ game.status_display }}
                </span>
                <span class="row__seats">{{ game.occupied_seats }} / {{ game.max_players }} 人</span>
              </span>
              <span class="row__plus" aria-hidden="true"><AppIcon name="plus" :size="18" /></span>
            </button>

            <div
              v-show="isOpen(game.id)"
              :id="'rec-panel-' + game.id"
              class="row__panel"
              role="region"
              :aria-labelledby="'rec-row-' + game.id"
            >
              <div class="row__panel-in">
                <dl class="row__facts">
                  <div v-for="fact in facts(game)" :key="fact.k" class="row__fact">
                    <dt>{{ fact.k }}</dt>
                    <dd>{{ fact.v }}</dd>
                  </div>
                </dl>
                <p class="row__who">
                  <img v-if="game.gm.avatar" class="row__face" :src="game.gm.avatar" alt="" />
                  <span v-else class="row__face row__face--blank" aria-hidden="true"></span>
                  <span>GM · {{ game.gm.nickname }}</span>
                  <span v-if="game.tags.length" class="row__tags">
                    <span v-for="name in game.tags" :key="name" class="row__tag">{{ name }}</span>
                  </span>
                </p>
                <RouterLink class="row__go" :to="'/games/' + game.id">
                  <span>查看详情：{{ game.title }}</span>
                  <AppIcon name="arrow" :size="16" />
                </RouterLink>
              </div>
            </div>
          </li>
        </ul>

        <nav v-if="totalPages > 1" class="pager" aria-label="分页">
          <button
            class="pager__btn"
            type="button"
            :disabled="page <= 1"
            @click="goPage(page - 1)"
          >
            上一页
          </button>
          <template v-for="(item, index) in pageItems" :key="index">
            <span v-if="item === 'gap'" class="pager__gap" aria-hidden="true">…</span>
            <button
              v-else
              class="pager__btn"
              :class="{ 'pager__btn--now': item === page }"
              type="button"
              :aria-current="item === page ? 'page' : undefined"
              @click="goPage(item)"
            >
              {{ item }}
            </button>
          </template>
          <button class="pager__btn" type="button" :disabled="!hasNext" @click="goPage(page + 1)">
            下一页
          </button>
        </nav>
      </LoadState>

      <!-- 游客说明：压成一行放在列表之后，不挡首屏的团 -->
      <p v-if="authenticated === false" class="rec__guest">
        <span>游客看不到谁报了名：报名者身份只对登录成员可见，正式名单只对同团成员可见。</span>
        <RouterLink class="c-textlink" :to="loginNext">登录后再看 →</RouterLink>
      </p>

      <div class="rec__foot">
        <span class="u-small">列表一页 20 个团，顺序按筛选里选的排序来。</span>
        <RouterLink v-if="isGm" class="c-textlink" to="/games/new">发布我的招募 →</RouterLink>
        <RouterLink v-else-if="authenticated === false" class="c-textlink" to="/auth/signup">
          注册账号 →
        </RouterLink>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* ==========================================================================
   页面网格：<1200 单栏；≥1200 一套 12 列，筛选占左 3 列、其余内容落在第 4 列起的同一条列线上
   ========================================================================== */

.rec {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: start;
  /* 列表表格列（≥768 用）：日期 / 团名 / 规则 / 状态 / 人数 / +。
     用字号令牌乘倍数而不是 em：表头与行字号不同，em 会让两边列线错开 */
  --cols: calc(var(--fs-md) * 9) minmax(0, 1fr) minmax(0, calc(var(--fs-md) * 8))
    calc(var(--fs-md) * 6.5) calc(var(--fs-md) * 5.5) 40px;
}

.rec__head {
  margin-bottom: var(--sp-3);
}

.rec__head .u-kicker {
  margin: 0;
}

/* 超大标题：中文 300 字重（苹方 Light / 雅黑 Light），字距只收一点点 */
.rec__title {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-h-mega);
  font-weight: 300;
  line-height: 1.1;
  letter-spacing: var(--ls-mega);
  color: var(--ink);
}

/* 右上角数量角标：约为标题三成大，贴着字顶 */
.rec__count {
  position: relative;
  top: -0.2em;
  margin-left: 0.12em;
  font-size: 0.3em;
  font-weight: 400;
  letter-spacing: 0;
  vertical-align: top;
  font-variant-numeric: tabular-nums;
  color: var(--ink-muted);
}

.rec__lead {
  max-width: 60ch;
  margin: 0 0 var(--sp-3);
}

.rec__aside {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-4);
}

.rec__side-note {
  max-width: 38ch;
}

/* 区块小标题「/ 名称」+ 1px 细线（只在本页用） */
.rec-sh {
  margin: 0;
  padding-bottom: var(--sp-2);
  font-size: var(--fs-sm);
  font-weight: 400;
  letter-spacing: var(--ls-mid);
  color: var(--ink);
  border-bottom: 1px solid var(--ink);
}

.rec-sh--bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-1) var(--sp-4);
  min-height: 32px;
}

.rec-sh__t {
  margin: 0;
  font-size: inherit;
  font-weight: inherit;
}

.rec-sh__count {
  flex: 1 1 14em;
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--ink-muted);
}

/* 标题行右侧的文字按钮（「清空筛选」）：与表格同一套细线 + 文字语言，不用描边方框 */
.rec-act {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 0;
  font: inherit;
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-mid);
  color: var(--brand-ink);
  background: none;
  border: 0;
  border-bottom: 1px solid currentColor;
  cursor: pointer;
}

.rec-act:disabled {
  color: var(--ink-faint);
  border-bottom-color: transparent;
  cursor: default;
}

.rec-act:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

/* 「/ 列表」标题行右侧的排序：原生下拉，外观压成「排序 最新发布」一行细字 + 下划线 */
.rec-sort {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--ink-muted);
}

.rec-sort__sel {
  min-height: 32px;
  max-width: 12em;
  padding: 0 var(--sp-1);
  font: inherit;
  font-size: var(--fs-xs);
  color: var(--ink);
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--ink);
  border-radius: 0;
  cursor: pointer;
}

.rec-sort__sel:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

.rec__filters {
  margin-top: var(--sp-4);
  min-width: 0;
}

.rec__list {
  margin-top: var(--sp-4);
  min-width: 0;
}

/* 游客说明：一行细字，上下与表格同样的 1px 线 */
.rec__guest {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-1) var(--sp-4);
  margin: var(--sp-4) 0 0;
  padding: var(--sp-2) 0;
  font-size: var(--fs-xs);
  color: var(--ink-muted);
  border-bottom: 1px solid var(--line);
}

/* ==========================================================================
   筛选。<1200：一条横向滑动的带（选中项是品牌色胶囊）
   ========================================================================== */

.fgroups {
  display: flex;
  gap: var(--sp-4);
  margin: 0 calc(-1 * var(--pad));
  margin-right: calc(var(--strip-trim, 0px) - var(--pad));
  padding: var(--sp-3) var(--pad);
  overflow-x: auto;
  overscroll-behavior-x: contain;
  scrollbar-width: none;
}

.fgroups::-webkit-scrollbar {
  display: none;
}

/* 两端渐隐：还能往哪边滚，哪边就淡出（被截断的选项露出半截、渐隐），滚到头那一端的遮罩消失。
   遮罩只看透明度，渐变色用哪个不透明色都一样，这里借 --ink */
.fgroups.is-fade-r {
  -webkit-mask-image: linear-gradient(90deg, var(--ink) calc(100% - 64px), transparent);
  mask-image: linear-gradient(90deg, var(--ink) calc(100% - 64px), transparent);
}

.fgroups.is-fade-l {
  -webkit-mask-image: linear-gradient(90deg, transparent, var(--ink) 48px);
  mask-image: linear-gradient(90deg, transparent, var(--ink) 48px);
}

.fgroups.is-fade-l.is-fade-r {
  -webkit-mask-image: linear-gradient(90deg, transparent, var(--ink) 48px, var(--ink) calc(100% - 64px), transparent);
  mask-image: linear-gradient(90deg, transparent, var(--ink) 48px, var(--ink) calc(100% - 64px), transparent);
}

.fgroup {
  display: flex;
  flex: none;
  align-items: center;
  gap: var(--sp-1);
}

.fgroup + .fgroup {
  padding-left: var(--sp-4);
  border-left: 1px solid var(--line);
}

.fgroup__k {
  margin-right: var(--sp-1);
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-mid);
  color: var(--ink-muted);
  white-space: nowrap;
}

.fopt {
  position: relative;
  display: inline-flex;
  flex: none;
  cursor: pointer;
}

/* 原生单选框留在无障碍树里（方向键切换、读屏报「第几项共几项」），视觉上藏起来 */
.fopt__input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  opacity: 0;
  cursor: pointer;
}

.fopt__text {
  position: relative;
  display: inline-flex;
  align-items: center;
  min-height: 36px;
  padding: 0 var(--sp-2);
  font-size: var(--fs-sm);
  white-space: nowrap;
  color: var(--ink-muted);
  transition: color var(--dur) var(--ease);
}

/* 与桌面目录短横同一套语言：未选只有文字，悬浮在字下出一道细横，选中是品牌色短横 + 文字加深加粗 */
.fopt__text::after {
  content: "";
  position: absolute;
  left: var(--sp-2);
  bottom: 5px;
  width: 0;
  height: 2px;
  background: var(--ink-soft);
  transition: width var(--dur) var(--ease), background-color var(--dur) var(--ease);
}

.fopt:hover .fopt__text {
  color: var(--ink);
}

.fopt:hover .fopt__text::after {
  width: 12px;
}

.fopt__input:checked ~ .fopt__text {
  font-weight: 500;
  color: var(--ink);
}

.fopt__input:checked ~ .fopt__text::after {
  width: 16px;
  background: var(--brand);
}

.fopt__input:focus-visible ~ .fopt__text {
  outline: 2px solid var(--brand);
  outline-offset: -2px;
  border-radius: var(--radius);
}

/* ==========================================================================
   列表行（表格式，1px 分隔线；悬浮整行铺品牌浅色，不位移不加阴影）
   手机：两行文字 —— 团名一行、「日期 · 规则 · 状态 · 人数」一行
   ========================================================================== */

.rows__head {
  display: none;
}

.rows {
  margin: 0;
  padding: 0;
  list-style: none;
}

.row {
  border-bottom: 1px solid var(--line);
}

.row__bar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 40px;
  grid-template-areas:
    "title plus"
    "meta plus";
  align-items: center;
  column-gap: var(--sp-3);
  row-gap: 2px;
  width: 100%;
  min-height: 52px;
  padding: var(--sp-2);
  font: inherit;
  font-size: var(--fs-md);
  text-align: left;
  color: var(--ink);
  background: transparent;
  border: 0;
  cursor: pointer;
  transition: background-color var(--dur) var(--ease);
}

.row__bar:hover,
.row.is-open .row__bar {
  background: var(--brand-wash);
}

.row__bar:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: -2px;
}

.row__title {
  grid-area: title;
  min-width: 0;
  font-size: var(--fs-lg);
  line-height: var(--lh-card);
  overflow-wrap: anywhere;
}

.row__meta {
  grid-area: meta;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  min-width: 0;
  font-size: var(--fs-sm);
  color: var(--ink-muted);
}

/* 分隔点挂在前一项的尾巴上（整项不折行），折行时新一行不会以孤立的「·」开头 */
.row__meta > span {
  white-space: nowrap;
}

.row__meta > span:not(:last-child)::after {
  content: "·";
  margin: 0 var(--sp-2);
  color: var(--ink-faint);
}

.row__date,
.row__seats {
  font-variant-numeric: tabular-nums;
}

/* 状态：一颗状态色点（五值令牌 --st-*）+ 后端 status_display 文字 */
.row__status::before {
  content: "";
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: var(--sp-1);
  vertical-align: middle;
  border-radius: var(--radius-pill);
  background: var(--st-dot, currentColor);
}

.row__status--recruiting {
  --st-dot: var(--st-recruiting);
}

.row__status--closed_signup {
  --st-dot: var(--st-closed-signup);
}

.row__status--running {
  --st-dot: var(--st-running);
}

.row__status--finished {
  --st-dot: var(--st-finished);
}

.row__status--cancelled {
  --st-dot: var(--st-cancelled);
}

.row--dim .row__title {
  color: var(--ink-muted);
}

.row__plus {
  grid-area: plus;
  display: inline-grid;
  place-items: center;
  width: 40px;
  height: 40px;
  color: var(--ink-soft);
  border: 1px solid var(--line-2);
  border-radius: var(--radius-pill);
  transition: transform var(--dur) var(--ease);
}

/* 展开：「+」转 45° 成「×」（减少动态下同样是瞬时切换，状态照样看得出） */
.row.is-open .row__plus {
  transform: rotate(45deg);
}

.row__panel {
  padding: var(--sp-2) var(--sp-2) var(--sp-4);
  background: var(--brand-wash);
}

.row__panel-in {
  min-width: 0;
}

.row__facts {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-1) var(--sp-5);
  margin: 0;
}

.row__fact {
  display: grid;
  grid-template-columns: 5.5em minmax(0, 1fr);
  gap: var(--sp-2);
  font-size: var(--fs-md);
}

.row__fact dt {
  color: var(--ink-muted);
}

.row__fact dd {
  margin: 0;
  color: var(--ink);
  overflow-wrap: anywhere;
}

.row__who {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: var(--sp-3) 0;
  font-size: var(--fs-md);
  color: var(--ink-soft);
}

.row__face {
  flex: none;
  width: 24px;
  height: 24px;
  object-fit: cover;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line);
  background: var(--avatar-bg);
}

.row__tags {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--sp-1);
}

.row__tag {
  padding: 0 var(--sp-2);
  font-size: var(--fs-xs);
  line-height: 20px;
  color: var(--ink-soft);
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius-pill);
}

/* 「查看详情」：整行可点的文字链接行，上方一条深色细线，悬浮铺白 —— 不用整块墨绿实心 */
.row__go {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  min-height: 44px;
  padding: 0 var(--sp-2);
  font-size: var(--fs-md);
  color: var(--brand-ink);
  text-decoration: none;
  border-top: 1px solid var(--ink);
  transition: background-color var(--dur) var(--ease);
}

.row__go span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.row__go:hover {
  background: var(--white);
}

.row__go:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: -2px;
}

/* ==========================================================================
   分页与页脚行
   ========================================================================== */

.pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  margin-top: var(--sp-5);
}

.pager__btn {
  min-width: 44px;
  min-height: 44px;
  padding: 0 var(--sp-3);
  display: inline-grid;
  place-items: center;
  font-size: var(--fs-sm);
  color: var(--ink-soft);
  background: var(--white);
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
}

.pager__btn:disabled {
  color: var(--ink-faint);
  cursor: not-allowed;
}

.pager__btn--now {
  color: var(--on-brand);
  background: var(--brand);
  border-color: var(--brand);
}

.pager__gap {
  min-width: 20px;
  text-align: center;
  color: var(--ink-faint);
}

.rec__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  /* 左边一句说明、右边一个去向：贴在一起看着像同一句话，分到两端才读得出「这是出口」 */
  justify-content: space-between;
  gap: var(--sp-1) var(--sp-5);
  margin-top: var(--sp-3);
  padding-top: var(--sp-2);
}

/* ==========================================================================
   ≥768：列表换成表格列；筛选仍是一条横向滑动的带（不在列表上方堆一大块）
   ========================================================================== */

@media (min-width: 768px) {
  /* ≥768 的 --pad 是含百分比的表达式，在这里展开会按本元素宽度重算，所以不做出血 */
  .fgroups {
    margin: 0 var(--strip-trim, 0px) 0 0;
    padding: var(--sp-3) 0;
  }

  .rows__head {
    display: grid;
    grid-template-columns: var(--cols);
    column-gap: var(--sp-3);
    padding: var(--sp-2);
    font-size: var(--fs-xs);
    letter-spacing: var(--ls-mid);
    color: var(--ink-muted);
    border-bottom: 1px solid var(--line);
  }

  .row__bar {
    grid-template-columns: var(--cols);
    grid-template-areas: "date title rule status seats plus";
  }

  .row__meta {
    display: contents;
  }

  .row__meta > span:not(:last-child)::after {
    content: none;
  }

  .row__date {
    grid-area: date;
    color: var(--ink-soft);
  }

  .row__rule {
    grid-area: rule;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--ink-soft);
  }

  .row__status {
    grid-area: status;
    color: var(--ink-soft);
  }

  .row__seats {
    grid-area: seats;
    color: var(--ink-soft);
  }

  /* 展开区与表格同一套列：内容从「团名」那一列起，左边缘对齐团名 */
  .row__panel {
    display: grid;
    grid-template-columns: var(--cols);
    column-gap: var(--sp-3);
    font-size: var(--fs-md);
  }

  .row__panel-in {
    grid-column: 2 / -1;
  }

  .row__facts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* ==========================================================================
   ≥1200：12 列页面网格，筛选左 3 列（目录式单选）、导语与列表从第 4 列起
   ========================================================================== */

@media (min-width: 1200px) {
  .rec {
    grid-template-columns: repeat(12, minmax(0, 1fr));
    column-gap: var(--sp-6);
  }

  .rec__head {
    grid-column: 1 / -1;
  }

  .rec__aside {
    grid-column: 1 / 4;
    grid-row: 2;
    align-self: start;
  }

  /* 顶栏右侧已有「我要开团」胶囊，这一档不在标题下再放一个 */
  .rec__aside-gm {
    display: none;
  }

  .rec__lead {
    grid-column: 4 / -1;
    grid-row: 2;
  }

  .rec__filters {
    grid-column: 1 / 4;
    grid-row: 3;
  }

  .rec__list {
    grid-column: 4 / -1;
    grid-row: 3;
  }

  .rec__filters,
  .rec__list {
    margin-top: var(--sp-6);
  }

  .fgroups {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--sp-4);
    padding: var(--sp-3) 0 0;
    overflow: visible;
  }

  .fgroup {
    flex-direction: column;
    align-items: stretch;
    gap: 0;
  }

  .fgroup + .fgroup {
    padding-left: 0;
    border-left: 0;
  }

  .fgroup__k {
    margin: 0 0 2px;
  }

  /* 目录式单选：左侧一道短横，选中时拉长加粗成品牌色，文字转深 —— 像目录里「当前所在」的标记 */
  .fopt {
    display: flex;
  }

  .fopt__text {
    width: 100%;
    min-height: 28px;
    padding: 0 var(--sp-2) 0 0;
    gap: var(--sp-2);
    white-space: normal;
    border: 0;
    border-radius: 0;
  }

  .fopt__text::before {
    content: "";
    flex: none;
    width: 8px;
    height: 1px;
    background: var(--ink-faint);
    transition: width var(--dur) var(--ease), background-color var(--dur) var(--ease);
  }

  /* 目录态不用字下那道横（短横挪到字前） */
  .fopt__text::after {
    content: none;
  }

  .fopt:hover .fopt__text::before {
    width: 12px;
    background: var(--ink-soft);
  }

  .fopt__input:checked ~ .fopt__text::before {
    width: 16px;
    height: 2px;
    background: var(--brand);
  }

  .fopt__input:focus-visible ~ .fopt__text {
    outline-offset: 0;
  }
}

/* 视口够高才让筛选栏贴顶跟随；矮屏（如 1280×800）回到正常文档流，随页面滚动全部可达 */
@media (min-width: 1200px) and (min-height: 1000px) {
  .rec__filters {
    position: sticky;
    top: calc(var(--header-h) + var(--sp-4));
    max-height: calc(100dvh - var(--header-h) - var(--sp-6));
    overflow-y: auto;
    scrollbar-width: thin;
  }
}

/* 宽屏（>1920）：全局 --pad 会把版心收到 1080，表格反而比 1920 窄；
   本页单独把内容撑回 1440（不动全局 --pad 规则），两侧留白随屏宽继续增长 */
@media (min-width: 1921px) {
  .rec {
    width: min(1440px, 100vw - 480px);
    margin-inline: calc((100% - min(1440px, 100vw - 480px)) / 2);
  }
}

/* 触屏：筛选项抬到 44px（与全站 .c-chip 同一条登记例外；放在最后，压过上面的 28/36px） */
@media (pointer: coarse) {
  .fopt__text,
  .rec-act,
  .rec-sort__sel {
    min-height: 44px;
  }
}
</style>

<style>
/* 非 scoped：宽屏下本页版心撑到 1440 之后，页脚（AppFooter，外壳里的兄弟节点）跟着对齐。
   只在本页挂载期间生效（`html.rec-page` 由本组件挂上/摘掉），不改全局 --pad。 */
@media (min-width: 1921px) {
  html.rec-page .c-foot-bar {
    padding-left: calc((100% - min(1440px, 100% - 480px)) / 2);
    padding-right: calc((100% - min(1440px, 100% - 480px)) / 2);
  }
}
</style>
