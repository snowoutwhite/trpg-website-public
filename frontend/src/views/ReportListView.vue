<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import BlurStage from '../components/BlurStage.vue'
import CButton from '../components/CButton.vue'
import CChip from '../components/CChip.vue'
import CNotice from '../components/CNotice.vue'
import LoadState from '../components/LoadState.vue'
import PageHead from '../components/PageHead.vue'
import { fetchFeaturedReports, fetchReports, type ReportListItem } from '../api/reports'
import type { RuleSystemPreset } from '../api/home'
import { errorText } from '../lib/api-error'
import { formatDate } from '../lib/datetime'
import { ruleArtFile } from '../lib/rule-art'
import { useAuthStore } from '../stores/auth'
import { useHomeStore } from '../stores/home'
import { useSiteStore } from '../stores/site'

/** 「其他」哨兵：与招募列表同名，后端 `apps/siteconfig/services.OTHER_SENTINEL`（大小写敏感）。 */
const OTHER = '__other__'
/** 后端 `common/pagination.StandardPagination.page_size`。 */
const PAGE_SIZE = 20

type ScopeKey = 'featured' | 'public' | 'mine'

const SCOPES: { key: ScopeKey; label: string; guest: boolean; desc: string }[] = [
  { key: 'featured', label: '精选', guest: true, desc: '站主挑出来对所有人公开的几篇。' },
  { key: 'public', label: '全部', guest: false, desc: '你能看到的全部战报，含自己团里「仅同团可见」的。' },
  { key: 'mine', label: '我参加的团', guest: false, desc: '你到场过或主持过的团里的战报。' },
]

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const home = useHomeStore()
const site = useSiteStore()
const { authenticated } = storeToRefs(auth)
const { config } = storeToRefs(site)

/** 地址栏里显式写了范围吗？没写的话登录用户默认落在「全部」，游客落在「精选」。 */
const scopeInUrl = SCOPES.some((s) => s.key === readQuery('scope'))
const scope = ref<ScopeKey>(readScope())
const rule = ref(readQuery('rule_system'))
/** 团筛选：跟地址栏的 `?game=` 同步，方便从团页带着团跳过来（这一条**是**服务端筛选）。 */
const gameFilter = ref(readQuery('game'))
const page = ref(readPage())

const items = ref<ReportListItem[]>([])
const count = ref(0)
const loading = ref(true)
const error = ref('')
/** 首屏那次请求由 onMounted 自己发；在那之前不让 watch 再发一次。 */
const mounted = ref(false)

function readQuery(key: string): string {
  const value = route.query[key]
  return typeof value === 'string' ? value : ''
}

function readScope(): ScopeKey {
  const raw = readQuery('scope')
  return SCOPES.some((s) => s.key === raw) ? (raw as ScopeKey) : 'featured'
}

function readPage(): number {
  const n = Number(readQuery('page'))
  return Number.isInteger(n) && n > 0 ? n : 1
}

/** 站级规则预设：优先站长内容接口，拿不到退回 siteconfig 的名字列表（同招募列表）。 */
const rulePresets = computed<{ id: string; name: string }[]>(() => {
  const fromHome = home.rulePresets as RuleSystemPreset[]
  if (fromHome.length) return fromHome.map((p) => ({ id: 'p' + p.id, name: p.name }))
  return (config.value.rule_system_presets ?? []).map((name) => ({ id: name, name }))
})

/** 当前这一档是否对游客开放（游客只有「精选」）。 */
function locked(key: ScopeKey): boolean {
  return authenticated.value !== true && !SCOPES.find((s) => s.key === key)?.guest
}

/** 这个身份的默认档：游客只有精选，登录用户默认看全部。 */
const defaultScope = computed<ScopeKey>(() =>
  authenticated.value === true ? 'public' : 'featured',
)
const dirty = computed(
  () =>
    scope.value !== defaultScope.value || Boolean(rule.value) || Boolean(gameFilter.value),
)
const totalPages = computed(() => Math.max(1, Math.ceil(count.value / PAGE_SIZE)))

const scopeDesc = computed(
  () => SCOPES.find((s) => s.key === scope.value)?.desc ?? SCOPES[0].desc,
)

const countText = computed(() => {
  const label = SCOPES.find((s) => s.key === scope.value)?.label ?? '精选'
  const parts = [label + ' · 共 ' + count.value + ' 篇']
  if (totalPages.value > 1) parts.push('第 ' + page.value + ' / ' + totalPages.value + ' 页')
  return parts.join(' · ')
})

const emptyText = computed(() => {
  if (rule.value || gameFilter.value) return '这组条件下没有战报，换个规则或清掉筛选再看看。'
  if (scope.value === 'mine') return '你到场过或主持过的团里还没有战报。'
  if (scope.value === 'featured') return '站主还没有从大家的战报里挑出精选。'
  return '还没有你能看到的战报。团结束之后，到场的人都可以写一份。'
})

