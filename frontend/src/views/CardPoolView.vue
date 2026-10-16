<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import BtnLink from '../components/BtnLink.vue'
import CButton from '../components/CButton.vue'
import CChip from '../components/CChip.vue'
import CNotice from '../components/CNotice.vue'
import CPill from '../components/CPill.vue'
import LoadState from '../components/LoadState.vue'
import PageHead from '../components/PageHead.vue'
import { fetchCardPool, type CardStatus, type PublicCard } from '../api/cards'
import type { RuleSystemPreset } from '../api/home'
import { errorStatus, errorText } from '../lib/api-error'
import { formatDate } from '../lib/datetime'
import {
  cardArt,
  CARD_SORT_DEFAULT,
  CARD_SORT_OPTIONS,
  CARD_STATUS_OPTIONS,
  type CardSort,
} from '../lib/card-display'
import { useAuthStore } from '../stores/auth'
import { useHomeStore } from '../stores/home'
import { useSiteStore } from '../stores/site'

/** 「其他」哨兵：后端 `apps/siteconfig/services.OTHER_SENTINEL`，**大小写敏感**。 */
const OTHER = '__other__'

/** 后端 `common/pagination.py:StandardPagination.page_size`。 */
const PAGE_SIZE = 20

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const home = useHomeStore()
const site = useSiteStore()
const { authenticated } = storeToRefs(auth)
const { config } = storeToRefs(site)

function readQuery(key: string): string {
  const value = route.query[key]
  return typeof value === 'string' ? value : ''
}

function readSort(): CardSort {
  const raw = readQuery('sort')
  return CARD_SORT_OPTIONS.some((o) => o.value === raw) ? (raw as CardSort) : CARD_SORT_DEFAULT
}

function readPage(): number {
  const n = Number(readQuery('page'))
  return Number.isInteger(n) && n > 0 ? n : 1
}

function readStatus(): CardStatus | '' {
  const raw = readQuery('status')
  return raw === 'alive' || raw === 'torn' ? raw : ''
}

// —— 筛选状态：初值一律从地址栏读，之后再写回地址栏 ——
const ruleSystem = ref(readQuery('rule_system'))
const status = ref<CardStatus | ''>(readStatus())
const sort = ref<CardSort>(readSort())
const owner = ref(readQuery('owner'))
const page = ref(readPage())

const cards = ref<PublicCard[]>([])
const count = ref(0)
const hasNext = ref(false)
const loading = ref(true)
const error = ref('')

/** 规则筹码：站长内容接口的预设优先，拿不到退回 `siteconfig.rule_system_presets`。 */
const rulePresets = computed<{ id: string; name: string }[]>(() => {
  const fromHome = home.rulePresets as RuleSystemPreset[]
  if (fromHome.length) return fromHome.map((p) => ({ id: 'p' + p.id, name: p.name }))
  return (config.value.rule_system_presets ?? []).map((name) => ({ id: name, name }))
})

/** 地址栏里的规则名不在站级预设里时（站主删过预设、或卡主填了自定义规则名）临时补一枚筹码， */
const strayRule = computed(() => {
  const value = ruleSystem.value
  if (!value || value === OTHER) return ''
  return rulePresets.value.some((p) => p.name.toLowerCase() === value.toLowerCase()) ? '' : value
})

const totalPages = computed(() => Math.max(1, Math.ceil(count.value / PAGE_SIZE)))

const dirty = computed(
  () => Boolean(ruleSystem.value || status.value || owner.value) || sort.value !== CARD_SORT_DEFAULT,
)

/**
 * 按卡主筛选时的提示条。昵称只能从返回的卡里取 —— 卡池接口不回传被筛的那个人是谁，
 * 这一页一张卡都没有时就只说「这个人」，不瞎编名字。
 */
const ownerName = computed(() => (owner.value ? (cards.value[0]?.owner.nickname ?? '') : ''))

const countText = computed(() => {
  const parts = ['共 ' + count.value + ' 张公开卡']
  if (totalPages.value > 1) parts.push('第 ' + page.value + ' / ' + totalPages.value + ' 页')
  return parts.join(' · ')
})

const emptyText = computed(() =>
  owner.value
    ? 'TA 还没有公开任何角色卡，或者这个条件下一张都没有。'
    : '这个条件下没有公开的角色卡。换个规则，或把状态放回「全部」。',
)

const loginNext = computed(() => '/auth/login?next=' + encodeURIComponent(route.fullPath))

