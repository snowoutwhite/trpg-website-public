<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import BlurStage from '../components/BlurStage.vue'
import BtnLink from '../components/BtnLink.vue'
import CChip from '../components/CChip.vue'
import CEmpty from '../components/CEmpty.vue'
import CNotice from '../components/CNotice.vue'
import SectionHead from '../components/SectionHead.vue'
import type { FeaturedPhoto, QuickEntry, RuleSystemPreset } from '../api/home'
import { fetchGames, type GameListItem } from '../api/games'
import { fetchFeaturedReports, type ReportListItem } from '../api/reports'
import { CONFIG_MAX, PRESET_MAX, QUICK_MAX } from '../api/homeAdmin'
import AnnouncementPanel from '../components/edit/AnnouncementPanel.vue'
import EditableChoice from '../components/edit/EditableChoice.vue'
import EditableImage from '../components/edit/EditableImage.vue'
import EditableText from '../components/edit/EditableText.vue'
import FeaturedPhotosPanel from '../components/edit/FeaturedPhotosPanel.vue'
import { errorText } from '../lib/api-error'
import { formatDate, formatDateTime } from '../lib/datetime'
import { loadTodoCards, type TodoCard } from '../lib/todos'
import { ruleArtFile } from '../lib/rule-art'
import { safeExternalUrl, safeNextPath } from '../lib/url-guard'
import { useAuthStore } from '../stores/auth'
import { useEditStore } from '../stores/edit'
import { useHomeStore } from '../stores/home'
import { useSiteStore } from '../stores/site'

const site = useSiteStore()
const home = useHomeStore()
const auth = useAuthStore()
const edit = useEditStore()
const { config } = storeToRefs(site)
const { authenticated, user, isGm } = storeToRefs(auth)
const { rulePresets, quickEntries, announcement, featuredPhotos } = storeToRefs(home)

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

// ==========================================================================
// 1. 首屏规则轮播
// ==========================================================================

/** 自动播的节拍。`prefers-reduced-motion` 下根本不起这个定时器。 */
const HERO_INTERVAL = 7000

/**
 * 首屏的帧 = **站主配好文案的**规则预设（v2：「幻灯 = 站级 rule_system_presets ∩
 * 站主配好的素材」）。没配文案的预设仍然是全站分类轴的一档 —— 它出现在下面的规则筹码里，
 * 只是不该在首屏画一帧「有图没字」的幻灯。
 */
const heroSlides = computed<RuleSystemPreset[]>(() =>
  // 编辑态列出**全部**预设：标题与眼标都空着的那些正是站主要来填的，
  // 按普通态的过滤条件它们连一帧都没有，就永远填不上（`sort` 与新建仍在 Django 后台）。
  edit.active
    ? rulePresets.value
    : rulePresets.value.filter((p) => Boolean(p.title || p.kicker)),
)
const heroIndex = ref(0)
const currentSlide = computed<RuleSystemPreset | null>(
  () => heroSlides.value[heroIndex.value] ?? null,
)
const heroCounter = computed(
  () => pad2(heroIndex.value + 1) + ' / ' + pad2(heroSlides.value.length),
)

/**
 * 当前帧的明暗，决定遮罩强度（`.hero[data-tone="dark"]` 那组变量）。
 * 编辑态读草稿值，站主一改下拉框遮罩就跟着变 —— 否则「这张图该配哪档遮罩」得先保存才看得出来。
 */
const heroTone = computed<'light' | 'dark'>(() => {
  const slide = currentSlide.value
  if (!slide) return 'light'
  const value = edit.active ? edit.presetValue(slide.id, 'tone') : slide.tone
  return value === 'dark' ? 'dark' : 'light'
})

/** 取一帧的图：后端三档优先（首屏用 full），没配图回落本地规则美术。 */
function slideImage(preset: RuleSystemPreset): string {
  return (
    preset.image.full ||
    preset.image.card ||
    preset.image.thumb ||
    ruleArtFile(preset.name)
  )
}

let heroTimer: number | undefined

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
}

function stopAuto(): void {
  if (heroTimer !== undefined) {
    window.clearInterval(heroTimer)
    heroTimer = undefined
  }
}

/**
 * 起自动播。`prefers-reduced-motion: reduce` 下不播（全局也已关掉过渡动画）。
 * **编辑态也不播**：正在往某一帧的输入框里打字时画面自己翻页是最糟的交互。
 */
function startAuto(): void {
  stopAuto()
  if (edit.active || prefersReducedMotion() || heroSlides.value.length < 2) return
  heroTimer = window.setInterval(() => {
    heroIndex.value = (heroIndex.value + 1) % heroSlides.value.length
  }, HERO_INTERVAL)
}

function goSlide(n: number): void {
  const total = heroSlides.value.length
  if (!total) return
  heroIndex.value = ((n % total) + total) % total
  // 手动切过就把自动播的节拍重新起算，免得刚点完就被定时器抢走
  startAuto()
}

/** 触摸/指针滑动：位移超过 40px 才算一次翻页（v2 同阈值）。 */
let swipeFrom: number | null = null
function onHeroDown(event: PointerEvent): void {
  swipeFrom = event.clientX
}
function onHeroUp(event: PointerEvent): void {
  if (swipeFrom === null) return
  const dx = event.clientX - swipeFrom
  swipeFrom = null
  if (Math.abs(dx) > 40) goSlide(heroIndex.value + (dx < 0 ? 1 : -1))
}

// 预设是异步来的：条数变了要把游标收回合法范围
watch(
  () => heroSlides.value.length,
  (total) => {
    if (heroIndex.value >= total) heroIndex.value = 0
    startAuto()
  },
)

/** 「快速开始 ↓」：滚到快速选择那段。用滚动而不是 `#start` 锚点，免得往历史里塞一条哈希。 */
function toQuick(): void {
  document.getElementById('start')?.scrollIntoView({ block: 'start' })
}

// ---- 「了解该规则」覆盖层 ----

const ruleOpen = ref(false)
const ruleBackBtn = ref<HTMLButtonElement | null>(null)
const learnBtn = ref<HTMLButtonElement | null>(null)

/** 覆盖层/灯箱打开时锁住背景滚动。不新增全局类名，直接改行内样式并在关闭时还原。 */
function lockScroll(on: boolean): void {
  document.body.style.overflow = on ? 'hidden' : ''
}

function openRule(): void {
  if (!currentSlide.value) return
  ruleOpen.value = true
  stopAuto()
  lockScroll(true)
  void nextTick(() => ruleBackBtn.value?.focus({ preventScroll: true }))
}

/** aria-modal 的另一半：Tab 在对话框内循环，不逃到页脚/顶栏（复检 2026-09-22 走查发现第 4 次 Tab 逃出） */
function trapFocus(event: KeyboardEvent): void {
  if (event.key !== 'Tab') return
  const root = event.currentTarget as HTMLElement | null
  if (!root) return
  const focusables = Array.from(
    root.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'),
  ).filter((el) => el.offsetParent !== null)
  if (focusables.length === 0) return
  const first = focusables[0]!
  const last = focusables[focusables.length - 1]!
  const active = document.activeElement
  if (event.shiftKey && (active === first || !root.contains(active))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (active === last || !root.contains(active))) {
    event.preventDefault()
    first.focus()
  }
}

function closeRule(): void {
  ruleOpen.value = false
  lockScroll(false)
  startAuto()
  learnBtn.value?.focus({ preventScroll: true })
}

/** 覆盖层里的两个站内去向：规则名进 query，由 `/recruit`、`/cards` 自己按它筛。 */
function ruleQuery(path: string, name: string): string {
  return path + '?rule_system=' + encodeURIComponent(name)
}

// ==========================================================================
// 2. 站长公告
// ==========================================================================

/** `is_read === true` 的公告整条不显示（本人已经点过「知道了」）。 */
const showAnnouncement = computed(() => Boolean(announcement.value) && announcement.value?.is_read !== true)
/** 只有「本人确实收到了那条通知且还没读」才给「知道了」；游客与 `null` 一律不给。 */
const canDismiss = computed(() => announcement.value?.is_read === false)

// ==========================================================================
// 3. 快速选择 + 我的当下
// ==========================================================================

const quickIndex = ref(0)
const quickCurrent = computed<QuickEntry | null>(() => quickEntries.value[quickIndex.value] ?? null)

function pickQuick(n: number): void {
  const total = quickEntries.value.length
  if (!total) return
  quickIndex.value = ((n % total) + total) % total
}

watch(
  () => quickEntries.value.length,
  (total) => {
    if (quickIndex.value >= total) quickIndex.value = 0
  },
)

/**
 * 六个入口的去向。后端 `QuickEntry.route` 的校验器只收站内路由（`models.validate_internal_route`），
 * 这里**再过一遍** `safeNextPath`：值来自后端可写字段，多一道纯函数的代价几乎为零，
 * 而一个 `//evil.example` 落进 `<RouterLink to>` 就是一次开放重定向。
 */
function quickTo(entry: QuickEntry): string {
  return safeNextPath(entry.route, '/')
}

const todos = ref<TodoCard[]>([])
/** 待办是多个接口拼出来的，登录态一变就重拼；用世代号丢弃过期结果。 */
let todoGen = 0

/** 业务界面遵循后端权限与隐私约束。 */
async function loadTodos(): Promise<void> {
  const gen = ++todoGen
  if (authenticated.value !== true) {
    todos.value = []
    return
  }
  const cards = await loadTodoCards({
    isGm: isGm.value,
    userId: user.value?.id ?? null,
    galleryUploadWindowDays: config.value.gallery_upload_window_days,
  })
  if (gen === todoGen) todos.value = cards
}