/** 当前筛选对应的地址栏 query（地址栏是这一页的真源）。 */
function toQuery(): Record<string, string> {
  const q: Record<string, string> = {}
  if (scope.value !== 'featured') q.scope = scope.value
  if (rule.value) q.rule_system = rule.value
  if (gameFilter.value) q.game = gameFilter.value
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

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data =
      scope.value === 'featured'
        ? await fetchFeaturedReports({ rule_system: rule.value, page: page.value })
        : await fetchReports({
            game: gameFilter.value,
            rule_system: rule.value,
            mine: scope.value === 'mine' ? '1' : undefined,
            page: page.value,
          })
    items.value = data.results
    count.value = data.count
  } catch (e) {
    error.value = errorText(e, '战报暂时无法读取，请刷新后重试。')
    items.value = []
    count.value = 0
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  void site.load()
  await auth.refresh()
  void home.load(authenticated.value === true)
  // 游客只有「精选」一档：地址栏里带着别的 scope 也要落回来
  if (locked(scope.value)) {
    scope.value = 'featured'
  } else if (
    // 登录用户没指定范围时默认「全部」—— 他们能看的本来就不止精选那几篇；
    // 「精选」接口也不认 `?game=`，带着团跳过来时同样要切到「全部」。
    authenticated.value === true &&
    scope.value === 'featured' &&
    (!scopeInUrl || gameFilter.value)
  ) {
    scope.value = 'public'
  }
  syncUrl()
  await load()
  mounted.value = true
})

/** 正在按地址栏回填筛选：这一轮别再把状态写回地址栏，也别把页码归 1。 */
let fromUrl = false

watch([scope, rule, gameFilter], () => {
  if (!mounted.value || fromUrl) return
  page.value = 1
  syncUrl()
  void load()
})

/**
 * 前进后退（或有人直接改地址栏、从团页带 `?game=` 跳进来）：地址栏是真源，
 * 按它把筛选读回来并重拉。一致就说明这次 query 变化是上面 `syncUrl()` 自己写的，不回填。
 * 游客只有「精选」一档，回填时照样要落回来（与 `onMounted` 同一条闸）。
 */
watch(
  () => route.query,
  () => {
    if (route.name !== 'reports' || !mounted.value) return
    if (sameQuery(toQuery())) return
    fromUrl = true
    const wanted = readScope()
    scope.value = locked(wanted) ? 'featured' : wanted
    rule.value = readQuery('rule_system')
    gameFilter.value = readQuery('game')
    page.value = readPage()
    void nextTick(() => {
      fromUrl = false
    })
    void load()
  },
)

function pickScope(key: ScopeKey): void {
  if (locked(key)) return
  scope.value = key
  if (key === 'featured') gameFilter.value = ''
}

