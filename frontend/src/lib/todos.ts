/** 「我的当下 / 待办」的**唯一一份数据来源**。 */
import { fetchAllMySignups, fetchGame, fetchGames } from '../api/games'
import { fetchPendingReviews } from '../api/reviews'
import { fetchUnreadCount } from '../api/notifications'
import { formatDateTime } from './datetime'

const DAY_MS = 86_400_000

/** 还剩几天（不足一天算 1 天，已过期算 0）。v2 `shared.js` 的 `daysLeft()` 同口径。 */
export function daysLeft(iso: string | null | undefined): number {
  if (!iso) return 0
  const target = new Date(iso).getTime()
  if (Number.isNaN(target)) return 0
  return Math.max(0, Math.ceil((target - Date.now()) / DAY_MS))
}

/** 一张待办卡。`days` + `unit` 是卡片右侧那个大数字。 */
export interface TodoCard {
  key: string
  kicker: string
  title: string
  small: string
  days: number
  unit: string
  urgent: boolean
  to: string
}

export interface TodoOptions {
  /** 本人是否有 GM 身份：决定要不要去查「相册可传」。 */
  isGm: boolean
  /** 本人 id；没有就跳过「相册可传」那一路。 */
  userId: number | null
  /** 站级相册上传窗口天数（`siteconfig.gallery_upload_window_days`）。 */
  galleryUploadWindowDays: number
}

/** 待交卡：报名还停在 pending 且此团要求交卡。 */
async function cardsToSubmit(): Promise<TodoCard[]> {
  const out: TodoCard[] = []
  try {
    // 翻页取全：默认一页 20 条，报名一多就漏掉待交卡（与缺陷 F11 同病）
    const mine = await fetchAllMySignups()
    for (const item of mine) {
      if (item.status !== 'pending' || !item.game.requires_card) continue
      const left = daysLeft(item.game.card_deadline)
      out.push({
        key: 'card-' + item.id,
        kicker: '待交卡',
        days: left,
        unit: '天',
        urgent: left <= 3,
        title: '给「' + item.game.title + '」交角色卡',
        small: '截止 ' + formatDateTime(item.game.card_deadline) + '，逾期视为放弃席位',
        to: '/games/' + item.game.id,
      })
    }
  } catch {
    // 拿不到就少这几张卡
  }
  return out
}

/** 待评价：窗口由后端给（`window_ends_at`）。 */
async function reviewsToWrite(): Promise<TodoCard[]> {
  const out: TodoCard[] = []
  try {
    const pending = await fetchPendingReviews()
    for (const group of pending.results) {
      out.push({
        key: 'review-' + group.game.id,
        kicker: '待评价',
        days: daysLeft(group.window_ends_at),
        unit: '天',
        urgent: false,
        title: '给「' + group.game.title + '」的同伴留评价',
        small: '还有 ' + group.targets.length + ' 位同伴可评，匿名，每人只能评一次',
        to: '/games/' + group.game.id + '#reviews',
      })
    }
  } catch {
    // 同上
  }
  return out
}

/**
 * 相册可传（GM）：本人主持 + 已结团 + 还在上传窗口内。
 * 列表项没有 `finished_at`（`GameListItem` 里就没这个字段），所以对本人主持的已结团的团
 * **逐个取详情**拿结团时间，最多 10 个 —— 不值得为这一张卡把整页请求数放大。
 */
async function galleryOpen(options: TodoOptions): Promise<TodoCard[]> {
  const out: TodoCard[] = []
  if (!options.isGm || !options.userId) return out
  try {
    const hosted = await fetchGames({
      gm: options.userId,
      status: 'finished',
      ordering: '-start_at',
      page_size: 10,
    })
    const settled = await Promise.allSettled(
      hosted.results.slice(0, 10).map((g) => fetchGame(g.id)),
    )
    const windowDays = options.galleryUploadWindowDays
    for (const one of settled) {
      if (one.status !== 'fulfilled') continue
      const detail = one.value
      if (!detail.finished_at) continue
      const ends = new Date(detail.finished_at).getTime() + windowDays * DAY_MS
      const left = Math.max(0, Math.ceil((ends - Date.now()) / DAY_MS))
      if (left <= 0) continue
      out.push({
        key: 'gallery-' + detail.id,
        kicker: '相册可传',
        days: left,
        unit: '天',
        urgent: false,
        title: '上传「' + detail.title + '」的活动照片',
        small: '你是此团的 GM，结团后 ' + windowDays + ' 天内可传',
        to: '/games/' + detail.id + '#photos',
      })
    }
  } catch {
    // 同上
  }
  return out
}

/** 未读通知：永远给一张，没有未读就写「没有新通知」。 */
async function notificationCard(): Promise<TodoCard> {
  let unread = 0
  try {
    unread = (await fetchUnreadCount()).unread
  } catch {
    // 同上
  }
  return {
    key: 'notifications',
    kicker: '通知',
    days: unread,
    unit: '未读',
    urgent: false,
    title: unread ? '有 ' + unread + ' 条新消息' : '没有新通知',
    small: '报名结果、开团提醒、评价开放等站内消息',
    to: '/me#account',
  }
}

/**
 * 拼出当前登录者的全部待办卡。**调用方负责先确认已登录**（未登录时这些接口会 401）。
 * 四路顺序发：`my-signups` 与 `pending` 很轻，`galleryOpen` 自带并发。
 */
export async function loadTodoCards(options: TodoOptions): Promise<TodoCard[]> {
  const cards: TodoCard[] = []
  cards.push(...(await cardsToSubmit()))
  cards.push(...(await reviewsToWrite()))
  cards.push(...(await galleryOpen(options)))
  cards.push(await notificationCard())
  return cards
}
