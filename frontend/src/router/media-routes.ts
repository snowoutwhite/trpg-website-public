/** 相册与战报的路由（W4c）。 */
import type { RouteRecordRaw } from 'vue-router'

export const mediaRoutes: RouteRecordRaw[] = [
  {
    path: '/games/:id/photos',
    name: 'game-photos',
    redirect: (to) => ({ path: '/games/' + to.params.id, hash: '#photos' }),
  },
  // —— 战报 ——
  {
    path: '/reports',
    name: 'reports',
    component: () => import('../views/ReportListView.vue'),
    meta: { title: '战报' },
  },
  {
    path: '/reports/:id',
    name: 'report-detail',
    component: () => import('../views/ReportDetailView.vue'),
    meta: { title: '战报' },
  },
  {
    path: '/games/:id/reports',
    name: 'game-reports',
    redirect: (to) => ({ path: '/games/' + to.params.id, hash: '#reports' }),
  },
  {
    path: '/games/:id/reports/edit',
    name: 'game-report-edit',
    component: () => import('../views/ReportEditView.vue'),
    meta: { title: '写战报', requiresAuth: true },
  },
  // —— 「我的」子项 ——
  {
    path: '/me/reports',
    name: 'my-reports',
    component: () => import('../views/MyReportsView.vue'),
    meta: { title: '我的战报', requiresAuth: true },
  },
  {
    path: '/me/photo-reports',
    name: 'my-photo-reports',
    redirect: { path: '/me', hash: '#records-abuse' },
  },
]