/** 当前筛选对应的地址栏 query（地址栏是这一页的真源）。 */
function toQuery(): Record<string, string> {
  const q: Record<string, string> = {}
  if (ruleSystem.value) q.rule_system = ruleSystem.value
  if (status.value) q.status = status.value
  if (owner.value) q.owner = owner.value
  if (sort.value !== CARD_SORT_DEFAULT) q.sort = sort.value
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
    const data = await fetchCardPool({
      rule_system: ruleSystem.value,
      status: status.value,
      owner: owner.value || undefined,
      ordering: sort.value === 'plays' ? 'plays' : '',
      page: page.value,
    })
    cards.value = data.results
    count.value = data.count
    hasNext.value = Boolean(data.next)
  } catch (e) {
    // 页码越界（缺陷 F13）：后端越界回 404 not_found 且不带 count，真没卡是 200 count:0。
    // 取「回第一页」而不是「保留旧计数」：直接打开 `?page=999`（旧链接、卡被删后页数变少）时
    // 本页根本没有旧计数可保留，只会停在一张空页上；回第一页能给出真实计数和内容。
    // 只在 page > 1 时这样做，第一页的 404 仍按读取失败处理，不会循环。
    if (errorStatus(e) === 404 && page.value > 1) {
      page.value = 1
      syncUrl()
      await load()
      return
    }
    error.value = errorText(e, '卡池暂时无法读取，请刷新后重试。')
    cards.value = []
    count.value = 0
    hasNext.value = false
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  // 规则筹码的两个来源都不阻断列表：拿不到就各自用兜底继续渲染。
  void site.load()
  void home.load(authenticated.value)
  await load()
})

/** 正在按地址栏回填筛选：这一轮别再把状态写回地址栏，也别把页码归 1。 */
let fromUrl = false

watch([ruleSystem, status, sort], () => {
  if (fromUrl) return
  page.value = 1
  syncUrl()
  void load()
})

/**
 * 前进后退（或有人直接改地址栏、从个人空间带 `?owner=` 跳进来）：地址栏是真源，
 * 按它把筛选读回来并重拉。一致就说明这次 query 变化是上面 `syncUrl()` 自己写的，不回填。
 */
watch(
  () => route.query,
  () => {
    if (route.name !== 'cards') return
    if (sameQuery(toQuery())) return
    fromUrl = true
    ruleSystem.value = readQuery('rule_system')
    status.value = readStatus()
    sort.value = readSort()
    owner.value = readQuery('owner')
    page.value = readPage()
    void nextTick(() => {
      fromUrl = false
    })
    void load()
  },
)

