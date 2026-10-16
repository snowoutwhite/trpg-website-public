<script setup lang="ts">
/** 页面布局与交互。 */
import { storeToRefs } from 'pinia'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import AppIcon from './AppIcon.vue'
import { MAIN_NAV } from './nav-links'
import { fetchUnreadCount } from '../api/notifications'
import { useAuthStore } from '../stores/auth'
import { useEditStore } from '../stores/edit'
import EditableText from './edit/EditableText.vue'
import { CONFIG_MAX } from '../api/homeAdmin'
import { useHomeStore } from '../stores/home'
import { useSiteStore } from '../stores/site'

const props = withDefaults(defineProps<{ variant?: 'glass' | 'light' }>(), { variant: 'light' })
const variant = computed(() => props.variant)

/** 站主点「编辑」时由外壳（`App.vue` 的 `onEdit`）决定进不进编辑态。 */
defineEmits<{ edit: [] }>()

const site = useSiteStore()
const home = useHomeStore()
const auth = useAuthStore()
const edit = useEditStore()
const { config } = storeToRefs(site)
const { authenticated, user, displayName, isGm } = storeToRefs(auth)

const route = useRoute()
/** 已经在登录/注册页时，顶栏不必再重复同样的入口。 */
const onAuthPage = computed(() => route.name === 'login' || route.name === 'signup')

/** 站名优先用 `/home/` 那份（站主能改），拿不到再退回 `/siteconfig/`。 */
const siteName = computed(() => home.site?.site_name || config.value.site_name)

const isStaff = computed(() => user.value?.is_staff === true)

const unread = ref(0)
/** 角标最多显示到 99+，再多也没意义，还会把三列网格撑歪。 */
const unreadLabel = computed(() => (unread.value > 99 ? '99+' : String(unread.value)))

watch(
  authenticated,
  async (ok) => {
    if (ok !== true) {
      unread.value = 0
      return
    }
    try {
      unread.value = (await fetchUnreadCount()).unread
    } catch {
      unread.value = 0
    }
  },
  { immediate: true },
)

/** 主操作胶囊：按身份选一条最常用的去处（见文件头）。登录态未知时不显示，免得闪一下错的按钮。 */
const primary = computed<{ to: string; label: string } | null>(() => {
  if (authenticated.value === false) return onAuthPage.value ? null : { to: '/auth/login', label: '登录' }
  if (authenticated.value !== true) return null
  return isGm.value ? { to: '/games/new', label: '我要开团' } : { to: '/me', label: '个人空间' }
})

/** 菜单「我的」卡片里的入口。 */
const mineLinks = computed<{ to: string; label: string; note?: string }[]>(() => {
  if (authenticated.value === false) {
    return [
      { to: '/auth/login', label: '登录' },
      { to: '/auth/signup', label: '注册' },
    ]
  }
  if (authenticated.value !== true) return []
  const links: { to: string; label: string; note?: string }[] = [
    { to: '/me', label: '个人空间' },
    {
      to: '/me/notifications',
      label: '通知',
      note: unread.value > 0 ? unreadLabel.value + ' 条未读' : undefined,
    },
  ]
  if (isGm.value) links.push({ to: '/games/new', label: '我要开团' })
  return links
})

const navLinks = computed(() => [{ to: '/', label: '首页' }, ...MAIN_NAV])

// ---------------------------------------------------------------------------
// 菜单开合与焦点管理
// ---------------------------------------------------------------------------

const menuOpen = ref(false)
const menuBtn = ref<HTMLButtonElement | null>(null)
const panel = ref<HTMLElement | null>(null)

function focusables(): HTMLElement[] {
  const inside = panel.value
    ? Array.from(panel.value.querySelectorAll<HTMLElement>('a[href], button:not([disabled])'))
    : []
  return menuBtn.value ? [menuBtn.value, ...inside] : inside
}

/**
 * 菜单打开时锁住页面滚动：`overflow:hidden` 让滚动条消失，页面会横向跳一下，
 * 所以同时给 body 补上等宽的右内边距。关闭（含组件卸载）时原样恢复。
 */
function lockScroll(on: boolean): void {
  const root = document.documentElement
  if (on) {
    const bar = window.innerWidth - root.clientWidth
    root.style.overflow = 'hidden'
    if (bar > 0) {
      document.body.style.paddingRight = bar + 'px'
      // 右对齐的 fixed 菜单面板不受 body 内边距影响，单独补同样的宽度（见 .c-menu 的 right）
      root.style.setProperty('--menu-scroll-comp', bar + 'px')
    }
  } else {
    root.style.overflow = ''
    document.body.style.paddingRight = ''
    root.style.removeProperty('--menu-scroll-comp')
  }
}