// ==========================================================================
// 4. 正在招募
// ==========================================================================

/** 「其他」筛选的哨兵（后端 `apps/siteconfig/services.OTHER_SENTINEL`，大小写敏感）。 */
const OTHER = '__other__'
/** 横轨最多几张卡。再多也滚不完，翻页交给 `/recruit`。 */
const TRACK_LIMIT = 12

const ruleFilter = ref('')
const games = ref<GameListItem[]>([])
const gamesLoading = ref(true)
const gamesError = ref('')
/** 招募中的总数（可报名）与「招募中 + 报名已满」的总数，给筛选条右边那行小字。 */
const recruitingCount = ref(0)
const openCount = ref(0)

/**
 * 两个状态各拉一次再并起来。
 *
 * 为什么不一次拉全部状态：`?status=` 只收**单个**值，而 `ordering=start_at` 是升序 ——
 * 不带状态过滤时最先回来的是开团时间最早的那批（也就是早就结团/取消的团），
 * 第一页很可能一个在招的团都没有。所以按状态各取一页，再按开团时间合并。
 * （v2 稿的横轨里还有「进行中」的团，那是静态示例；进行中已经开不了新座位，
 *   本段标题是「正在招募的团」，只留招募中与报名已满两档。）
 */
async function loadGames(): Promise<void> {
  gamesLoading.value = true
  gamesError.value = ''
  const shared = {
    rule_system: ruleFilter.value,
    ordering: 'start_at' as const,
    page_size: TRACK_LIMIT,
  }
  try {
    const [open, full] = await Promise.all([
      fetchGames({ ...shared, status: 'recruiting' }),
      fetchGames({ ...shared, status: 'closed_signup' }),
    ])
    recruitingCount.value = open.count
    openCount.value = open.count + full.count
    games.value = [...open.results, ...full.results]
      .sort((a, b) => new Date(a.start_at).getTime() - new Date(b.start_at).getTime())
      .slice(0, TRACK_LIMIT)
  } catch (e) {
    gamesError.value = errorText(e, '正在招募的团暂时无法读取，请刷新后重试。')
    games.value = []
    recruitingCount.value = 0
    openCount.value = 0
  } finally {
    gamesLoading.value = false
  }
}

watch(ruleFilter, () => void loadGames())

/** 团卡的图：先找同名规则预设的 card 档，没有就回落本地规则美术。 */
function gameArt(game: GameListItem): { image: RuleSystemPreset['image'] | null; file: string } {
  const preset = home.presetByName(game.rule_system)
  return {
    image: preset ? preset.image : null,
    file:
      preset?.image.card ||
      preset?.image.full ||
      preset?.image.thumb ||
      ruleArtFile(game.rule_system),
  }
}

/** 卡面那行事实。文案一律用后端的 `*_display`，前端不建中文映射表。 */
function gameMeta(game: GameListItem): string[] {
  const meta = [
    formatDateTime(game.start_at),
    game.mode_display,
    game.occupied_seats + ' / ' + game.max_players + ' 人',
    game.signup_mode_display,
  ]
  if (game.min_play_count) meta.push('需团次数 ≥ ' + game.min_play_count)
  if (game.min_level_display) meta.push('需 ' + game.min_level_display)
  if (game.requires_card) meta.push('需交卡')
  return meta
}

const trackEl = ref<HTMLElement | null>(null)
const trackAtEnd = ref(false)

function paintTrack(): void {
  const el = trackEl.value
  if (!el) return
  trackAtEnd.value = el.scrollLeft + el.clientWidth >= el.scrollWidth - 4
}

function scrollTrack(dir: 1 | -1): void {
  const el = trackEl.value
  if (!el) return
  el.scrollBy({ left: dir * Math.round(el.clientWidth * 0.8), behavior: 'smooth' })
}

/** 桌面端也要能「滑」（v2 上手检查 2026-09-23）：横轨是原生 `overflow-x: auto`， */
const DRAG_THRESHOLD = 6
let dragStartX = 0
let dragStartLeft = 0
let dragPointerId = -1
let dragging = false
let dragMoved = false

function onTrackPointerDown(event: PointerEvent): void {
  const el = trackEl.value
  if (!el || event.pointerType !== 'mouse' || event.button !== 0) return
  dragging = true
  dragMoved = false
  dragPointerId = event.pointerId
  dragStartX = event.clientX
  dragStartLeft = el.scrollLeft
}

function onTrackPointerMove(event: PointerEvent): void {
  const el = trackEl.value
  if (!el || !dragging || event.pointerId !== dragPointerId) return
  const dx = event.clientX - dragStartX
  if (!dragMoved) {
    if (Math.abs(dx) < DRAG_THRESHOLD) return
    // 跨过阈值：从这一刻起才算「拖」
    dragMoved = true
    el.classList.add('is-dragging')
    el.setPointerCapture(event.pointerId)
  }
  el.scrollLeft = dragStartLeft - dx
}

function onTrackPointerUp(event: PointerEvent): void {
  const el = trackEl.value
  if (!el || !dragging || event.pointerId !== dragPointerId) return
  dragging = false
  if (el.hasPointerCapture(event.pointerId)) el.releasePointerCapture(event.pointerId)
  // 没拖过就是一次普通点击：什么都不碰，让 click 正常落到卡片链接上
  if (!dragMoved) return
  // 类名晚一帧再摘：先让这次 scrollLeft 落定，再恢复吸附，不然松手瞬间会被吸回起点
  window.setTimeout(() => el.classList.remove('is-dragging'), 0)
}

/** 鼠标按住后移动时，浏览器会对 <a> 与 <img> 发起原生拖拽（拖出一个链接幽灵），会打断横轨拖动。 */
function onTrackDragStart(event: DragEvent): void {
  if (dragging) event.preventDefault()
}

/** 拖过的手势松手时落在卡片上会触发 click，这里把它吃掉。 */
function onTrackClickCapture(event: MouseEvent): void {
  if (!dragMoved) return
  dragMoved = false
  event.preventDefault()
  event.stopPropagation()
}