/** 业务界面遵循后端权限与隐私约束。 */
function goPage(next: number): void {
  if (next === page.value || next < 1) return
  page.value = next
  syncUrl()
  void load()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

/** 提示条上的「看全部卡」：只去掉卡主这一条筛选，其余保持原样。 */
function clearOwner(): void {
  owner.value = ''
  page.value = 1
  syncUrl()
  void load()
}

function resetAll(): void {
  sort.value = CARD_SORT_DEFAULT
  owner.value = ''
  ruleSystem.value = ''
  status.value = ''
  // 卡主筛选不在上面的 watch 里（例如只开着 `?owner=`），这里补一次地址同步
  syncUrl()
}

/** 分页条页码：首尾 + 当前页附近，其余折成省略号。 */
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

function art(card: PublicCard) {
  return cardArt(home.presetByName(card.rule_system), card.rule_system)
}
</script>

<template>
  <div class="pool u-rise">
    <PageHead
      eyebrow="Character pool · 角色卡池"
      title="角色卡池"
      lead="公开的角色卡对所有人可见：卡名、规则、参团次数和跑过的团谁都能看。源文件只发给登录成员。设为私密的卡不会出现在这里，卡主自己在「我的角色卡」里管理。"
    >
      <template #aside>
        <BtnLink v-if="authenticated === true" variant="ghost" to="/me/cards">
          我的角色卡 →
        </BtnLink>
        <RouterLink v-else-if="authenticated === false" class="c-textlink" :to="loginNext">
          登录后可下载源文件 →
        </RouterLink>
      </template>
    </PageHead>

    <CNotice v-if="owner" tone="brand" class="pool__owner">
      <!-- 昵称单独隔离进 <bdi>：防 U+202E 之类方向控制符把后面的静态文案一起倒过来（缺陷 F10） -->
      正在看<template v-if="ownerName"> <bdi>{{ ownerName }}</bdi> </template><template v-else>这个人</template>的公开角色卡。
      <template #actions>
        <CButton variant="text" @click="clearOwner">看全部卡 →</CButton>
      </template>
    </CNotice>

    <section class="filters" aria-label="筛选条件">
      <div class="filters__grid">
        <div class="fline">
          <span class="fline__k u-kicker">规则</span>
          <div class="c-chips" role="group" aria-label="按规则筛选">
            <CChip :active="ruleSystem === ''" @click="ruleSystem = ''">全部</CChip>
            <CChip
              v-for="preset in rulePresets"
              :key="preset.id"
              :active="ruleSystem === preset.name"
              @click="ruleSystem = preset.name"
            >
              {{ preset.name }}
            </CChip>
            <CChip :active="ruleSystem === OTHER" @click="ruleSystem = OTHER">其他</CChip>
            <CChip v-if="strayRule" active @click="ruleSystem = ''">{{ strayRule }}</CChip>
          </div>
        </div>

        <div class="fline">
          <span class="fline__k u-kicker">状态</span>
          <div class="c-chips" role="group" aria-label="按状态筛选">
            <!-- 文案照抄后端 STATUS_CHOICES（lib/card-display.ts），与卡上的 status_display 一致 -->
            <CChip
              v-for="option in CARD_STATUS_OPTIONS"
              :key="option.value || 'all'"
              :active="status === option.value"
              @click="status = option.value"
            >
              {{ option.label }}
            </CChip>
          </div>
        </div>

        <div class="fline">
          <span class="fline__k u-kicker">排序</span>
          <div class="c-chips" role="group" aria-label="排序方式">
            <CChip
              v-for="option in CARD_SORT_OPTIONS"
              :key="option.value"
              :active="sort === option.value"
              @click="sort = option.value"
            >
              {{ option.label }}
            </CChip>
          </div>
        </div>
      </div>
    </section>

    <div class="fbar">
      <p class="u-small fbar__count" aria-live="polite">{{ countText }}</p>
      <CButton variant="ghost" :disabled="!dirty" @click="resetAll">清空筛选</CButton>
    </div>

    <CNotice v-if="authenticated === false" tone="brand" class="pool__guest">
      卡的名称、规则、参团次数和跑过的团谁都能看；源文件只发给登录成员，下载不会通知卡主。
      <template #actions>
        <RouterLink class="c-textlink" :to="loginNext">登录后下载 →</RouterLink>
      </template>
    </CNotice>

    <LoadState
      :loading="loading"
      :error="error"
      :empty="!cards.length"
      empty-title="这里还没有卡"
      :empty-text="emptyText"
    >
      <template #empty-actions>
        <CButton v-if="dirty" variant="ghost" @click="resetAll">清空筛选</CButton>
        <RouterLink v-if="authenticated === true" class="c-textlink" to="/me/cards">
          建一张自己的卡 →
        </RouterLink>
      </template>

      <div class="grid">
        <article
          v-for="card in cards"
          :key="card.id"
          class="ccard"
          :class="{ 'ccard--torn': card.status === 'torn' }"
        >
          <img class="ccard__img" :src="art(card).file" alt="" loading="lazy" decoding="async" />
          <span class="c-tag c-tag--dark ccard__corner">
            {{ card.rule_system || '未填规则' }}
          </span>

          <RouterLink class="ccard__link" :to="'/cards/' + card.id">
            <span class="ccard__cap">
              <small>角色卡</small>
              <span class="ccard__name">{{ card.name }}</span>
              <span class="ccard__meta">
                <span>参团 {{ card.play_count }} 次</span>
                <span>建于 {{ formatDate(card.created_at) }}</span>
              </span>
              <span class="ccard__who">
                <img v-if="card.owner.avatar" class="ccard__face" :src="card.owner.avatar" alt="" />
                <span v-else class="ccard__face ccard__face--blank" aria-hidden="true"></span>
                <span>{{ card.owner.nickname }}</span>
              </span>
            </span>
          </RouterLink>

          <div class="ccard__foot">
            <CPill :tone="card.status === 'torn' ? 'off' : 'ok'">{{ card.status_display }}</CPill>
            <!-- 下载链接是后端下发的同源鉴权路径（download_url 只有 can_download 为真时非空） -->
            <a
              v-if="card.can_download && card.download_url"
              class="ccard__dl"
              :href="card.download_url"
            >
              <AppIcon name="download" :size="16" />
              下载源文件
            </a>
            <RouterLink
              v-else-if="card.has_file && authenticated === false"
              class="ccard__dl"
              :to="loginNext"
            >
              登录后下载
            </RouterLink>
            <span v-else-if="!card.has_file" class="u-small ccard__nofile">还没传文件</span>
          </div>
        </article>
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
        <button class="pager__btn" type="button" :disabled="!hasNext" @click="goPage(page + 1)">
          下一页
        </button>
      </nav>
    </LoadState>

    <div class="pool__foot">
      <span class="u-small">
        卡池一页 {{ PAGE_SIZE }} 张，默认按建卡时间倒序。撕卡的卡仍然能下载，但不能再用于报名。
      </span>
      <RouterLink v-if="authenticated === true" class="c-textlink" to="/me/cards">
        管理我的角色卡 →
      </RouterLink>
      <RouterLink v-else-if="authenticated === false" class="c-textlink" to="/auth/signup">
        注册账号 →
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
/** 业务界面遵循后端权限与隐私约束。 */

.pool__owner,
.pool__guest {
  margin-bottom: var(--sp-4);
}

.filters__grid {
  display: grid;
  gap: var(--sp-4);
}

.fline {
  display: grid;
  gap: var(--sp-2);
  align-items: start;
}

.fline__k {
  padding-top: 0;
}

.fbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3) var(--sp-5);
  margin: var(--sp-5) 0 var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  background: var(--bg-2);
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}