watch(menuOpen, (open) => lockScroll(open))

function openMenu(): void {
  menuOpen.value = true
  // 打开后把焦点放到第一条链接（面板一打开就 visibility:visible，可聚焦）
  void nextTick(() => focusables()[1]?.focus())
}

/** `restore`：关闭后是否把焦点送回菜单按钮（点链接跳走时不需要）。 */
function closeMenu(restore: boolean): void {
  if (!menuOpen.value) return
  menuOpen.value = false
  if (restore) menuBtn.value?.focus()
}

function toggleMenu(): void {
  if (menuOpen.value) closeMenu(true)
  else openMenu()
}

function onKeydown(event: KeyboardEvent): void {
  if (!menuOpen.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeMenu(true)
    return
  }
  if (event.key !== 'Tab') return
  // 面板挂在 body 末尾，Tab 的自然顺序会从菜单按钮跳去页面主体 —— 这里把
  // 「菜单按钮 + 面板里的链接」围成一个圈，关掉菜单之前焦点不会溜到遮罩后面去。
  const items = focusables()
  if (!items.length) return
  const index = items.indexOf(document.activeElement as HTMLElement)
  const step = event.shiftKey ? -1 : 1
  const next = index === -1 ? 0 : (index + step + items.length) % items.length
  event.preventDefault()
  items[next]?.focus()
}

function onPointerDown(event: PointerEvent): void {
  if (!menuOpen.value) return
  const target = event.target as Node | null
  if (!target) return
  if (panel.value?.contains(target) || menuBtn.value?.contains(target)) return
  closeMenu(false)
}

watch(
  () => route.fullPath,
  () => closeMenu(false),
)

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  document.addEventListener('pointerdown', onPointerDown)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('pointerdown', onPointerDown)
  if (menuOpen.value) lockScroll(false)
})
</script>