function onTrackWheel(event: WheelEvent): void {
  const el = trackEl.value
  if (!el || event.ctrlKey) return
  // 触控板横向手势本身带 deltaX，浏览器已经会横滚；只接管「纯竖向」的滚轮
  if (Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return
  const max = el.scrollWidth - el.clientWidth
  if (max <= 0) return
  const toRight = event.deltaY > 0
  if ((toRight && el.scrollLeft >= max - 1) || (!toRight && el.scrollLeft <= 1)) return
  event.preventDefault()
  el.scrollLeft += event.deltaY
}

// ==========================================================================
// 5. 留下的故事 + 活动掠影
// ==========================================================================

const reports = ref<ReportListItem[]>([])
const reportsLoading = ref(true)
const reportsError = ref('')

async function loadReports(): Promise<void> {
  reportsLoading.value = true
  reportsError.value = ''
  try {
    const data = await fetchFeaturedReports({ page: 1 })
    reports.value = data.results.slice(0, 3)
  } catch (e) {
    reportsError.value = errorText(e, '精选战报暂时无法读取，请刷新后重试。')
    reports.value = []
  } finally {
    reportsLoading.value = false
  }
}

/**
 * 摘要是后端截的 Markdown 原文前 200 字，直接显示会带着 `## ` `> ` 这些记号。
 * 与 `components/ReportEntry.vue` 同一套朴素清理：**仍然是插值渲染**，
 * 不解析 Markdown、不产出 HTML（一行摘要不值得拉起 sanitize 那一整套）。
 */
function excerptOf(report: ReportListItem): string {
  return (report.excerpt || '')
    .split('\n')
    .map((line) => line.replace(/^\s*(#{1,6}\s+|>\s?|[-*+]\s+|\d+\.\s+)/, '').trim())
    .filter(Boolean)
    .join(' ')
    .replace(/[*_`]/g, '')
}

/** 战报卡的底图 = 该团规则的美术。 */
function reportArt(report: ReportListItem): string {
  const preset = home.presetByName(report.game.rule_system)
  return (
    preset?.image.card ||
    preset?.image.full ||
    preset?.image.thumb ||
    ruleArtFile(report.game.rule_system)
  )
}

/** 最近开过团的 GM（去重，按横轨里那几个团取）。 */
const recentGms = computed(() => {
  const seen = new Set<number>()
  const out: GameListItem['gm'][] = []
  for (const game of games.value) {
    if (seen.has(game.gm.id)) continue
    seen.add(game.gm.id)
    out.push(game.gm)
  }
  return out.slice(0, 8)
})

/** 精选照片：`visible` 已经把「站级开关 → 可见范围与登录态」两道闸算完了，前端不再推一遍。 */
const photos = computed<FeaturedPhoto[]>(() =>
  featuredPhotos.value?.visible ? featuredPhotos.value.results : [],
)
const photoIndex = ref<number | null>(null)
const openPhoto = computed<FeaturedPhoto | null>(() =>
  photoIndex.value === null ? null : (photos.value[photoIndex.value] ?? null),
)

const lightboxClose = ref<HTMLButtonElement | null>(null)
function showPhoto(i: number): void {
  photoIndex.value = i
  lockScroll(true)
  // 焦点进对话框（与 openRule 同法），关闭后回到触发按钮由浏览器自然处理
  void nextTick(() => lightboxClose.value?.focus({ preventScroll: true }))
}

function closePhoto(): void {
  photoIndex.value = null
  lockScroll(false)
}

// ==========================================================================
// 生命周期
// ==========================================================================

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  if (photoIndex.value !== null) closePhoto()
  else if (ruleOpen.value) closeRule()
}

onMounted(() => {
  void site.load()
  void loadGames()
  void loadReports()
  startAuto()
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', paintTrack)
})

onBeforeUnmount(() => {
  stopAuto()
  lockScroll(false)
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', paintTrack)
})

watch(authenticated, () => void loadTodos(), { immediate: true })
watch(games, () => void nextTick(paintTrack))
// 进编辑态即停自动播，退出再起（`startAuto()` 自己判 `edit.active`）
watch(
  () => edit.active,
  () => startAuto(),
)

// ==========================================================================
// ==========================================================================

/** 文案照后端 `homecontent/models.TONE_CHOICES` 写，不自造第二套说法。 */
const TONE_OPTIONS = [
  { value: 'light', text: '浅色画面（配深色字）' },
  { value: 'dark', text: '深色画面（配浅色字）' },
]

/** 某一格的后端字段级错误；没有就是空串。 */
/** 首屏「更多设置」弹层开在哪一帧（预设 id）；快速选择的「格子上的字」弹层开关。 */
const heroMoreOpen = ref<number | null>(null)
const quickMoreOpen = ref(false)

function presetError(id: number, field: string): string {
  return edit.fieldErrors['preset.' + id + '.' + field] ?? ''
}
function quickError(id: number, field: string): string {
  return edit.fieldErrors['quick.' + id + '.' + field] ?? ''
}
function configError(field: string): string {
  return edit.fieldErrors['config.' + field] ?? ''
}
</script>

<template>
  <div class="home">
    <!-- ============ 1. 首屏：规则轮播 ============ -->
    <section
      v-if="heroSlides.length"
      class="hero"
      :class="{ 'is-editing': edit.active, 'has-panel': heroMoreOpen !== null }"
      data-hero
      :data-tone="heroTone"
      aria-roledescription="轮播"
      aria-label="规则世界"
      @pointerdown="onHeroDown"
      @pointerup="onHeroUp"
    >
      <div class="hero__track" :style="{ transform: 'translateX(-' + heroIndex * 100 + '%)' }">
        <article
          v-for="(slide, i) in heroSlides"
          :key="slide.id"
          class="hero__slide"
          :aria-hidden="i === heroIndex ? undefined : 'true'"
          :inert="i === heroIndex ? undefined : 'true'"
        >
          <img
            class="hero__img"
            :src="slideImage(slide)"
            :alt="slide.image_alt"
            :loading="i === heroIndex ? undefined : 'lazy'"
            :fetchpriority="i === heroIndex ? 'high' : undefined"
            draggable="false"
          />
          <!-- 编辑态：点图换图的覆盖层贴在底图上（文字压在图上，所以只留角上的徽标，不开整图热区） -->
          <EditableImage
            v-if="edit.active"
            kind="preset"
            tone="dark"
            offset-top="calc(var(--header-h, 54px) + var(--sp-2))"
            offset-x="var(--pad)"
            :id="slide.id"
            :label="slide.name + '：首屏底图'"
            :alt="edit.presetValue(slide.id, 'image_alt') ?? ''"
            :alt-max="PRESET_MAX.image_alt"
            @update:alt="edit.setPreset(slide.id, 'image_alt', $event)"
          />
          <!-- 编辑态：这一帧在页面上看不见的两项（规则介绍页用的副标、画面明暗）收进右上角的小弹层，
               与「更换图片」徽标同一角落（块级工具都在块的角上），不再在标题下面堆面板 -->
          <div v-if="edit.active" class="hero__tools">
            <button
              class="hero__morebtn"
              type="button"
              :aria-expanded="heroMoreOpen === slide.id ? 'true' : 'false'"
              @click="heroMoreOpen = heroMoreOpen === slide.id ? null : slide.id"
            >
              {{ heroMoreOpen === slide.id ? '收起' : '更多设置' }}
            </button>
            <div v-if="heroMoreOpen === slide.id" class="hero__morebox">
              <p class="hero__morehead">这一帧在页面上看不见的两项</p>
              <label class="hero__morerow">
                <span class="hero__morelabel">规则介绍页的副标</span>
                <EditableText
                  tone="dark"
                  :value="edit.presetValue(slide.id, 'tagline') ?? ''"
                  :label="slide.name + '：一句副标（规则介绍页用）'"
                  :max="PRESET_MAX.tagline"
                  :error="presetError(slide.id, 'tagline')"
                  @update:value="edit.setPreset(slide.id, 'tagline', $event)"
                />
              </label>
              <EditableChoice
                tone="dark"
                :value="edit.presetValue(slide.id, 'tone') ?? 'dark'"
                :label="slide.name + '：画面明暗（决定遮罩强度）'"
                :options="TONE_OPTIONS"
                :error="presetError(slide.id, 'tone')"
                @update:value="edit.setPreset(slide.id, 'tone', $event as 'light' | 'dark')"
              />
            </div>
          </div>
          <div class="hero__center">
            <template v-if="!edit.active">
              <p v-if="slide.kicker" class="u-kicker hero__kicker">{{ slide.kicker }}</p>
              <!-- 一页只有一个 h1：非当前帧降为 p（复检 2026-09-22：4 帧 4 个 h1 违反约定） -->
              <component :is="i === heroIndex ? 'h1' : 'p'" class="hero__title">{{ slide.title || slide.name }}</component>
              <p v-if="slide.intro.hero" class="hero__copy">{{ slide.intro.hero }}</p>
            </template>
            <!-- 编辑态：同样三行，原位换成描虚线的真实控件（深色底那一套外观） -->
            <template v-else>
              <EditableText
                class="u-kicker hero__kicker"
                tone="dark"
                :value="edit.presetValue(slide.id, 'kicker') ?? ''"
                :label="slide.name + '：首屏眼标'"
                :max="PRESET_MAX.kicker"
                :error="presetError(slide.id, 'kicker')"
                @update:value="edit.setPreset(slide.id, 'kicker', $event)"
              />
              <EditableText
                class="hero__title"
                :as="i === heroIndex ? 'h1' : 'p'"
                tone="dark"
                :value="edit.presetValue(slide.id, 'title') ?? ''"
                :label="slide.name + '：首屏大标题'"
                :max="PRESET_MAX.title"
                :error="presetError(slide.id, 'title')"
                @update:value="edit.setPreset(slide.id, 'title', $event)"
              />
              <EditableText
                class="hero__copy"
                tone="dark"
                multiline
                :rows="2"
                :value="edit.presetValue(slide.id, 'intro_hero') ?? ''"
                :label="slide.name + '：首屏一句话'"
                :max="PRESET_MAX.intro_hero"
                :error="presetError(slide.id, 'intro_hero')"
                @update:value="edit.setPreset(slide.id, 'intro_hero', $event)"
              />
            </template>
            <button class="c-btn c-btn--light hero__start" type="button" @click="toQuick">
              快速开始 <span aria-hidden="true">↓</span>
            </button>
          </div>
        </article>
      </div>

      <template v-if="heroSlides.length > 1">
        <button
          class="hero__turn hero__turn--prev"
          type="button"
          aria-label="上一个规则"
          @click="goSlide(heroIndex - 1)"
        >
          <AppIcon name="back" :size="18" />
        </button>
        <button
          class="hero__turn hero__turn--next"
          type="button"
          aria-label="下一个规则"
          @click="goSlide(heroIndex + 1)"
        >
          <AppIcon name="arrow" :size="18" />
        </button>
      </template>

      <div class="hero__foot">
        <div class="hero__rules" role="group" aria-label="选择规则">
          <button
            v-for="(slide, i) in heroSlides"
            :key="slide.id"
            class="hero__rule"
            type="button"
            :aria-pressed="i === heroIndex ? 'true' : 'false'"
            @click="goSlide(i)"
          >
            {{ slide.name }}
          </button>
        </div>
        <div class="hero__aside">
          <span class="hero__counter" aria-live="polite">{{ heroCounter }}</span>
          <button ref="learnBtn" class="hero__learn" type="button" @click="openRule">
            了解该规则 <span aria-hidden="true">↗</span>
          </button>
        </div>
      </div>
    </section>

    <!-- 站长内容取不到时，首屏不画一块空的深色板，只给一句话 -->
    <section v-else-if="home.error" class="l-section l-section--tight">
      <CNotice tone="warn" title="首页内容暂时无法读取">请刷新后重试；其余栏目不受影响。</CNotice>
    </section>

    <!-- ============ 2. 站长公告横幅（编辑态在同一位置展开成公告面板） ============ -->
    <div v-if="edit.active" class="announce">
      <AnnouncementPanel />
    </div>
    <div v-else-if="showAnnouncement && announcement" class="announce">
      <CNotice
        tone="brand"
        :title="announcement.title"
        :dismissible="canDismiss"
        @dismiss="home.dismissAnnouncement()"
      >
        <p class="announce__body">{{ announcement.body }}</p>
        <p class="announce__at u-small">
          {{ formatDate(announcement.published_at) }} · 站长公告
        </p>
        <template #actions>
          <RouterLink class="c-textlink" to="/announcements">查看历史 →</RouterLink>
        </template>
      </CNotice>
    </div>

    <!-- ============ 3a. 我的当下（仅登录） ============ -->
    <section v-if="authenticated === true && todos.length" class="l-section now" aria-label="我的当下">
      <SectionHead kicker="WHAT'S NEXT FOR YOU" title="我的当下">
        <template #aside>
          <RouterLink class="c-textlink" to="/me">进入我的页面 →</RouterLink>
        </template>
      </SectionHead>
      <div class="now__grid">
        <RouterLink
          v-for="card in todos"
          :key="card.key"
          class="c-card now__card"
          :class="{ 'now__card--urgent': card.urgent }"
          :to="card.to"
        >
          <span class="u-kicker now__kicker">{{ card.kicker }}</span>
          <span class="now__days">
            {{ card.days }}
            <small>{{ card.unit }}</small>
          </span>
          <strong class="now__title">{{ card.title }}</strong>
          <span class="now__small u-small">{{ card.small }}</span>
        </RouterLink>
      </div>
    </section>

    <!-- ============ 3b. 快速选择 ============ -->
    <section v-if="quickEntries.length" id="start" class="l-section quick">
      <div class="quick__head">
        <p class="quick__ask u-h-section">你想从哪里开始？</p>
        <div class="quick__switch">
          <small class="u-kicker">快速选择</small>
          <button type="button" aria-label="上一个入口" @click="pickQuick(quickIndex - 1)">
            <AppIcon name="back" :size="15" />
          </button>
          <button type="button" aria-label="下一个入口" @click="pickQuick(quickIndex + 1)">
            <AppIcon name="arrow" :size="15" />
          </button>
        </div>
      </div>

      <div class="quick__grid" role="group" aria-label="快速选择">
        <button
          v-for="(entry, i) in quickEntries"
          :key="entry.id"
          class="quick__cell"
          type="button"
          :aria-pressed="i === quickIndex ? 'true' : 'false'"
          @click="pickQuick(i)"
        >
          <AppIcon :name="entry.icon" :size="20" />
          <span class="quick__label">{{ entry.label }}</span>
          <span class="quick__desc">{{ entry.description }}</span>
        </button>
      </div>

      <div v-if="quickCurrent" class="quick__detail" aria-live="polite">
        <div class="quick__text">
          <template v-if="!edit.active">
            <p v-if="quickCurrent.kicker" class="u-kicker">{{ quickCurrent.kicker }}</p>
            <h2 class="u-h-display quick__title">{{ quickCurrent.title || quickCurrent.label }}</h2>
            <p class="u-lead quick__lead">{{ quickCurrent.body }}</p>
            <div class="c-btn-row">
              <BtnLink :to="quickTo(quickCurrent)">
                {{ quickCurrent.button_text || quickCurrent.label }}
                <span aria-hidden="true">↗</span>
              </BtnLink>
            </div>
          </template>
          <!-- 编辑态：眼标 / 标题 / 正文 / 按钮文字都在原位改；
               上面那排格子是 <button>，可编辑文字不能塞进按钮里，所以「入口名 / 一行说明」
               收进一个与内容相邻的小弹层。 -->
          <template v-else>
            <EditableText
              class="u-kicker"
              :value="edit.quickValue(quickCurrent.id, 'kicker') ?? ''"
              :label="quickCurrent.label + '：眼标'"
              :max="QUICK_MAX.kicker"
              :error="quickError(quickCurrent.id, 'kicker')"
              @update:value="edit.setQuick(quickCurrent.id, 'kicker', $event)"
            />
            <EditableText
              class="u-h-display quick__title"
              as="h2"
              :value="edit.quickValue(quickCurrent.id, 'title') ?? ''"
              :label="quickCurrent.label + '：大标题'"
              :max="QUICK_MAX.title"
              :error="quickError(quickCurrent.id, 'title')"
              @update:value="edit.setQuick(quickCurrent.id, 'title', $event)"
            />
            <EditableText
              class="u-lead quick__lead"
              multiline
              :value="edit.quickValue(quickCurrent.id, 'body') ?? ''"
              :label="quickCurrent.label + '：正文'"
              :max="QUICK_MAX.body"
              :error="quickError(quickCurrent.id, 'body')"
              @update:value="edit.setQuick(quickCurrent.id, 'body', $event)"
            />
            <div class="c-btn-row">
              <!-- 按钮原样，只有里面的字可改（不是链接，编辑态里点了不跳走） -->
              <span class="c-btn quick__btn-edit">
                <EditableText
                  inline
                  bare
                  tone="dark"
                  :value="edit.quickValue(quickCurrent.id, 'button_text') ?? ''"
                  :label="quickCurrent.label + '：按钮文字'"
                  :max="QUICK_MAX.button_text"
                  :error="quickError(quickCurrent.id, 'button_text')"
                  @update:value="edit.setQuick(quickCurrent.id, 'button_text', $event)"
                />
                <span aria-hidden="true">↗</span>
              </span>
              <button
                class="quick__morebtn"
                type="button"
                :aria-expanded="quickMoreOpen ? 'true' : 'false'"
                @click="quickMoreOpen = !quickMoreOpen"
              >
                {{ quickMoreOpen ? '收起' : '改格子上的字' }}
              </button>
            </div>
            <div v-if="quickMoreOpen" class="quick__morebox">
              <p class="quick__morehead">上面那排格子里显示的两行</p>
              <label class="quick__morerow">
                <span class="quick__morelabel">入口名</span>
                <EditableText
                  :value="edit.quickValue(quickCurrent.id, 'label') ?? ''"
                  :label="quickCurrent.label + '：入口名（上面那排格子上的字）'"
                  :max="QUICK_MAX.label"
                  :error="quickError(quickCurrent.id, 'label')"
                  @update:value="edit.setQuick(quickCurrent.id, 'label', $event)"
                />
              </label>
              <label class="quick__morerow">
                <span class="quick__morelabel">一行说明</span>
                <EditableText
                  :value="edit.quickValue(quickCurrent.id, 'description') ?? ''"
                  :label="quickCurrent.label + '：格子上的一行说明'"
                  :max="QUICK_MAX.description"
                  :error="quickError(quickCurrent.id, 'description')"
                  @update:value="edit.setQuick(quickCurrent.id, 'description', $event)"
                />
              </label>
              <p class="quick__editnote">图标、去向与标识不在首页改，要动请去后台。</p>
            </div>
          </template>
        </div>
        <div v-if="quickCurrent.image || edit.active" class="quick__figure">
          <img
            v-if="quickCurrent.image"
            class="quick__image"
            :src="quickCurrent.image"
            :alt="quickCurrent.image_alt"
            loading="lazy"
            decoding="async"
          />
          <div v-else class="quick__image quick__image--blank" aria-hidden="true">还没有配图</div>
          <!-- 编辑态：整张图都是「更换图片」的热区，也接受把文件拖到图上 -->
          <EditableImage
            v-if="edit.active"
            kind="quick"
            cover
            :id="quickCurrent.id"
            :label="quickCurrent.label + '：配图'"
            :alt="edit.quickValue(quickCurrent.id, 'image_alt') ?? ''"
            :alt-max="QUICK_MAX.image_alt"
            @update:alt="edit.setQuick(quickCurrent.id, 'image_alt', $event)"
          />
        </div>
      </div>
    </section>

    <!-- ============ 4. 正在招募 ============ -->
    <section class="l-section recruit" aria-label="正在招募的团">
      <SectionHead
        v-if="!edit.active"
        :kicker="home.site?.section3.kicker || 'OPEN TABLES'"
        :title="home.site?.section3.title || '正在招募的团'"
        :lead="home.site?.section3.lead || ''"
        size="display"
      />
      <!-- 编辑态：抬头三行原位可改（`SectionHead` 是纯展示件，本波不给它塞编辑分支） -->
      <div v-else class="sechead-edit">
        <EditableText
          class="u-kicker"
          :value="edit.configValue('home_section3_kicker') ?? ''"
          label="正在招募这一段：眼标"
          :max="CONFIG_MAX.home_section3_kicker"
          :error="configError('home_section3_kicker')"
          @update:value="edit.setConfig('home_section3_kicker', $event)"
        />
        <EditableText
          class="u-h-display"
          :value="edit.configValue('home_section3_title') ?? ''"
          label="正在招募这一段：标题"
          :max="CONFIG_MAX.home_section3_title"
          :error="configError('home_section3_title')"
          @update:value="edit.setConfig('home_section3_title', $event)"
        />
        <EditableText
          class="u-lead"
          multiline
          :rows="2"
          :value="edit.configValue('home_section3_lead') ?? ''"
          label="正在招募这一段：导语"
          :max="CONFIG_MAX.home_section3_lead"
          :error="configError('home_section3_lead')"
          @update:value="edit.setConfig('home_section3_lead', $event)"
        />
      </div>

      <div class="recruit__filter">
        <div class="c-chips" role="group" aria-label="按规则筛选">
          <CChip :active="ruleFilter === ''" @click="ruleFilter = ''">全部</CChip>
          <CChip
            v-for="preset in rulePresets"
            :key="preset.id"
            :active="ruleFilter === preset.name"
            @click="ruleFilter = preset.name"
          >
            {{ preset.name }}
          </CChip>
          <CChip :active="ruleFilter === OTHER" @click="ruleFilter = OTHER">其他</CChip>
        </div>
        <div class="recruit__count">
          <span class="u-small">{{ openCount }} 个团 · {{ recruitingCount }} 个可报名</span>
          <div class="recruit__arrows">
            <button type="button" aria-label="向左" @click="scrollTrack(-1)">
              <AppIcon name="back" :size="15" />
            </button>
            <button type="button" aria-label="向右" @click="scrollTrack(1)">
              <AppIcon name="arrow" :size="15" />
            </button>
          </div>
        </div>
      </div>

      <CNotice v-if="gamesError" tone="warn">{{ gamesError }}</CNotice>

      <div v-else-if="games.length" class="recruit__wrap" :class="{ 'is-end': trackAtEnd }">
        <div
          ref="trackEl"
          class="track"
          @scroll.passive="paintTrack"
          @pointerdown="onTrackPointerDown"
          @pointermove="onTrackPointerMove"
          @pointerup="onTrackPointerUp"
          @pointercancel="onTrackPointerUp"
          @dragstart="onTrackDragStart"
          @click.capture="onTrackClickCapture"
          @wheel="onTrackWheel"
        >
          <RouterLink
            v-for="game in games"
            :key="game.id"
            class="gcard"
            :class="{ 'gcard--dim': game.status !== 'recruiting' }"
            :to="'/games/' + game.id"
          >
            <BlurStage
              class="gcard__art"
              :image="gameArt(game).image"
              :rule="game.rule_system"
              size="card"
              tone="dark"
              :foreground="false"
            >
              <span class="gcard__stage">
                <img :src="gameArt(game).file" alt="" loading="lazy" decoding="async" />
                <span class="gcard__corner">
                  <span v-if="game.rule_system" class="c-tag c-tag--dark">{{ game.rule_system }}</span>
                  <span v-for="tag in game.tags.slice(0, 2)" :key="tag" class="c-tag c-tag--dark">
                    {{ tag }}
                  </span>
                </span>
              </span>
              <span class="gcard__body">
                <span class="gcard__status" :class="'gcard__status--' + game.status">
                  {{ game.status_display }}
                </span>
                <span class="gcard__title u-h-card">{{ game.title }}</span>
                <span class="gcard__meta">
                  <span v-for="fact in gameMeta(game)" :key="fact">{{ fact }}</span>
                </span>
                <span class="gcard__who">
                  <img v-if="game.gm.avatar" class="gcard__face" :src="game.gm.avatar" alt="" />
                  <span v-else class="gcard__face gcard__face--blank" aria-hidden="true"></span>
                  <span>GM · {{ game.gm.nickname }}</span>
                </span>
              </span>
            </BlurStage>
          </RouterLink>
        </div>
      </div>

      <CEmpty
        v-else-if="!gamesLoading"
        compact
        title="这个筛选下没有在招的团"
        text="换一个规则看看，或者去招募页翻已经结团的记录。"
      >
        <template #actions>
          <RouterLink class="c-textlink" to="/recruit">查看全部招募 →</RouterLink>
        </template>
      </CEmpty>

      <p v-else class="u-small recruit__loading">正在读取……</p>

      <div class="recruit__foot">
        <RouterLink class="c-textlink" to="/recruit">查看全部招募 →</RouterLink>
        <RouterLink v-if="isGm" class="c-textlink" to="/games/new">我要开团 →</RouterLink>
        <span v-else-if="authenticated === false" class="u-small">
          开团需要 GM 身份。注册后申请，或作为玩家参团
          {{ config.gm_auto_promote_threshold }} 次自动获得。
        </span>
      </div>
    </section>

    <!-- ============ 5. 留下的故事 ============ -->
    <section class="l-section l-section--tone-3 stories" aria-label="精选战报">
      <SectionHead
        v-if="!edit.active"
        :kicker="home.site?.section4.kicker || 'STORIES WORTH KEEPING'"
        :title="home.site?.section4.title || '留下的故事'"
        :lead="home.site?.section4.lead || ''"
        size="display"
      />
      <div v-else class="sechead-edit">
        <EditableText
          class="u-kicker"
          :value="edit.configValue('home_section4_kicker') ?? ''"
          label="留下的故事这一段：眼标"
          :max="CONFIG_MAX.home_section4_kicker"
          :error="configError('home_section4_kicker')"
          @update:value="edit.setConfig('home_section4_kicker', $event)"
        />
        <EditableText
          class="u-h-display"
          :value="edit.configValue('home_section4_title') ?? ''"
          label="留下的故事这一段：标题"
          :max="CONFIG_MAX.home_section4_title"
          :error="configError('home_section4_title')"
          @update:value="edit.setConfig('home_section4_title', $event)"
        />
        <EditableText
          class="u-lead"
          multiline
          :rows="2"
          :value="edit.configValue('home_section4_lead') ?? ''"
          label="留下的故事这一段：导语"
          :max="CONFIG_MAX.home_section4_lead"
          :error="configError('home_section4_lead')"
          @update:value="edit.setConfig('home_section4_lead', $event)"
        />
      </div>

      <CNotice v-if="reportsError" tone="warn">{{ reportsError }}</CNotice>

      <div
        v-else-if="reports.length"
        class="stories__grid"
        :class="'stories__grid--' + reports.length"
      >
        <RouterLink
          v-for="report in reports"
          :key="report.id"
          class="pcard"
          :to="'/reports/' + report.id"
        >
          <img class="pcard__img" :src="reportArt(report)" alt="" loading="lazy" decoding="async" />
          <span class="pcard__corner">
            <span class="c-tag c-tag--dark">精选</span>
            <span v-if="report.game.rule_system" class="c-tag c-tag--dark">
              {{ report.game.rule_system }}
            </span>
          </span>
          <span class="pcard__cap">
            <small>{{ report.game.title }} · {{ formatDate(report.created_at) }}</small>
            <span class="pcard__title">{{ report.title }}</span>
            <span class="pcard__excerpt">{{ excerptOf(report) }}</span>
            <span class="pcard__who">
              <img v-if="report.author.avatar" class="pcard__face" :src="report.author.avatar" alt="" />
              <span v-else class="pcard__face pcard__face--blank" aria-hidden="true"></span>
              <span>{{ report.author.nickname }}</span>
            </span>
          </span>
        </RouterLink>
      </div>

      <CEmpty
        v-else-if="!reportsLoading"
        compact
        title="还没有精选战报"
        text="站主会从成员的战报里挑几篇放在这里。"
      >
        <template #actions>
          <RouterLink class="c-textlink" to="/reports">去战报区看看 →</RouterLink>
        </template>
      </CEmpty>

      <div class="c-btn-row">
        <RouterLink class="c-textlink" to="/reports">阅读全部战报 →</RouterLink>
        <RouterLink v-if="authenticated === true" class="c-textlink" to="/me/reports">
          写下我的战报 →
        </RouterLink>
      </div>

      <div v-if="recentGms.length" class="gms">
        <div class="gms__faces">
          <RouterLink
            v-for="gm in recentGms"
            :key="gm.id"
            class="gms__face"
            :to="'/users/' + gm.id"
            :title="gm.nickname"
          >
            <img v-if="gm.avatar" :src="gm.avatar" :alt="gm.nickname" />
            <span v-else class="gms__blank" aria-hidden="true">{{ gm.nickname.slice(0, 1) }}</span>
          </RouterLink>
        </div>
        <div class="gms__text">
          <p class="gms__line">最近开过团的 GM</p>
          <p class="u-small gms__hint">点头像进入个人空间，看 TA 的玩家卡、GM 卡和公开的战报。</p>
        </div>
        <RouterLink class="c-textlink gms__more" to="/recruit">看他们在招的团 →</RouterLink>
      </div>
    </section>

    <!-- ============ 5b. 活动掠影（精选照片） ============ -->
    <section v-if="photos.length" class="l-section photos" aria-label="活动掠影">
      <SectionHead
        kicker="MOMENTS AT THE TABLE"
        title="活动掠影"
        lead="站主从活动相册里挑出来的几张。照片里的人可以随时要求下架。"
      />
      <ul class="photos__grid">
        <li v-for="(photo, i) in photos" :key="photo.id" class="photos__cell">
          <button type="button" class="photos__btn" @click="showPhoto(i)">
            <img :src="photo.thumbnail_url" :alt="photo.caption || photo.game_title" loading="lazy" decoding="async" />
            <span class="u-hidden">看大图</span>
          </button>
        </li>
      </ul>
    </section>

    <!-- ============ 5c. 精选照片设置（只在编辑态出现） ============ -->
    <section v-if="edit.active" class="l-section fpwrap" aria-label="精选照片设置">
      <FeaturedPhotosPanel />
    </section>

    <!-- ============ 覆盖层：了解该规则 ============ -->
    <BlurStage
      v-if="ruleOpen && currentSlide"
      as="section"
      class="rulepage"
      :class="{ 'is-editing': edit.active }"
      :image="currentSlide.image"
      :rule="currentSlide.name"
      size="full"
      tone="dark"
      :foreground="false"
      role="dialog"
      aria-modal="true"
      :aria-label="(currentSlide.title || currentSlide.name) + ' 规则介绍'"
      @keydown="trapFocus"
    >
      <button ref="ruleBackBtn" class="rulepage__back" type="button" @click="closeRule">
        <span aria-hidden="true">←</span> 返回首页
      </button>
      <div class="rulepage__inner">
        <div class="rulepage__text">
          <p v-if="currentSlide.kicker" class="u-kicker rulepage__kicker">{{ currentSlide.kicker }}</p>
          <h2 class="rulepage__title">{{ currentSlide.title || currentSlide.name }}</h2>
          <p v-if="currentSlide.tagline" class="rulepage__tagline">{{ currentSlide.tagline }}</p>
          <template v-if="!edit.active">
            <p v-if="currentSlide.intro.body" class="rulepage__body">{{ currentSlide.intro.body }}</p>
            <p v-if="currentSlide.intro.fit" class="rulepage__body rulepage__fit">
              {{ currentSlide.intro.fit }}
            </p>
          </template>
          <!-- 编辑态：这一页专属的三格（正文 / 适合谁 / 官方站点）。
               眼标、标题、副标在首屏那一帧里改，这里不放第二套控件。 -->
          <template v-else>
            <EditableText
              class="rulepage__body"
              tone="dark"
              multiline
              :rows="5"
              :value="edit.presetValue(currentSlide.id, 'intro_body') ?? ''"
              :label="currentSlide.name + '：规则介绍正文'"
              :max="PRESET_MAX.intro_body"
              :error="presetError(currentSlide.id, 'intro_body')"
              @update:value="edit.setPreset(currentSlide.id, 'intro_body', $event)"
            />
            <EditableText
              class="rulepage__body rulepage__fit"
              tone="dark"
              multiline
              :rows="4"
              :value="edit.presetValue(currentSlide.id, 'intro_fit') ?? ''"
              :label="currentSlide.name + '：适合什么人'"
              :max="PRESET_MAX.intro_fit"
              :error="presetError(currentSlide.id, 'intro_fit')"
              @update:value="edit.setPreset(currentSlide.id, 'intro_fit', $event)"
            />
            <EditableText
              tone="dark"
              :value="edit.presetValue(currentSlide.id, 'official_url') ?? ''"
              :label="currentSlide.name + '：官方站点地址（只收 http / https）'"
              :max="PRESET_MAX.official_url"
              :error="presetError(currentSlide.id, 'official_url')"
              placeholder="https://…"
              @update:value="edit.setPreset(currentSlide.id, 'official_url', $event)"
            />
          </template>
          <div class="c-btn-row">
            <BtnLink variant="light" :to="ruleQuery('/recruit', currentSlide.name)">
              看正在招的团 <span aria-hidden="true">→</span>
            </BtnLink>
            <BtnLink variant="light" :to="ruleQuery('/cards', currentSlide.name)">看卡池</BtnLink>
            <BtnLink
              v-if="safeExternalUrl(currentSlide.official_url)"
              variant="light"
              :href="safeExternalUrl(currentSlide.official_url)"
            >
              阅读官方介绍 <span aria-hidden="true">↗</span>
            </BtnLink>
          </div>
        </div>
        <figure class="rulepage__art">
          <img :src="slideImage(currentSlide)" :alt="currentSlide.image_alt" />
        </figure>
      </div>
    </BlurStage>

    <!-- ============ 灯箱：精选照片 ============ -->
    <div
      v-if="openPhoto"
      class="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label="活动照片"
      @click="closePhoto"
      @keydown="trapFocus"
    >
      <button ref="lightboxClose" class="lightbox__close" type="button" @click="closePhoto">关闭 ✕</button>
      <figure class="lightbox__frame" @click.stop>
        <img :src="openPhoto.preview_url" :alt="openPhoto.caption || openPhoto.game_title" />
        <figcaption class="lightbox__cap">
          <span>{{ openPhoto.game_title }}</span>
          <span v-if="openPhoto.caption">{{ openPhoto.caption }}</span>
        </figcaption>
      </figure>
    </div>
  </div>
</template>

<style scoped>
/* ==========================================================================
   1. 首屏：规则轮播（v2 index.html `.hero`）
   手机默认：文字贴底、图取 50% 30%、底部渐变更厚；≥768 回到居中版。
   ========================================================================== */

.hero {
  position: relative;
  height: 570px;
  /* clip 而不是 hidden：hidden 的容器仍可被程序滚动（聚焦 / scrollIntoView 会把轮播横向拖走，
     2026-09-23 编辑态复检实测 1920 上被拖 689px），clip 彻底不可滚 */
  overflow: clip;
  isolation: isolate;
  color: var(--on-dark);
  background: var(--dark-bg);
  /* 钻到 sticky 顶栏下面（顶栏是玻璃变体，首屏图当它的底） */
  margin-top: calc(-1 * var(--header-h));
  touch-action: pan-y;
}

.hero__track {
  display: flex;
  height: 100%;
  transition: transform var(--dur-slide) var(--ease-slide);
}

/** 业务界面遵循后端权限与隐私约束。 */
.hero__slide {
  position: relative;
  flex: 0 0 100%;
  min-width: 0;
  height: 100%;
  display: grid;
  place-items: end center;
  isolation: isolate;
}

.hero__img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: 50% 30%;
  z-index: -2;
}

/* 左右压暗（v2 .slide::after）：中间浅、两边深，让文字块坐在暗区上 */
.hero__slide::after {
  content: "";
  position: absolute;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  background: linear-gradient(
    90deg,
    rgb(var(--hero-veil-rgb) / var(--edge)),
    rgb(var(--hero-veil-rgb) / var(--shade)) 13%,
    rgb(var(--hero-veil-rgb) / var(--shade)) 87%,
    rgb(var(--hero-veil-rgb) / var(--edge))
  );
}

/* 遮罩强度按帧明暗联动：浅色画面用满档，暗色画面降一档（免得 DND/COC 被压闷）。
   这几个数是观感调参，不是色板，所以留在本文件。
   **center 两档是按实测定的**（375 与 1440 四帧逐行量 WCAG 相对亮度，滑窗均值与最亮点两种口径
   都要 ≥4.5:1）：v2 稿那组值（light .62/.38、dark .32/.16）在「龙与地下城」「三角机构」两帧
   的眼标上只有 2.5–3.7:1 —— 那两张素材的文字区背后都有大片高光。 */
.hero {
  --veil-top: 0.62;
  --veil-bottom: 0.68;
  --veil-center: 0.74;
  --veil-center-2: 0.5;
}

.hero[data-tone="dark"] {
  --veil-top: 0.38;
  --veil-bottom: 0.42;
  --veil-center: 0.6;
  --veil-center-2: 0.38;
}

.hero::before,
.hero::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  z-index: 2;
  pointer-events: none;
  transition: opacity var(--dur-slow) var(--ease);
}

.hero::before {
  top: 0;
  height: 130px;
  background: linear-gradient(rgb(var(--hero-veil-rgb) / var(--veil-top)), transparent);
}

.hero::after {
  bottom: 0;
  height: 260px;
  background: linear-gradient(
    transparent,
    rgb(var(--hero-veil-rgb) / calc(var(--veil-bottom) * 0.75)) 40%,
    rgb(var(--hero-veil-rgb) / calc(var(--veil-bottom) + 0.18))
  );
}

.hero__center {
  position: relative;
  z-index: 1;
  min-width: 0;
  max-width: calc(100% - 2 * var(--sp-5));
  overflow-wrap: anywhere;
  padding: var(--sp-6) var(--sp-5) 100px;
  text-align: center;
  text-shadow: var(--hero-text-shadow);
}

/* 文字块自带一团径向暗雾：浅色画面上白字也能过 4.5:1（v2 .center::before） */
.hero__center::before {
  content: "";
  position: absolute;
  /* 手机上文字块贴底，雾要往上多罩一截：眼标是最上面那行，也是实测最险的一行 */
  inset: -40% -25% -30%;
  z-index: -1;
  pointer-events: none;
  background: radial-gradient(
    ellipse at center,
    rgb(var(--hero-veil-rgb) / var(--veil-center)) 0%,
    rgb(var(--hero-veil-rgb) / var(--veil-center-2)) 40%,
    transparent 72%
  );
}

.hero__kicker {
  margin: 0 0 var(--sp-2);
  color: var(--on-dark);
  opacity: 0.92;
}

.hero__title {
  margin: 0 0 var(--sp-2);
  font-size: clamp(20px, 2.65vw, 29px);
  font-weight: 400;
  line-height: var(--lh-tight);
  letter-spacing: var(--ls-wide);
}

.hero__copy {
  max-width: 230px;
  margin: 0 auto;
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  letter-spacing: var(--ls-caps-sm);
}

.hero__start {
  margin-top: var(--sp-4);
  gap: var(--sp-3);
  padding: var(--sp-2) var(--sp-4);
  font-size: var(--fs-xs);
}

.hero__turn {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  z-index: 3;
  display: grid;
  place-items: center;
  min-width: 44px;
  min-height: 44px;
  color: var(--on-dark);
  background: transparent;
  border: 0;
}

.hero__turn--prev {
  left: var(--sp-1);
}

.hero__turn--next {
  right: var(--sp-1);
}

.hero__foot {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 3;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-1);
  padding: var(--sp-2) var(--sp-5) var(--sp-3);
  text-shadow: var(--hero-text-shadow);
}

.hero__rules {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
}

.hero__rule {
  min-height: 44px;
  padding: var(--sp-2) 0;
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-wide);
  color: var(--on-dark);
  background: transparent;
  border: 0;
  border-bottom: 1px solid transparent;
  opacity: 0.8;
}

.hero__rule[aria-pressed="true"] {
  opacity: 1;
  font-weight: 600;
  border-bottom-color: var(--on-dark);
}

.hero__aside {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-wide);
}

.hero__learn {
  min-height: 44px;
  padding: var(--sp-2) 0;
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-wide);
  color: var(--on-dark);
  background: none;
  border: 0;
}

/* ==========================================================================
   2. 站长公告横幅
   ========================================================================== */

.announce {
  padding: var(--sp-4) var(--pad) 0;
}

.announce__body {
  margin: 0;
  font-size: var(--fs-md);
  line-height: var(--lh-body);
  white-space: pre-line;
}

.announce__at {
  margin: var(--sp-1) 0 0;
}

/* ==========================================================================
   3a. 我的当下
   ========================================================================== */

.now {
  padding-bottom: 0;
}

.now__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-3);
}

.now__card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  column-gap: var(--sp-3);
  padding: var(--sp-4);
  border-left: 3px solid var(--line-2);
  color: inherit;
  text-decoration: none;
}

.now__kicker,
.now__title,
.now__small {
  grid-column: 1;
}

.now__days {
  grid-column: 2;
  grid-row: 1 / span 3;
  align-self: start;
  text-align: right;
  font-size: var(--fs-2xl);
  line-height: 1;
  letter-spacing: var(--ls-section);
  color: var(--ink-soft);
}

.now__days small {
  display: block;
  margin-top: var(--sp-1);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-kicker);
  color: var(--ink-faint);
}

.now__title {
  margin-top: var(--sp-2);
  font-size: var(--fs-lg);
  font-weight: 400;
  line-height: var(--lh-tight);
  /* 固定两行高，几张卡的脚注才对得齐 */
  min-height: calc(var(--fs-lg) * var(--lh-tight) * 2);
}

.now__small {
  margin-top: var(--sp-2);
}

.now__card--urgent {
  border-left-color: var(--danger);
}

.now__card--urgent .now__kicker,
.now__card--urgent .now__days {
  color: var(--danger);
}

/* ==========================================================================
   3b. 快速选择
   ========================================================================== */

.quick__head {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  margin-bottom: var(--sp-4);
}

.quick__ask {
  margin: 0;
}

.quick__switch {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--ink-muted);
}

.quick__switch button {
  display: grid;
  place-items: center;
  /** 业务界面遵循后端权限与隐私约束。 */
  width: 44px;
  height: 44px;
  margin-block: -4px;
  color: var(--ink-soft);
  background: none;
  border: 1px solid var(--line-2);
  border-radius: var(--radius-pill);
}

.quick__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-2);
}

.quick__cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
  min-height: 96px;
  padding: var(--sp-4) var(--sp-4) var(--sp-3);
  font-size: var(--fs-sm);
  letter-spacing: var(--ls-mid);
  text-align: left;
  color: var(--ink-soft);
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.quick__label {
  display: block;
}

.quick__desc {
  display: block;
  font-size: var(--fs-2xs);
  line-height: var(--lh-card);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-faint);
}

.quick__cell[aria-pressed="true"] {
  color: var(--on-brand);
  background: var(--brand);
  border-color: var(--brand);
}

.quick__cell[aria-pressed="true"] .quick__desc {
  color: var(--on-dark-2);
}

.quick__detail {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-5);
  margin-top: var(--sp-5);
}

.quick__text {
  order: 2;
}

.quick__title {
  margin: var(--sp-3) 0 var(--sp-3);
  /* 站主可以在标题里直接敲回车（后端 `QuickEntry.title` 收纯文本，不收 HTML） */
  white-space: pre-line;
}

.quick__lead {
  max-width: 380px;
  margin: 0;
}

.quick__image {
  width: 100%;
  height: 220px;
  object-fit: cover;
  border-radius: var(--radius);
}

/* ==========================================================================
   4. 正在招募：筛选条 + 横轨
   横轨自己管左右留白（`--pad`），所以本段的 `.l-section` 只留纵向节奏。
   ========================================================================== */

.recruit {
  padding-left: 0;
  padding-right: 0;
}

.recruit > :not(.recruit__wrap) {
  padding-left: var(--pad);
  padding-right: var(--pad);
}

.recruit__filter {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  margin-bottom: var(--sp-4);
}

.recruit__count {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
}

.recruit__arrows {
  display: flex;
  gap: var(--sp-2);
}

.recruit__arrows button {
  display: grid;
  place-items: center;
  /** 业务界面遵循后端权限与隐私约束。 */
  width: 44px;
  height: 44px;
  margin-block: -4px;
  color: var(--ink-soft);
  background: none;
  border: 1px solid var(--line-2);
  border-radius: var(--radius-pill);
}

.recruit__loading {
  margin: 0;
}

.recruit__wrap {
  position: relative;
}

/* 右侧渐隐：提示还能往右滚；滚到底就淡出 */
.recruit__wrap::after {
  content: "";
  position: absolute;
  top: 0;
  bottom: var(--sp-3);
  right: 0;
  width: 40px;
  pointer-events: none;
  background: linear-gradient(90deg, transparent, var(--bg));
  transition: opacity var(--dur) var(--ease);
}

.recruit__wrap.is-end::after {
  opacity: 0;
}

.track {
  display: flex;
  gap: var(--sp-4);
  overflow-x: auto;
  padding: var(--sp-1) var(--pad) var(--sp-3);
  scroll-snap-type: x mandatory;
  scroll-padding-left: var(--pad);
  scrollbar-width: none;
}

.track::-webkit-scrollbar {
  display: none;
}

/* 鼠标拖动中：关吸附、换抓手、禁选中文字与图片拖拽 */
.track.is-dragging {
  scroll-snap-type: none;
  cursor: grabbing;
  user-select: none;
}

.track.is-dragging .gcard {
  pointer-events: none;
}

@media (hover: hover) and (pointer: fine) {
  .track {
    cursor: grab;
  }
}

.gcard {
  flex: 0 0 84vw;
  scroll-snap-align: start;
  border-radius: var(--radius);
  overflow: hidden;
  color: var(--on-dark);
  text-decoration: none;
}

.gcard--dim {
  opacity: 0.82;
}

.gcard__art {
  display: block;
  height: 100%;
}

.gcard__stage {
  position: relative;
  display: block;
  height: 210px;
}

.gcard__stage img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.gcard--dim .gcard__stage img {
  filter: saturate(0.7);
}

.gcard__corner {
  position: absolute;
  top: var(--sp-3);
  left: var(--sp-3);
  z-index: 1;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1);
}

.gcard__body {
  display: block;
  padding: var(--sp-4) var(--sp-5) var(--sp-5);
  background: var(--card-body-glass);
}

.gcard__status {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: var(--sp-2);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-wide);
}

.gcard__status::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: var(--radius-pill);
  background: currentcolor;
}

.gcard__status--recruiting {
  color: var(--st-recruiting);
}

.gcard__status--closed_signup {
  color: var(--st-closed-signup);
}

.gcard__status--running {
  color: var(--st-running);
}

.gcard__status--finished {
  color: var(--on-dark-3);
}

.gcard__status--cancelled {
  color: var(--st-cancelled);
}

.gcard__title {
  display: block;
  margin-bottom: var(--sp-2);
}

.gcard__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-4);
  margin-top: var(--sp-3);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps);
  color: var(--on-dark-2);
}

.gcard__who {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
  font-size: var(--fs-xs);
}

.gcard__face {
  flex: none;
  width: 24px;
  height: 24px;
  object-fit: cover;
  border-radius: var(--radius-pill);
  border: 1px solid var(--glass-line);
  background: var(--avatar-bg);
}

.recruit__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-5);
  margin-top: var(--sp-3);
}

/* ==========================================================================
   5. 留下的故事
   ========================================================================== */

.stories__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-4);
}

.pcard {
  position: relative;
  display: block;
  min-height: 320px;
  overflow: hidden;
  border-radius: var(--radius);
  color: var(--on-dark);
  text-decoration: none;
  background: var(--stage-bg);
}

.pcard__img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.pcard__corner {
  position: absolute;
  top: var(--sp-3);
  left: var(--sp-3);
  z-index: 1;
  display: flex;
  gap: var(--sp-1);
}

.pcard__cap {
  position: absolute;
  inset: auto 0 0;
  display: block;
  padding: var(--sp-9) var(--sp-5) var(--sp-4);
  background: linear-gradient(transparent, var(--cap-scrim-1) 38%, var(--cap-scrim-2));
  text-shadow: var(--hero-text-shadow);
}

.pcard__cap small {
  display: block;
  margin-bottom: var(--sp-2);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-wide);
  opacity: 0.9;
}

.pcard__title {
  display: block;
  font-size: var(--fs-2xl);
  line-height: var(--lh-tight);
}

.pcard__excerpt {
  display: -webkit-box;
  margin-top: var(--sp-2);
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  color: var(--on-dark-2);
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.pcard__who {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
  font-size: var(--fs-xs);
}

.pcard__face {
  flex: none;
  width: 24px;
  height: 24px;
  object-fit: cover;
  border-radius: var(--radius-pill);
  border: 1px solid var(--glass-line);
  background: var(--avatar-bg);
}

.gms {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-4);
  margin-top: var(--sp-6);
  padding-top: var(--sp-5);
  border-top: 1px solid var(--line-2);
}

.gms__faces {
  display: flex;
}

.gms__face {
  display: block;
  margin-right: -8px;
  border: 2px solid var(--bg-3);
  border-radius: var(--radius-pill);
}

.gms__face img,
.gms__blank {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  object-fit: cover;
  border-radius: var(--radius-pill);
  background: var(--avatar-bg);
  color: var(--ink-soft);
  font-size: var(--fs-md);
}

.gms__text {
  max-width: 420px;
}

.gms__line {
  margin: 0;
  font-size: var(--fs-md);
}

.gms__hint {
  margin: var(--sp-1) 0 0;
}

.gms__more {
  margin-left: auto;
}

/* ==========================================================================
   5b. 活动掠影
   ========================================================================== */

.photos__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.photos__btn {
  display: block;
  width: 100%;
  padding: 0;
  background: var(--thumb-bg);
  border: 0;
  border-radius: var(--radius);
  overflow: hidden;
}

.photos__btn img {
  width: 100%;
  height: 130px;
  object-fit: cover;
}

/* ==========================================================================
   覆盖层：了解该规则
   ========================================================================== */

.rulepage {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  align-content: start;
  padding: 84px var(--pad) var(--sp-7);
  overflow: auto;
  overscroll-behavior: contain;
  color: var(--on-dark);
}

/* 覆盖层的遮罩比普通铺底更重（v2 .rule-page::after） */
.rulepage::after {
  background: linear-gradient(180deg, var(--overlay-scrim-1), var(--overlay-scrim-2));
}

.rulepage__back {
  position: fixed;
  top: var(--sp-4);
  left: var(--sp-5);
  z-index: 1;
  min-height: 44px;
  padding: var(--sp-2) var(--sp-4);
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-wide);
  color: var(--on-dark);
  background: var(--veil-tag);
  border: 1px solid var(--glass-line);
  border-radius: var(--radius-pill);
}

.rulepage__inner {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-5);
  align-items: center;
}

.rulepage__kicker {
  margin: 0;
  color: var(--on-dark-kicker);
}

.rulepage__title {
  margin: var(--sp-4) 0 var(--sp-2);
  font-size: clamp(28px, 4vw, 44px);
  font-weight: 400;
  line-height: var(--lh-tight);
  letter-spacing: var(--ls-caps);
}

.rulepage__tagline {
  margin: 0 0 var(--sp-5);
  font-size: var(--fs-sm);
  letter-spacing: var(--ls-kicker);
  opacity: 0.9;
}

.rulepage__body {
  max-width: 560px;
  margin: 0;
  font-size: var(--fs-base);
  line-height: var(--lh-read);
  color: var(--on-dark-2);
  white-space: pre-line;
}

.rulepage__fit {
  margin-top: var(--sp-4);
}

.rulepage__art {
  order: -1;
  margin: 0;
  aspect-ratio: 16 / 10;
  overflow: hidden;
  border-radius: var(--radius);
  background: var(--dark-bg);
  box-shadow: var(--shadow-2);
}

.rulepage__art img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* ==========================================================================
   灯箱：精选照片
   ========================================================================== */

.lightbox {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  gap: var(--sp-4);
  padding: var(--sp-7) var(--sp-4) var(--sp-5);
  overflow: auto;
  overscroll-behavior: contain;
  background: var(--overlay-scrim-2);
}

.lightbox__close {
  position: fixed;
  top: var(--sp-4);
  right: var(--sp-4);
  min-height: 44px;
  padding: var(--sp-2) var(--sp-4);
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-wide);
  color: var(--on-dark);
  background: var(--veil-tag);
  border: 1px solid var(--glass-line);
  border-radius: var(--radius-pill);
}

.lightbox__frame {
  margin: 0;
  max-width: min(100%, 900px);
}

.lightbox__frame img {
  width: auto;
  max-width: 100%;
  /* 竖幅照片不要把灯箱撑成一条长条：先按视口高度封顶，再等比缩 */
  max-height: 78dvh;
  object-fit: contain;
  border-radius: var(--radius);
}

.lightbox__cap {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-4);
  margin-top: var(--sp-3);
  font-size: var(--fs-xs);
  color: var(--on-dark-2);
}

/* ==========================================================================
   ≥768px：平板与桌面
   ========================================================================== */

@media (min-width: 768px) {
  .hero {
    height: 590px;
  }

  .hero__slide {
    place-items: center;
  }

  .hero__img {
    object-position: 55% center;
  }

  .hero__center {
    max-width: 100%;
    padding: var(--sp-7) 72px var(--sp-6);
  }

  .hero__center::before {
    inset: -30% -40%;
  }

  .hero__copy {
    max-width: none;
  }

  .hero::after {
    height: 170px;
    background: linear-gradient(transparent, rgb(var(--hero-veil-rgb) / var(--veil-bottom)));
  }

  .hero__foot {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-4);
    padding: var(--sp-3) var(--pad) var(--sp-4);
  }

  .hero__rules {
    gap: 19px;
  }

  .hero__turn--prev {
    left: var(--sp-2);
  }

  .hero__turn--next {
    right: var(--sp-2);
  }

  .now__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .quick__head {
    flex-direction: row;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--sp-5);
  }

  .quick__grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .quick__detail {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr);
    gap: var(--sp-7);
    align-items: center;
    margin-top: var(--sp-6);
  }

  /* ≥768 文字在左、配图在右（v2 `.quick-detail` 的 1fr / 1.15fr）；
     手机上配图在前（`.quick__text { order: 2 }`），所以这里要显式收回 order。 */
  .quick__text {
    order: 0;
  }

  .quick__image {
    height: 300px;
  }

  .recruit__filter {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-4);
  }

  .gcard {
    /* 卡宽按版心算：1440 上限内四张一屏（v2 348px），下限 300、上限 420 */
    flex-basis: clamp(300px, calc((min(100vw, var(--max)) - 48px) / 4), 420px);
  }

  /* 精选战报够三篇才摆 v2 那个「一大两小」的版式；
     只有一两篇时摆成整幅 / 两栏，免得右边空出一个洞。 */
  .stories__grid--3 {
    grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
    grid-template-rows: 1fr 1fr;
  }

  .stories__grid--2 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .pcard {
    min-height: 222px;
  }

  .stories__grid--3 .pcard:first-child {
    grid-row: 1 / span 2;
  }

  .stories__grid--1 .pcard,
  .stories__grid--2 .pcard,
  .stories__grid--3 .pcard:first-child {
    min-height: 460px;
  }

  .stories__grid--1 .pcard .pcard__title,
  .stories__grid--2 .pcard .pcard__title,
  .stories__grid--3 .pcard:first-child .pcard__title {
    font-size: 24px;
  }

  .photos__grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: var(--sp-3);
  }

  .photos__btn img {
    height: 180px;
  }

  .rulepage {
    align-content: center;
    padding: 90px var(--pad) var(--sp-8);
  }

  .rulepage__inner {
    grid-template-columns: minmax(0, 560px) minmax(0, 1fr);
    gap: 56px;
  }

  .rulepage__art {
    order: 0;
    aspect-ratio: 4 / 3;
  }
}

/* ==========================================================================
   ≥1200px：桌面加宽
   ========================================================================== */

@media (min-width: 1200px) {
  .now__grid {
    grid-template-columns: repeat(4, minmax(0, 330px));
  }

  .quick__grid {
    grid-template-columns: repeat(6, minmax(0, 1fr));
  }

  .recruit__wrap::after {
    width: 72px;
  }
}

/* ==========================================================================
   宽屏横轨（出处 v2 index.html 文件头「宽屏留白」）
   flex-basis 的 100% 按**横轨内容盒**算，已扣掉两侧 --pad，正好等于版心宽，
   所以末卡右缘始终贴版心右线：1921+ 四张一屏、2251+ 三张一屏。
   ========================================================================== */

@media (min-width: 1921px) {
  .gcard {
    flex-basis: clamp(300px, calc((100% - 48px) / 4), 420px);
  }
}

@media (min-width: 2251px) {
  .gcard {
    flex-basis: clamp(300px, calc((100% - 32px) / 3), 420px);
  }
}
/** 业务界面遵循后端权限与隐私约束。 */

/* 首屏在编辑态**不再变高**（2026-09-23 原地编辑重做）：文字原位改、换图是覆盖层、
   其余两项收进弹层，一帧的高度与普通态一致，`height: 100%` 的轨道与帧不会塌。 */
/* 首屏右上角的块级工具：「更换图片」徽标（EditableImage 自带，top 8px）下面一行是「更多设置」，
   弹层从它下方展开、右对齐。首屏文字压在底部居中，顶部这一角本来是空的，不会盖住标题。 */
.hero__tools {
  position: absolute;
  /* 页头是 sticky 压在首屏顶上：让出页头高度，再让出上面那枚「更换图片」徽标 */
  top: calc(var(--header-h, 54px) + var(--sp-2) + 34px);
  right: var(--pad);
  z-index: 3;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: var(--sp-2);
  text-shadow: none;
  text-align: left;
}

.hero__morebtn,
.quick__morebtn {
  min-height: 28px;
  padding: 3px 9px;
  font-family: var(--font-sans);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps-sm);
  line-height: 1.4;
  color: var(--on-dark);
  background: var(--scrim-3);
  border: 1px solid var(--on-dark);
  border-radius: 999px;
  cursor: pointer;
  box-shadow: 0 1px 4px rgb(0 0 0 / 0.18);
}

.hero__morebtn:hover,
.hero__morebtn[aria-expanded='true'] {
  color: var(--brand-ink);
  background: var(--on-dark);
}

.hero__morebox,
.quick__morebox {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  text-align: left;
}

.hero__morebox {
  width: min(360px, calc(100vw - 2 * var(--pad)));
  padding: var(--sp-3) var(--sp-4);
  color: var(--on-dark);
  background: var(--scrim-3);
  border-radius: var(--radius);
  backdrop-filter: blur(6px);
}

/* 弹层开着时把左右翻页箭头藏掉（它们在画面中线，会和弹层挤在一起） */
.hero.has-panel .hero__turn {
  visibility: hidden;
}

.hero__morehead,
.quick__morehead {
  margin: 0;
  font-family: var(--font-sans);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps-sm);
  line-height: 1.4;
  opacity: 0.85;
}

.hero__morerow,
.quick__morerow {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hero__morelabel,
.quick__morelabel {
  font-family: var(--font-sans);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps-sm);
  opacity: 0.85;
}

/* 分区抬头的三行（替 SectionHead） */
.sechead-edit {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  max-width: 640px;
  margin-bottom: var(--sp-5);
}

/* 快速选择：按钮原样只换字；「格子上的字」小弹层贴在按钮行下面 */
.quick__btn-edit {
  cursor: default;
}

.quick__morebtn {
  color: var(--brand-ink);
  background: var(--white);
  border-color: var(--brand-ink);
}

.quick__morebtn:hover,
.quick__morebtn[aria-expanded='true'] {
  border-style: solid;
}

.quick__morebox {
  margin-top: var(--sp-3);
  padding: var(--sp-3);
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
  background: var(--white);
}

.quick__editnote {
  margin: 0;
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps-sm);
  line-height: 1.6;
  color: var(--ink-muted);
}

.quick__figure {
  position: relative;
  border-radius: var(--radius);
}

.quick__image--blank {
  display: grid;
  place-items: center;
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-muted);
  background: var(--bg-2);
}

/* 规则介绍覆盖层：底部让开固定的保存条（它在 z-index 60，压在覆盖层上面） */
.rulepage.is-editing {
  padding-bottom: calc(var(--sp-7) + var(--edit-bar-h, 76px));
}

/* 精选照片面板所在的那一段 */
.fpwrap {
  padding-top: 0;
}
</style>