function goPage(next: number): void {
  if (next === page.value || next < 1) return
  page.value = next
  syncUrl()
  void load()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function resetAll(): void {
  rule.value = ''
  gameFilter.value = ''
  scope.value = defaultScope.value
  // 三条筛选都在上面的 watch 里：有任何一条真的变了就会归页、同步地址、重拉，这里不用再补。
}

/** 战报卡的底图 = 该团规则的美术（与首页「留下的故事」同一套取图顺序）。 */
function art(report: ReportListItem): { image: RuleSystemPreset['image'] | null; file: string } {
  const preset = home.presetByName(report.game.rule_system)
  return {
    image: preset ? preset.image : null,
    file:
      preset?.image.card ||
      preset?.image.full ||
      preset?.image.thumb ||
      ruleArtFile(report.game.rule_system),
  }
}

/**
 * 摘要是后端截的 Markdown 原文前 200 字，直接显示会带着 `## ` `> ` 这些记号。
 * 与 `components/ReportEntry.vue`、`HomeView.vue` 同一套朴素清理：**仍然是插值渲染**，
 * 不解析 Markdown、不产出 HTML。
 */
function excerptOf(report: ReportListItem): string {
  return (report.excerpt || '')
    .split('\n')
    .map((line) => line.replace(/^\s*(#{1,6}\s+|>\s?|[-*+]\s+|\d+\.\s+)/, '').trim())
    .filter(Boolean)
    .join(' ')
    .replace(/[*_`]/g, '')
}

/** 分页条上的页码（首尾 + 当前页附近，其余折成省略号）。与招募列表同一段。 */
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

const loginNext = '/auth/login?next=' + encodeURIComponent('/reports')
</script>

<template>
  <div class="rep u-rise">
    <PageHead
      eyebrow="What happened at the table · 战报"
      title="战报"
      lead="一个团结束之后，到场的人各自写下自己那份。每人每团一份，写完还可以回去改。"
    >
      <template #aside>
        <RouterLink v-if="authenticated === true" class="c-textlink" to="/me/reports">
          我写过的战报 →
        </RouterLink>
      </template>
    </PageHead>

    <CNotice v-if="authenticated === false" tone="brand" class="rep__guest">
      你现在看到的是站主精选的几篇。登录后可以看到全部公开战报，以及自己团里「仅同团可见」的那些。
      <template #actions>
        <RouterLink class="c-textlink" :to="loginNext">登录后再看 →</RouterLink>
      </template>
    </CNotice>

    <section class="filters" aria-label="筛选条件">
      <div class="fline">
        <span class="fline__k u-kicker">范围</span>
        <div class="c-chips" role="group" aria-label="按可见范围筛选">
          <CChip
            v-for="option in SCOPES"
            :key="option.key"
            :active="scope === option.key"
            :disabled="locked(option.key)"
            :title="locked(option.key) ? '登录后可用' : undefined"
            @click="pickScope(option.key)"
          >
            {{ option.label }}
          </CChip>
        </div>
      </div>

      <div class="fline">
        <span class="fline__k u-kicker">规则</span>
        <div class="c-chips" role="group" aria-label="按规则系统筛选">
          <CChip :active="rule === ''" @click="rule = ''">全部规则</CChip>
          <CChip
            v-for="preset in rulePresets"
            :key="preset.id"
            :active="rule === preset.name"
            @click="rule = preset.name"
          >
            {{ preset.name }}
          </CChip>
          <CChip :active="rule === OTHER" @click="rule = OTHER">其他</CChip>
        </div>
      </div>

      <div v-if="gameFilter" class="fline">
        <span class="fline__k u-kicker">团</span>
        <div class="c-chips" role="group" aria-label="按团筛选">
          <CChip active @click="gameFilter = ''">只看这一个团 ×</CChip>
        </div>
      </div>
    </section>

    <div class="fbar">
      <p class="u-small fbar__count" aria-live="polite">{{ countText }}</p>
      <CButton variant="ghost" :disabled="!dirty" @click="resetAll">清空筛选</CButton>
    </div>

    <p class="u-small rep__desc">
      {{ scopeDesc }}
      <span v-if="authenticated === false">未登录时只有「精选」可用。</span>
    </p>

    <LoadState
      :loading="loading"
      :error="error"
      :empty="!items.length"
      empty-title="这里暂时没有战报"
      :empty-text="emptyText"
    >
      <template #empty-actions>
        <CButton v-if="dirty" variant="ghost" @click="resetAll">清空筛选</CButton>
        <RouterLink class="c-textlink" to="/recruit">先去找个团 →</RouterLink>
      </template>

      <div class="rgrid">
        <RouterLink
          v-for="report in items"
          :key="report.id"
          class="rcard"
          :to="'/reports/' + report.id"
        >
          <BlurStage
            class="rcard__art"
            :image="art(report).image"
            :file="art(report).file"
            :rule="report.game.rule_system"
            size="card"
            tone="dark"
            :inset="10"
            alt=""
          >
            <span v-if="report.game.rule_system" class="rcard__corner">
              <span class="c-tag c-tag--dark">{{ report.game.rule_system }}</span>
            </span>
          </BlurStage>

          <span class="rcard__body">
            <span class="rcard__title u-h-card">{{ report.title }}</span>
            <span v-if="excerptOf(report)" class="rcard__excerpt">{{ excerptOf(report) }}</span>
            <span class="rcard__foot">
              <span class="rcard__who">
                <img
                  v-if="report.author.avatar"
                  class="rcard__face"
                  :src="report.author.avatar"
                  alt=""
                />
                <span v-else class="rcard__face rcard__face--blank" aria-hidden="true"></span>
                <span>{{ report.author.nickname }}</span>
              </span>
              <span class="rcard__from">{{ report.game.title }}</span>
              <span class="rcard__date">{{ formatDate(report.created_at) }}</span>
              <span v-if="report.is_featured" class="c-tag c-tag--seal">精选</span>
              <span v-if="report.visibility === 'same_game'" class="c-tag c-tag--mute">
                仅同团可见
              </span>
              <span v-if="report.attachment_count" class="rcard__date">
                附件 {{ report.attachment_count }}
              </span>
            </span>
          </span>
        </RouterLink>
      </div>

      <nav v-if="totalPages > 1" class="pager" aria-label="分页">
        <button class="pager__btn" type="button" :disabled="page <= 1" @click="goPage(page - 1)">
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
        <button
          class="pager__btn"
          type="button"
          :disabled="page >= totalPages"
          @click="goPage(page + 1)"
        >
          下一页
        </button>
      </nav>
    </LoadState>

    <div class="rep__foot">
      <span class="u-small">列表一页 {{ PAGE_SIZE }} 篇，按发布时间从新到旧。</span>
      <RouterLink v-if="authenticated === true" class="c-textlink" to="/me/reports">
        写下我的战报 →
      </RouterLink>
      <RouterLink v-else class="c-textlink" to="/auth/signup">注册账号 →</RouterLink>
    </div>
  </div>
</template>

<style scoped>
/* ==========================================================================
   筛选条（沿用招募列表那一套，两页看起来必须是同一件东西）
   ========================================================================== */

.rep__guest {
  margin-top: var(--sp-4);
}

.filters {
  display: grid;
  gap: var(--sp-4);
  margin-top: var(--sp-5);
}

.fline {
  display: grid;
  gap: var(--sp-2);
  align-items: start;
}

.fbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3) var(--sp-5);
  margin-top: var(--sp-5);
  padding: var(--sp-3) var(--sp-4);
  background: var(--bg-2);
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}

.fbar__count {
  flex: 1 1 16em;
  margin: 0;
}

.rep__desc {
  margin: var(--sp-3) 0 0;
}

/* 锁住的范围档（游客的「全部 / 我参加的团」）：v2 reports.html `.tabs .locked`。
   `.c-chip:disabled` 已收进 base.css（2026-09-22），本页不再覆盖。 */

/* ==========================================================================
   战报卡（v2 reports.html `.rcard`：左图右文，图是同图虚化铺底）
   ========================================================================== */

.rgrid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-4);
  margin-top: var(--sp-5);
}

.rcard {
  display: grid;
  grid-template-columns: 108px minmax(0, 1fr);
  gap: var(--sp-4);
  align-content: start;
  padding: var(--sp-4);
  color: inherit;
  text-decoration: none;
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}

.rcard:hover {
  border-color: var(--line-2);
  box-shadow: var(--shadow-1);
}

.rcard__art {
  position: relative;
  min-height: 96px;
  border-radius: var(--radius);
}

.rcard__corner {
  position: absolute;
  top: var(--sp-2);
  left: var(--sp-2);
  display: flex;
  gap: var(--sp-1);
  /** 业务界面遵循后端权限与隐私约束。 */
  max-width: calc(100% - 2 * var(--sp-2));
}

.rcard__corner .c-tag {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rcard__body {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.rcard__title {
  font-size: var(--fs-lg);
  line-height: var(--lh-card);
  letter-spacing: -0.01em;
  /** 业务界面遵循后端权限与隐私约束。 */
  overflow-wrap: anywhere;
}

.rcard__excerpt {
  margin-top: var(--sp-2);
  font-size: var(--fs-sm);
  line-height: var(--lh-read);
  color: var(--ink-muted);
  /* 三行截断；v2 手机上收成两行 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.rcard__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-4);
  margin-top: auto;
  padding-top: var(--sp-3);
}

.rcard__who {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--ink-soft);
}

.rcard__face {
  width: 22px;
  height: 22px;
  object-fit: cover;
  border-radius: var(--radius-pill);
  background: var(--avatar-bg);
}

.rcard__face--blank {
  display: inline-block;
}

.rcard__from {
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-muted);
  /** 业务界面遵循后端权限与隐私约束。 */
  overflow-wrap: anywhere;
}

.rcard__date {
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-faint);
}

/* ==========================================================================
   分页（v2 reports.html `.pager`）
   ========================================================================== */

.pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-6);
  padding-top: var(--sp-5);
  border-top: 1px solid var(--line);
}

.pager__btn {
  min-width: 44px;
  min-height: 44px;
  padding: 0 var(--sp-3);
  font-size: var(--fs-sm);
  color: var(--ink-soft);
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  cursor: pointer;
}

.pager__btn:disabled {
  color: var(--ink-faint);
  background: transparent;
  cursor: not-allowed;
}

.pager__btn--now {
  color: var(--on-brand);
  background: var(--brand);
  border-color: var(--brand);
}

.pager__gap {
  padding: 0 var(--sp-1);
  color: var(--ink-faint);
}

.rep__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2) var(--sp-4);
  margin-top: var(--sp-6);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--line);
}

/* ==========================================================================
   ≥768：筛选名与筹码并排；卡片图变大
   ========================================================================== */

@media (min-width: 768px) {
  .fline {
    grid-template-columns: 4.5em minmax(0, 1fr);
    gap: var(--sp-4);
  }

  .fline__k {
    padding-top: 10px;
  }

  .rcard {
    grid-template-columns: 152px minmax(0, 1fr);
    gap: var(--sp-5);
  }

  .rcard__art {
    aspect-ratio: 4 / 3;
    min-height: 0;
  }

  .rcard__excerpt {
    -webkit-line-clamp: 3;
    line-clamp: 3;
  }
}

/* ≥1200：两栏网格（v2 是 1000px 起两栏，这里并到本站断点） */
@media (min-width: 1200px) {
  .rgrid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