<template>
  <header class="c-header" :class="'c-header--' + variant">
    <div class="c-header__brand">
      <!-- 编辑态：站名就在这里改（GoDaddy 口径：页头左上角的站名也能直接点改；走草稿，要点保存） -->
      <EditableText
        v-if="edit.active"
        inline
        class="c-header__name c-header__name--edit"
        :tone="variant === 'glass' ? 'dark' : 'light'"
        :value="edit.configValue('site_name') ?? siteName"
        label="站名"
        :max="CONFIG_MAX.site_name"
        :error="edit.fieldErrors['config.site_name'] ?? ''"
        @update:value="edit.setConfig('site_name', $event)"
      />
      <RouterLink v-else to="/" class="c-header__name">{{ siteName }}</RouterLink>
    </div>

    <nav class="c-header__main" aria-label="主导航">
      <RouterLink v-for="link in MAIN_NAV" :key="link.to" :to="link.to" class="c-header__link">
        {{ link.label }}
      </RouterLink>
    </nav>

    <nav class="c-header__user" aria-label="个人入口">
      <template v-if="authenticated === true">
        <button
          v-if="isStaff"
          class="c-header__link c-header__edit"
          :class="{ 'is-on': edit.active }"
          type="button"
          aria-label="编辑站点内容"
          :aria-pressed="edit.active ? 'true' : 'false'"
          @click="$emit('edit')"
        >
          <AppIcon name="edit" :size="14" />
          <span class="c-header__label">编辑</span>
        </button>

        <!-- 通知只留图标 + 角标（文字「通知」在菜单卡片里）：右列要让出胶囊按钮的宽度。
             可读名靠 aria-label（复检 2026-09-22 无障碍树取证） -->
        <RouterLink
          to="/me/notifications"
          class="c-header__link c-header__bellink"
          :aria-label="unread > 0 ? `通知，${unread} 条未读` : '通知'"
        >
          <AppIcon class="c-header__bell" name="bell" :size="16" />
          <span v-if="unread > 0" class="c-header__badge">
            {{ unreadLabel }}
            <span class="u-hidden">条未读通知</span>
          </span>
        </RouterLink>
      </template>

      <!-- 主操作胶囊：悬浮时箭头从左侧裁切处滑入、文字右移让位、右侧小圆点缩没 -->
      <RouterLink
        v-if="primary"
        :to="primary.to"
        class="hbtn hbtn--primary"
        :class="{ 'hbtn--wide-only': authenticated === true }"
      >
        <span class="hbtn__in">
          <span class="hbtn__arrow" aria-hidden="true"><AppIcon name="arrow" :size="14" /></span>
          <span class="hbtn__text">{{ primary.label }}</span>
          <span class="hbtn__dot" aria-hidden="true"></span>
        </span>
      </RouterLink>

      <!-- 菜单胶囊：两个圆点悬浮时转成竖排；打开后「菜单」上移出框、「关闭」从下方升入 -->
      <button
        ref="menuBtn"
        class="hbtn hbtn--menu"
        :class="{ 'is-open': menuOpen }"
        type="button"
        aria-controls="site-menu"
        :aria-expanded="menuOpen ? 'true' : 'false'"
        :aria-label="menuOpen ? '关闭菜单' : '打开菜单'"
        @click="toggleMenu"
      >
        <span class="hbtn__in hbtn__in--late">
          <span class="hbtn__dots" aria-hidden="true"><i></i><i></i></span>
          <span class="hbtn__roll" aria-hidden="true">
            <span>菜单</span>
            <span>关闭</span>
          </span>
        </span>
      </button>
    </nav>

    <Teleport to="body">
      <div class="c-menu-veil" :class="{ 'is-open': menuOpen }" aria-hidden="true"></div>
      <nav
        id="site-menu"
        ref="panel"
        class="c-menu"
        :class="{ 'is-open': menuOpen }"
        aria-label="站内菜单"
      >
        <section
          class="c-menu__card"
          :style="{ '--i': 0, '--n': mineLinks.length ? 2 : 1, '--tilt': '3.5deg' }"
        >
          <h2 class="c-menu__head">/ 站内去处</h2>
          <ul class="c-menu__list">
            <li v-for="link in navLinks" :key="link.to">
              <RouterLink :to="link.to" class="c-menu__link" @click="closeMenu(false)">
                <span class="c-menu__roll">
                  <span>{{ link.label }}</span>
                  <span aria-hidden="true">{{ link.label }}</span>
                </span>
              </RouterLink>
            </li>
          </ul>
        </section>

        <section
          v-if="mineLinks.length"
          class="c-menu__card"
          :style="{ '--i': 1, '--n': 2, '--tilt': '-3.5deg' }"
        >
          <h2 class="c-menu__head">/ 我的</h2>
          <p v-if="authenticated === true" class="c-menu__who">
            <img v-if="user?.avatar" class="c-header__avatar" :src="user.avatar" alt="" />
            <span v-else class="c-header__avatar c-header__avatar--blank" aria-hidden="true"></span>
            <span class="c-menu__nick">{{ displayName || '我的' }}</span>
          </p>
          <ul class="c-menu__list c-menu__list--small">
            <li v-for="link in mineLinks" :key="link.to">
              <RouterLink :to="link.to" class="c-menu__link" @click="closeMenu(false)">
                <span class="c-menu__roll">
                  <span>{{ link.label }}</span>
                  <span aria-hidden="true">{{ link.label }}</span>
                </span>
                <span v-if="link.note" class="c-menu__note">{{ link.note }}</span>
              </RouterLink>
            </li>
          </ul>
        </section>
      </nav>
    </Teleport>
  </header>
</template>

<style scoped>
.c-header {
  position: sticky;
  top: 0;
  z-index: 30;
  /* 三列：站名 / 主导航 / 个人入口。auto 列被两个 1fr 夹在正中，
     左右两块宽度怎么变（登录前后）都不会把中间挤偏。 */
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: var(--sp-3);
  height: var(--header-h);
  padding: 0 var(--sp-4);
}

/* 显式列号：手机上 .c-header__main 是 display:none，不写列号右块会落进中间列 */
.c-header__brand {
  grid-column: 1;
  justify-self: start;
  min-width: 0;
}

.c-header__main {
  grid-column: 2;
  display: none;
  align-items: center;
  gap: var(--sp-5);
}

.c-header__user {
  grid-column: 3;
  justify-self: end;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 0;
}

/* 编辑态的站名：省略号规则不适用（要能看见自己在打什么），其余外观同链接 */
.c-header__name.c-header__name--edit {
  overflow: visible;
  text-overflow: clip;
  white-space: normal;
}