.fbar__count {
  flex: 1 1 16em;
  margin: 0;
}

/* ==========================================================================
   卡网格（v2 cards.html .card-grid .pic-card）
   ========================================================================== */

.grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-4);
  margin-top: var(--sp-5);
}

.ccard {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 240px;
  overflow: hidden;
  background: var(--stage-bg);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  color: var(--on-dark);
  transition: box-shadow var(--dur) var(--ease);
}

.ccard:hover {
  box-shadow: var(--shadow-1);
}

.ccard__img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* 撕卡：把美术压灰一档（v2 `.card-grid .pic-card.torn img`） */
.ccard--torn .ccard__img {
  filter: saturate(0.55) contrast(0.95);
}

.ccard__corner {
  position: absolute;
  top: var(--sp-3);
  left: var(--sp-3);
  z-index: 1;
  /** 业务界面遵循后端权限与隐私约束。 */
  max-width: calc(100% - 2 * var(--sp-3));
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 图上那一整块是链接：整张卡可点，动作条另算（嵌套交互元素是无效 HTML） */
.ccard__link {
  position: relative;
  z-index: 1;
  display: flex;
  flex: 1 1 auto;
  align-items: flex-end;
  min-height: 190px;
  color: inherit;
  text-decoration: none;
}

.ccard__cap {
  display: block;
  width: 100%;
  padding: var(--sp-8) var(--sp-5) var(--sp-4);
  background: linear-gradient(transparent, var(--cap-scrim-1) 38%, var(--cap-scrim-2));
  text-shadow: var(--hero-text-shadow);
}

.ccard__cap small {
  display: block;
  margin-bottom: var(--sp-2);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-wide);
  opacity: 0.9;
}

.ccard__name {
  display: block;
  font-size: var(--fs-2xl);
  line-height: var(--lh-tight);
  /* 卡名最多 60 字（后端 max_length），长名字折行而不是溢出 */
  overflow-wrap: anywhere;
}

.ccard__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-4);
  margin-top: var(--sp-2);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps);
  color: var(--on-dark-2);
}

.ccard__who {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
  font-size: var(--fs-xs);
}

.ccard__face {
  flex: none;
  width: 22px;
  height: 22px;
  object-fit: cover;
  border-radius: var(--radius-pill);
  border: 1px solid var(--glass-line);
  background: var(--avatar-bg);
}

/* 白动作条：状态胶囊（CPill 的配色是给浅底用的，压在图上会糊）+ 下载出口 */
.ccard__foot {
  position: relative;
  z-index: 1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2) var(--sp-3);
  padding: var(--sp-2) var(--sp-4);
  background: var(--white);
  border-top: 1px solid var(--line);
}

.ccard__dl {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  min-height: 40px;
  font-size: var(--fs-sm);
  letter-spacing: var(--ls-caps-sm);
  color: var(--brand-ink);
  text-decoration: none;
}

.ccard__dl:hover {
  text-decoration: underline;
  text-underline-offset: 4px;
}

.ccard__nofile {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
}

/** 业务界面遵循后端权限与隐私约束。 */

.pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  margin-top: var(--sp-6);
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

.pool__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-5);
  margin-top: var(--sp-6);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--line);
}

@media (min-width: 768px) {
  .fline {
    grid-template-columns: 62px minmax(0, 1fr);
    gap: var(--sp-3);
  }

  .fline__k {
    padding-top: var(--sp-2);
  }

  .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .ccard__link {
    min-height: 210px;
  }
}

@media (min-width: 1200px) {
  .filters__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    column-gap: var(--sp-8);
  }

  .grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (min-width: 1921px) {
  .grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: var(--sp-5);
  }
}

/* 2251+ 版心被 --pad 收到 1080：四列会把每张卡压到 255px，卡名与名牌挤成两字一行。
   与首页横轨、招募网格同一档位（1921+ 四张、2251+ 三张）。 */
@media (min-width: 2251px) {
  .grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
