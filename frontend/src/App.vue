<script setup lang="ts">
/** 应用外壳：玻璃顶栏 + 主体 + 页脚 + 手机底栏 四段（v2）。 */
import { computed, onMounted, watch, ref, nextTick, onBeforeUnmount } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import AppHeader from './components/AppHeader.vue'
import AppFooter from './components/AppFooter.vue'
import BottomNav from './components/BottomNav.vue'
import EditBar from './components/edit/EditBar.vue'
import { useSiteStore } from './stores/site'
import { useHomeStore } from './stores/home'
import { useAuthStore } from './stores/auth'
import { useEditStore } from './stores/edit'

const route = useRoute()
const router = useRouter()
const site = useSiteStore()
const home = useHomeStore()
const auth = useAuthStore()
const edit = useEditStore()
const { config } = storeToRefs(site)
const { ready, authenticated } = storeToRefs(auth)

/** 顶栏变体：路由 meta 给 `glass` 的页（首页）在**滚过首屏之后**切回 `light`， */
const scrolledPastHero = ref(false)
let rafPending = false
function measureHero() {
  rafPending = false
  const hero = document.querySelector<HTMLElement>('[data-hero]')
  if (!hero) {
    // 站长内容还在加载 → 首屏尚未渲染，先按 meta 走（避免闪一下浅色）；
    // 已加载完（成功但无预设、或失败只剩一条提示）仍没有首屏 → 必须回落浅色，
    // 否则白字压白底 1.14:1（复检 2026-09-22 打桩 /home/ 500 发现）。
    scrolledPastHero.value = !home.loading && (home.content !== null || home.error !== '')
    return
  }
  const headerH = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--header-h')) || 54
  scrolledPastHero.value = hero.getBoundingClientRect().bottom <= headerH
}
function onScroll() {
  if (rafPending) return
  rafPending = true
  requestAnimationFrame(measureHero)
}
const headerVariant = computed(() =>
  route.meta.headerVariant === 'glass' && !scrolledPastHero.value ? 'glass' : 'light',
)
watch(
  () => route.path,
  () => {
    scrolledPastHero.value = false
    // 路由切完等首屏挂上再量一次（首屏块由页面自己渲染）
    void nextTick(() => setTimeout(measureHero, 0))
  },
)
/** 通栏页（首页）：主体不要左右与顶部留白，留白由页面内的 `.l-section` 各段自己给。 */
const flush = computed(() => route.meta.flush === true)

/**
 * 未保存的编辑草稿：关页/刷新前拦一次。
 *
 * 浏览器只认「事件里调了 `preventDefault()` 或写了 `returnValue`」这一条，
 * 自定义文案早就不显示了（各家都换成了自己的默认话术），所以这里只设标记。
 */
function onBeforeUnload(event: BeforeUnloadEvent): void {
  if (!edit.active || !edit.dirty) return
  event.preventDefault()
  event.returnValue = ''
}

/** 路由守卫的注销函数（`router.beforeEach` 返回它）。 */
let removeGuard: (() => void) | null = null

onBeforeUnmount(() => {
  bodyObserver?.disconnect()
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', onScroll)
  window.removeEventListener('beforeunload', onBeforeUnload)
  removeGuard?.()
})

let bodyObserver: ResizeObserver | null = null
onMounted(() => {
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('resize', onScroll, { passive: true })
  window.addEventListener('beforeunload', onBeforeUnload)
  /**
   * 编辑态有未保存改动时，拦住任何跳转。
   *
   * 写在这里而不是 `router/index.ts`：那份路由表本波不碰（任务书文件边界），
   * 而且这条守卫的生命周期跟外壳一样长，注销函数正好交给 `onBeforeUnmount`。
   * 拦下之后把目标路径交给保存条去问一次（不用 `window.confirm`）。
   */
  removeGuard = router.beforeEach((to, from) => {
    if (!edit.active || !edit.dirty) return true
    if (to.fullPath === from.fullPath) return true
    // `http.ts` 收到 401 会自动 push 登录页：这不是用户要离开，是会话没了。
    // 拦下但**不**摆「离开本页」问询（第一颗按钮是「放弃改动并离开」，照着点就丢稿），
    if (to.name === 'login') {
      edit.authLost = true
      return false
    }
    edit.pendingLeave = to.fullPath
    return false
  })
  // 首屏是异步数据渲染出来的，内容高度一变就重量一次（不用轮询）
  if ('ResizeObserver' in window) {
    bodyObserver = new ResizeObserver(onScroll)
    bodyObserver.observe(document.body)
  }
  setTimeout(measureHero, 0)
  void site.load()
  // 先拿一次会话：顺带让后端下发 csrftoken Cookie，写操作才有 CSRF 头可带。
  void auth.refresh()
})

// 会话状态一确定就拉站长内容；之后登录/登出各重拉一次。
watch(
  [ready, authenticated],
  ([isReady, isAuthed]) => {
    if (!isReady) return
    void home.load(isAuthed)
  },
  { immediate: true },
)

// 标题跟随路由与站名
watch(
  [() => route.meta.title, config, () => home.site?.site_name],
  ([title, cfg, homeName]) => {
    const name = homeName || cfg.site_name
    document.title = title ? title + ' · ' + name : name
  },
  { immediate: true },
)

/**
 * 顶栏「编辑」（只有 `is_staff` 看得到这颗按钮）。
 *
 * 编辑态只在首页有意义（能改的东西全在首页与页脚），所以在别的页点它先回首页。
 * 已经在编辑态时再点一次 = 退出；有未保存改动时 `edit.exit()` 不会直接退，
 * 而是让保存条问一次（口径见 `stores/edit.ts`）。
 * `edit.enter()` 自己会判 `is_staff`，这里不重复判。
 */
async function onEdit(): Promise<void> {
  if (edit.active) {
    edit.exit()
    return
  }
  if (route.path !== '/') await router.push('/')
  await edit.enter()
}
</script>

<template>
  <AppHeader :variant="headerVariant" @edit="onEdit" />
  <main class="l-main" :class="{ 'l-main--flush': flush }">
    <RouterView v-slot="{ Component }">
      <component :is="Component" :key="route.path" />
    </RouterView>
  </main>
  <!-- 页脚在编辑态下也进入可编辑（站名与署名句），并自己让开保存条的高度 -->
  <AppFooter />
  <!-- 编辑态把手机底栏藏掉：保存条也是 fixed 的，两条叠在一起谁也点不准 -->
  <BottomNav v-if="!edit.active" />
  <EditBar v-if="edit.active" />
</template>