.c-header__name {
  display: inline-block;
  min-height: 40px;
  line-height: 40px;
  /** 页面布局与交互。 */
  max-width: min(40vw, 24em);
  font-size: var(--fs-sm);
  letter-spacing: 0.12em;
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
}

.c-header__link {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  min-height: 40px;
  padding: 0;
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-mid);
  color: inherit;
  background: none;
  border: 0;
  border-bottom: 1px solid transparent;
  text-decoration: none;
  white-space: nowrap;
}

.c-header__bellink {
  min-width: 40px;
  justify-content: center;
}

/* 当前页：v2 用 currentColor 的一条下划线 */
.c-header__main .c-header__link.router-link-active {
  border-bottom-color: currentColor;
}

/* 编辑态：「编辑」按钮显示为按下状态（与当前页同一条下划线语言，再加一层底） */
.c-header__edit.is-on {
  padding: 0 var(--sp-2);
  border-bottom-color: currentColor;
  background: var(--glass-fill);
  border-radius: var(--radius);
}

.c-header__avatar {
  flex: none;
  width: 24px;
  height: 24px;
  border-radius: var(--radius-pill);
  object-fit: cover;
  border: 1px solid var(--glass-line);
}

.c-header__avatar--blank {
  background: var(--avatar-bg);
}

/* 未读角标（v2 .badge）：红底白字，不跟随玻璃的文字阴影 */
.c-header__badge {
  display: inline-grid;
  place-items: center;
  min-width: 16px;
  height: 16px;
  margin-left: var(--sp-1);
  padding: 0 var(--sp-1);
  font-size: var(--fs-2xs);
  letter-spacing: 0;
  color: var(--on-brand);
  background: var(--danger-strong);
  border-radius: var(--radius-pill);
  text-shadow: none;
}

.c-header__label {
  display: none;
}

/* ==========================================================================
   胶囊按钮（lusion.co 右上角口径）
   ========================================================================== */

.hbtn {
  position: relative;
  display: inline-flex;
  align-items: center;
  flex: none;
  height: 40px;
  padding: 0 var(--sp-4);
  overflow: hidden;
  font: inherit;
  font-size: var(--fs-sm);
  line-height: 1;
  letter-spacing: var(--ls-mid);
  white-space: nowrap;
  text-decoration: none;
  text-shadow: none;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  cursor: pointer;
  transition:
    background-color var(--dur-slow) ease,
    color var(--dur-slow) ease,
    border-color var(--dur-slow) ease;
}

/* 裁切框里的内容整体：入场时从下方升起（Mask Reveal） */
.hbtn__in {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  animation: hbtn-mask var(--dur-slide) var(--ease-roll) both;
}

.hbtn__in--late {
  animation-delay: 80ms;
}

@keyframes hbtn-mask {
  from {
    transform: translateY(120%);
  }

  to {
    transform: none;
  }
}

/* 焦点环画在里面：按钮本身 overflow:hidden，外扩的 outline 会被别的块压住 */
.hbtn:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: -4px;
}

/* ---- 主操作 ---- */
.hbtn--primary {
  color: var(--on-brand);
  background: var(--brand);
}

.hbtn--primary:hover,
.hbtn--primary:focus-visible {
  background: var(--brand-2);
}

.hbtn__arrow {
  position: absolute;
  left: 0;
  top: 50%;
  display: inline-flex;
  /* 起点在按钮左内边距之外（被 overflow:hidden 裁掉） */
  transform: translate(calc(-100% - var(--sp-4) - 2px), -50%);
  transition: transform var(--dur-roll) var(--ease-roll);
}

.hbtn__text {
  display: inline-block;
  transition: transform var(--dur-roll) var(--ease-roll);
}

.hbtn__dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-pill);
  background: currentColor;
  transition: transform var(--dur-roll) var(--ease-roll);
}

.hbtn--primary:hover .hbtn__arrow,
.hbtn--primary:focus-visible .hbtn__arrow {
  transform: translate(0, -50%);
}

.hbtn--primary:hover .hbtn__text,
.hbtn--primary:focus-visible .hbtn__text {
  transform: translateX(1.5em);
}

.hbtn--primary:hover .hbtn__dot,
.hbtn--primary:focus-visible .hbtn__dot {
  transform: scale(0);
}

/* 已登录的主操作：768–1199 右列放不下，只在 ≥1200 出现（菜单卡片里有同一条入口） */
.hbtn--wide-only {
  display: none;
}

/* ---- 菜单 ---- */
.hbtn--menu {
  color: var(--ink);
  background: var(--bg-2);
  border-color: var(--line-2);
}

