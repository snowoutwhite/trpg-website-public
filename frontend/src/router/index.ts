/**
 * 路由表。
 *
 * 与后端 HEADLESS_FRONTEND_URLS 的对应关系（键名取自 allauth 65.19.4 源码）：
 *   account_confirm_email           -> /auth/verify-email/{key}
 *   account_reset_password          -> /auth/password/forgot
 *   account_reset_password_from_key -> /auth/password/reset/{key}
 *   account_signup                  -> /auth/signup
 * 改动这几条路径时必须同步改后端设置，否则邮件里的链接会 404。
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { setUnauthorizedHandler } from '../api/http'
import { useAuthStore } from '../stores/auth'
import { mediaRoutes } from './media-routes'

declare module 'vue-router' {
  interface RouteMeta {
    /** 页面标题，拼在站名前。 */
    title?: string
    /** 必须登录才能进。 */
    requiresAuth?: boolean
    /** 已登录就不该再进（登录/注册页）。 */
    guestOnly?: boolean
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: () => import('../views/HomeView.vue'),
    meta: { title: '首页', headerVariant: 'glass', flush: true },
  },
  {
    path: '/announcements',
    name: 'announcements',
    component: () => import('../views/AnnouncementsView.vue'),
    meta: { title: '站长公告' },
  },
  {
    path: '/auth/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { title: '登录', guestOnly: true },
  },
  {
    path: '/auth/signup',
    name: 'signup',
    component: () => import('../views/SignupView.vue'),
    meta: { title: '注册', guestOnly: true },
  },
  {
    path: '/auth/verify-email/:key?',
    name: 'verify-email',
    component: () => import('../views/VerifyEmailView.vue'),
    meta: { title: '验证邮箱' },
  },
  {
    path: '/auth/password/forgot',
    name: 'password-forgot',
    component: () => import('../views/PasswordForgotView.vue'),
    meta: { title: '找回密码' },
  },
  {
    path: '/auth/password/reset/:key?',
    name: 'password-reset',
    component: () => import('../views/PasswordResetView.vue'),
    meta: { title: '重置密码' },
  },
  // 所以挂 `flush`（`App.vue` → `.l-main--flush`），左右留白由页内各段自己的 `--pad` 给。
  // 四组靠 hash 直达：`#games-hosted` / `#cards-player` / `#records-reviews` / `#account`。
  {
    path: '/me',
    name: 'me',
    component: () => import('../views/MeView.vue'),
    meta: { title: '我的', requiresAuth: true, flush: true },
  },
  // —— 内容区（游客可读）——
  {
    path: '/guide',
    name: 'guide',
    component: () => import('../views/GuideListView.vue'),
    meta: { title: '新人指南' },
  },
  {
    path: '/guide/:slug',
    name: 'guide-detail',
    component: () => import('../views/GuideDetailView.vue'),
    meta: { title: '新人指南' },
  },
  {
    path: '/faq',
    name: 'faq',
    component: () => import('../views/FaqView.vue'),
    meta: { title: '常见问题' },
  },
  {
    path: '/glossary',
    name: 'glossary',
    component: () => import('../views/GlossaryView.vue'),
    meta: { title: '术语速查' },
  },
  // —— 资源区（列表详情游客可读，下载需登录）——
  {
    path: '/resources',
    name: 'resources',
    component: () => import('../views/ResourceListView.vue'),
    meta: { title: '资源区' },
  },
  {
    path: '/resources/:id',
    name: 'resource-detail',
    component: () => import('../views/ResourceDetailView.vue'),
    meta: { title: '资源' },
  },
  // —— 角色卡池 ——
  {
    path: '/cards',
    name: 'cards',
    component: () => import('../views/CardPoolView.vue'),
    meta: { title: '角色卡池' },
  },
  {
    path: '/cards/:id',
    name: 'card-detail',
    component: () => import('../views/CardDetailView.vue'),
    meta: { title: '角色卡' },
  },
  // —— 个人空间（公开）——
  {
    path: '/users/:id',
    name: 'user-profile',
    component: () => import('../views/UserProfileView.vue'),
    meta: { title: '个人空间', flush: true },
  },
  // —— 我的（全部需要登录）——
  {
    path: '/me/cards',
    name: 'my-cards',
    component: () => import('../views/MyCardsView.vue'),
    meta: { title: '我的角色卡', requiresAuth: true },
  },
  {
    path: '/me/cards/:id',
    name: 'my-card-detail',
    component: () => import('../views/MyCardDetailView.vue'),
    meta: { title: '我的角色卡', requiresAuth: true },
  },
  {
    path: '/me/player-card',
    name: 'my-player-card',
    component: () => import('../views/PlayerCardEditView.vue'),
    meta: { title: '玩家卡', requiresAuth: true },
  },
  {
    path: '/me/gm-card',
    name: 'my-gm-card',
    component: () => import('../views/GmCardEditView.vue'),
    meta: { title: 'GM 卡', requiresAuth: true },
  },
  // 路径保留为**纯重定向**：站内旧链接、通知里发出去的地址、用户收藏都还能用。
  // 守卫不用再写 `requiresAuth`：落点 `/me` 自己就是 `requiresAuth`，游客一样会被挡在登录页。
  // （`npm run security` 的断言同步从 MUST_REQUIRE_AUTH 移到 MUST_REDIRECT，见 scripts/xss-entry.mjs）
  {
    path: '/me/notifications',
    name: 'notifications',
    redirect: { path: '/me', hash: '#account' },
  },
  {
    path: '/me/account',
    name: 'account-settings',
    redirect: { path: '/me', hash: '#account' },
  },
  // —— 团与招募（列表详情游客可读，写操作需登录）——
  {
    path: '/recruit',
    name: 'recruit',
    component: () => import('../views/RecruitListView.vue'),
    meta: { title: '招募' },
  },
  // `/games/new` 必须排在 `/games/:id` 之前，否则 new 会被当成 id
  {
    path: '/games/new',
    name: 'game-new',
    component: () => import('../views/GameFormView.vue'),
    meta: { title: '放团', requiresAuth: true },
  },
  // `headerVariant: 'glass'` + `flush`；六个标签靠 hash 直达（`#photos` / `#manage`…）。
  {
    path: '/games/:id',
    name: 'game-detail',
    component: () => import('../views/GameDetailView.vue'),
    meta: { title: '团', headerVariant: 'glass', flush: true },
  },
  {
    path: '/games/:id/edit',
    name: 'game-edit',
    component: () => import('../views/GameFormView.vue'),
    meta: { title: '改公告', requiresAuth: true },
  },
  // 路径保留为重定向：站内旧链接、用户收藏、通知里发出去的地址都还能用。
  // 守卫不用再加 `requiresAuth`：目标页对游客开放，进去之后那一格自己说「需要登录」。
  {
    path: '/games/:id/manage',
    name: 'game-manage',
    redirect: (to) => ({ path: '/games/' + to.params.id, hash: '#manage' }),
  },
  {
    path: '/games/:id/mutual',
    name: 'game-mutual',
    redirect: (to) => ({ path: '/games/' + to.params.id, hash: '#mutual' }),
  },
  {
    path: '/me/signups',
    name: 'my-signups',
    redirect: { path: '/me', hash: '#games-signups' },
  },
  {
    path: '/me/games',
    name: 'my-games',
    redirect: { path: '/me', hash: '#games-hosted' },
  },
  {
    path: '/me/reviews',
    name: 'my-reviews',
    redirect: { path: '/me', hash: '#records-reviews' },
  },
  // —— 相册与战报（W4c，路由表在 router/media-routes.ts）——
  ...mediaRoutes,
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('../views/NotFoundView.vue'),
    meta: { title: '找不到页面' },
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  /** 换页面回顶部、前进后退复原位置；**同一个 path 只换 hash / query 的导航一律不滚**。 */
  scrollBehavior: (to, from, saved) => {
    if (to.path === from.path && to.fullPath !== from.fullPath) return false
    return saved ?? { top: 0 }
  },
})

// http 层遇到 401 时统一跳登录，并记下原地址
setUnauthorizedHandler(() => {
  const current = router.currentRoute.value
  if (current.name === 'login') return
  void router.push({ name: 'login', query: { next: current.fullPath } })
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth || to.meta.guestOnly) {
    await auth.refresh()
  }
  if (to.meta.requiresAuth && auth.authenticated !== true) {
    return { name: 'login', query: { next: to.fullPath } }
  }
  if (to.meta.guestOnly && auth.authenticated === true) {
    return { name: 'me' }
  }
  return true
})
