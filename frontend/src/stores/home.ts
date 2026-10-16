/**
 * 站长内容 store：`GET /api/v1/home/` 的一次性缓存。
 *
 * 为什么不并进 `stores/site.ts`：`/siteconfig/` 是**与登录态无关**的站级开关，全站只拉一次；
 * 本接口的 `announcement.is_read` 与 `featured_photos`（members 可见范围）**都依赖登录态**，
 * 登录/登出之后必须重拉。两者生命周期不同，合在一起只会让 site store 跟着登录态抖动，
 * 把现有 6 处 `useSiteStore()` 调用方一并拖下水。
 *
 * 拉取时机（`App.vue` 负责触发）：等 `auth.ready` 为真再拉，所以**应用启动只拉一次**；
 * 之后 `auth.authenticated` 一变（登录 / 登出 / 会话失效）就按新身份重拉。
 *
 * 失败不阻断渲染：`content` 保持 null，调用方按「这段没有内容」处理，
 * 与 `stores/site.ts` 的兜底口径一致。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { fetchHome, type HomeContent, type RuleSystemPreset } from '../api/home'
import { markRead } from '../api/notifications'

export const useHomeStore = defineStore('home', () => {
  const content = ref<HomeContent | null>(null)
  const loading = ref(false)
  const error = ref('')
  /** 上一次拉取时的登录态；`undefined` 表示从没拉过。 */
  const loadedFor = ref<boolean | null | undefined>(undefined)

  let inflight: Promise<void> | null = null

  const site = computed(() => content.value?.site ?? null)
  const rulePresets = computed<RuleSystemPreset[]>(() => content.value?.rule_presets ?? [])
  const quickEntries = computed(() => content.value?.quick_entries ?? [])
  const announcement = computed(() => content.value?.announcement ?? null)
  const featuredPhotos = computed(() => content.value?.featured_photos ?? null)

  /** 页脚署名句；接口没回来时给空串，页脚自己判断显不显示。 */
  const footerTagline = computed(() => site.value?.footer_tagline ?? '')

  /**
   * 公告是否该弹给当前用户看：有公告、且本人确实收到过那条通知、且还没读。
   * `is_read === null`（游客 / 公告推送时还没注册）一律不打扰。
   */
  const announcementUnread = computed(() => announcement.value?.is_read === false)

  /** 按规则名取预设（大小写不敏感，与后端「其他」筛选的比较口径一致）。 */
  function presetByName(name: string | null | undefined): RuleSystemPreset | null {
    const key = (name ?? '').trim().toLowerCase()
    if (!key) return null
    return rulePresets.value.find((p) => p.name.trim().toLowerCase() === key) ?? null
  }

  /**
   * 按登录态拉取。同一个登录态重复调用直接返回缓存；`force` 用于站主改完内容后自刷。
   *
   * @param authenticated 当前登录态（`stores/auth.ts` 的 `authenticated`）
   */
  async function load(authenticated: boolean | null, force = false): Promise<void> {
    if (!force && loadedFor.value === authenticated && content.value !== null) return
    // force（站主改完内容自刷）要拿到改动后的数据：等在飞的那次结束再重拉，而不是复用它
    if (inflight) {
      if (!force) return inflight
      await inflight
    }
    inflight = (async () => {
      loading.value = true
      try {
        content.value = await fetchHome()
        error.value = ''
      } catch {
        // 后端不可用时不阻断页面：首页各段自己按「没有内容」渲染。
        error.value = '首页内容暂时无法读取，请刷新后重试。'
      } finally {
        loadedFor.value = authenticated
        loading.value = false
        inflight = null
      }
    })()
    return inflight
  }

  /**
   * 站长公告「知道了」：把对应的**站内通知**标已读（已读的真源在通知，不在公告）。
   * 没有 `notification_id`（游客 / 没收到通知）时什么都不做。
   */
  async function dismissAnnouncement(): Promise<void> {
    const current = announcement.value
    if (!current || current.notification_id === null || current.is_read !== false) return
    // 先落本地，避免网络慢时横幅赖着不走；失败了下次重拉会把真值带回来。
    current.is_read = true
    try {
      await markRead([current.notification_id])
    } catch {
      current.is_read = false
    }
  }

  return {
    content,
    loading,
    error,
    site,
    rulePresets,
    quickEntries,
    announcement,
    announcementUnread,
    featuredPhotos,
    footerTagline,
    presetByName,
    load,
    dismissAnnouncement,
  }
})