.hbtn--menu:hover,
.hbtn--menu:focus-visible,
.hbtn--menu.is-open {
  background: var(--white);
}

.hbtn__dots {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  width: 12px;
  height: 12px;
  transition: transform var(--dur-roll) var(--ease-roll);
}

.hbtn__dots i {
  width: 4px;
  height: 4px;
  border-radius: var(--radius-pill);
  background: currentColor;
}

.hbtn--menu:hover .hbtn__dots,
.hbtn--menu:focus-visible .hbtn__dots,
.hbtn--menu.is-open .hbtn__dots {
  transform: rotate(90deg);
}

/* Text Roll：两行字叠在一个一行高的裁切框里，打开时一起上移一行 */
.hbtn__roll {
  display: inline-block;
  height: 1.4em;
  overflow: hidden;
  line-height: 1.4em;
}

.hbtn__roll > span {
  display: block;
  transition: transform var(--dur-roll) var(--ease-roll);
}

.hbtn--menu.is-open .hbtn__roll > span {
  transform: translateY(-100%);
}

/* ---- 变体：压在深色图上的玻璃（首页首屏） ---- */
.c-header--glass {
  color: var(--on-dark);
  background: linear-gradient(125deg, var(--glass-dark-1), var(--glass-dark-2));
  border-bottom: 1px solid var(--glass-line);
  box-shadow: var(--glass-shadow-dark);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  text-shadow: var(--text-shadow-dark);
}

/* 深色玻璃上主操作要最亮：墨绿实心压在深色图上反而比半透明的「菜单」更不显眼，
   这一档换成白底墨绿字；悬浮变成品牌淡底（仍是 0.4s 底色过渡） */
.c-header--glass .hbtn--primary {
  color: var(--brand);
  background: var(--white);
}

.c-header--glass .hbtn--primary:hover,
.c-header--glass .hbtn--primary:focus-visible {
  background: var(--bg-3);
}

.c-header--glass .hbtn--menu {
  color: var(--on-dark);
  background: var(--glass-fill);
  border-color: var(--glass-line);
}

.c-header--glass .hbtn--menu:hover,
.c-header--glass .hbtn--menu:focus-visible,
.c-header--glass .hbtn--menu.is-open {
  color: var(--ink);
  background: var(--white);
}

/* ---- 变体：其余页的浅色玻璃 ---- */
.c-header--light {
  color: var(--ink-soft);
  background: linear-gradient(130deg, var(--glass-light-1), var(--glass-light-2));
  border-bottom: 1px solid var(--line);
  box-shadow: var(--glass-shadow-light);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  text-shadow: none;
}

/* 不透明兜底：没有 backdrop-filter 的浏览器（微信 X5 / 老 Safari 未测）
   拿到的是半透明底 + 不模糊 = 糊成一片，所以这里整块换成不透明色。 */
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .c-header--glass {
    background: var(--glass-dark-solid);
  }

  .c-header--light {
    background: var(--glass-light-solid);
  }
}

/* ==========================================================================
   菜单面板：独立卡片，Teleport 到 body（scoped 属性随元素带过去，样式照常生效）
   ========================================================================== */

.c-menu-veil {
  position: fixed;
  inset: 0;
  z-index: 29;
  background: var(--scrim-1);
  opacity: 0;
  visibility: hidden;
  transition:
    opacity var(--dur-slow) ease,
    visibility 0s linear var(--dur-slow);
}

.c-menu-veil.is-open {
  opacity: 1;
  visibility: visible;
  transition:
    opacity var(--dur-slow) ease,
    visibility 0s;
}

.c-menu {
  position: fixed;
  z-index: 31;
  top: calc(var(--header-h) + var(--sp-2));
  /* 与顶栏左右内边距同宽，卡片右缘和菜单按钮右缘对齐 */
  right: calc(var(--sp-4) + var(--menu-scroll-comp, 0px));
  left: var(--sp-4);
  display: grid;
  gap: var(--sp-2);
  max-height: calc(100dvh - var(--header-h) - var(--sp-4));
  overflow-y: auto;
  visibility: hidden;
  pointer-events: none;
  /* 关闭时等卡片全部退场后再隐藏 */
  transition: visibility 0s linear calc(var(--dur-card) + var(--stagger) * 2);
}

.c-menu.is-open {
  visibility: visible;
  pointer-events: auto;
  transition: visibility 0s;
}

.c-menu__card {
  padding: var(--sp-4) var(--sp-5) var(--sp-5);
  color: var(--ink);
  background: var(--white);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-1);
  opacity: 0;
  transform: translateY(56px) rotate(var(--tilt));
  transform-origin: 50% 100%;
  /* 透明度约 120ms 先到位（飞入途中半透明的卡片会和底下页面文字重影），位移继续走满 0.5s */
  transition:
    transform var(--dur-card) var(--ease-roll),
    opacity calc(var(--dur-card) * 0.24) linear;
  /* 关闭反向错开：后入场的先退场 */
  transition-delay: calc((var(--n) - 1 - var(--i)) * var(--stagger));
}

.c-menu.is-open .c-menu__card {
  opacity: 1;
  transform: none;
  transition-delay: calc(var(--i) * var(--stagger));
}

.c-menu__head {
  margin: 0 0 var(--sp-3);
  padding-bottom: var(--sp-2);
  font-size: var(--fs-xs);
  font-weight: 400;
  letter-spacing: var(--ls-mid);
  color: var(--ink-muted);
  border-bottom: 1px solid var(--line);
}

.c-menu__who {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin: 0 0 var(--sp-2);
  font-size: var(--fs-sm);
  color: var(--ink-soft);
}

.c-menu__nick {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-menu__list {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}

.c-menu__link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  min-height: 44px;
  font-size: var(--fs-2xl);
  color: var(--ink);
  text-decoration: none;
}

.c-menu__list--small .c-menu__link {
  font-size: var(--fs-lg);
}

.c-menu__link[aria-current="page"] {
  color: var(--brand-ink);
}

.c-menu__link:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
  border-radius: var(--radius);
}

/* 链接悬浮：文字上移，同样的字从下方升入替换 */
.c-menu__roll {
  display: inline-block;
  height: 1.4em;
  overflow: hidden;
  line-height: 1.4em;
}

.c-menu__roll > span {
  display: block;
  transition: transform var(--dur-roll) var(--ease-roll);
}

.c-menu__roll > span + span {
  color: var(--brand-ink);
}

.c-menu__link:hover .c-menu__roll > span,
.c-menu__link:focus-visible .c-menu__roll > span {
  transform: translateY(-100%);
}

.c-menu__note {
  flex: none;
  padding: 0 var(--sp-2);
  font-size: var(--fs-2xs);
  line-height: 18px;
  color: var(--on-brand);
  background: var(--danger-strong);
  border-radius: var(--radius-pill);
}

@media (min-width: 768px) {
  .c-header {
    padding: 0 var(--sp-5);
    gap: var(--sp-5);
  }

  .c-header__main {
    display: flex;
  }

  .c-header__user {
    gap: var(--sp-3);
  }

  .c-header__label {
    display: inline;
  }

  .c-header__name {
    max-width: min(48vw, 24em);
  }

  /* 桌面：卡片列在右侧，遮罩只压右半屏（左边淡、右边暗） */
  .c-menu {
    left: auto;
    width: 380px;
    right: calc(var(--sp-5) + var(--menu-scroll-comp, 0px));
  }

  .c-menu-veil {
    background: linear-gradient(90deg, transparent 45%, var(--scrim-1) 70%, var(--scrim-2));
  }
}

@media (min-width: 1200px) {
  .hbtn--wide-only {
    display: inline-flex;
  }
}

/* 减少动态：取消一切位移（入场升起、箭头滑入、文字让位、圆点旋转、卡片飞入），
   只保留状态切换（底色、菜单/关闭两字的替换、卡片出现与消失）。 */
@media (prefers-reduced-motion: reduce) {
  .hbtn__in {
    animation: none;
  }

  .hbtn__arrow {
    display: none;
  }

  .hbtn--primary:hover .hbtn__text,
  .hbtn--primary:focus-visible .hbtn__text,
  .hbtn--primary:hover .hbtn__dot,
  .hbtn--primary:focus-visible .hbtn__dot,
  .hbtn--menu:hover .hbtn__dots,
  .hbtn--menu:focus-visible .hbtn__dots,
  .hbtn--menu.is-open .hbtn__dots {
    transform: none;
  }

  .c-menu__card {
    transform: none;
  }

  .c-menu__link:hover .c-menu__roll > span,
  .c-menu__link:focus-visible .c-menu__roll > span {
    transform: none;
  }

  .c-menu__link:hover {
    color: var(--brand-ink);
  }
}
</style>
