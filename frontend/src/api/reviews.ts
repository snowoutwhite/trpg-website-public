/**
 * 团后评价（apps/reviews）。字段核对自 apps/reviews/{urls,serializers,views,services}.py。
 *
 * **匿名红线（前端侧）**：`AnonymousReview` 就是后端白名单序列化器的全部字段 ——
 * 没有 id、没有 created_at、没有 reviewer。前端**不得**给收到的评价编号、排序、
 * 或把它和任何时间线索并排显示；接口若哪天多回了这类字段，要上报后端删，不是在前端藏。
 */
import { request } from './http'
import type { PublicUser } from './site'

export type Verdict = 'like' | 'dislike'
/** 被评者在该团里的身份：进 GM 卡还是进玩家卡。 */
export type RevieweeRole = 'gm' | 'pl'

/** 评价里附带的团信息：只有标题与日期，没有名单。 */
export interface ReviewGame {
  id: number
  title: string
  start_at: string
  finished_at: string | null
}

/** 被评者 / 互见面板看到的评价：白名单四项（外加一个展示用的中文档位）。 */
export interface AnonymousReview {
  verdict: Verdict
  verdict_display: string
  text: string
  reviewee_role: RevieweeRole
  game: ReviewGame
}

/** 本人发出的评价：带 reviewee（本人当然知道自己评了谁）。 */
export interface GivenReview {
  id: number
  game: ReviewGame
  reviewee: PublicUser
  reviewee_role: RevieweeRole
  verdict: Verdict
  verdict_display: string
  text: string
  created_at: string
  updated_at: string
}

export interface PendingTarget {
  user: PublicUser
  role: RevieweeRole
  role_display: string
}

export interface PendingGame {
  game: ReviewGame
  window_ends_at: string
  targets: PendingTarget[]
}

export interface ReceivedReviews {
  results: AnonymousReview[]
  /** 已收到但还没到延迟可见门槛的条数；只有数字，没有团、没有时间。 */
  hidden_count: number
  visible_after_games: number
}

export interface MutualGroup {
  user: PublicUser
  role: RevieweeRole
  reviews: AnonymousReview[]
}

export interface MutualPanel {
  game: ReviewGame
  /** false = 互见没开、本人不是到场成员，或本人对该团的延迟还没过。 */
  available: boolean
  visible_after_games: number
  groups: MutualGroup[]
}

export interface ReviewQuota {
  quota: number
  used: number
  remaining: number
  like_feature_enabled: boolean
}

const BASE = '/api/v1/reviews'

/** 窗口内重复提交 = 修改（后端是 upsert）；没有撤回接口，不提交就是「无评价」。 */
export function submitReview(payload: {
  game: number
  reviewee: number
  verdict: Verdict
  text: string
}): Promise<GivenReview> {
  return request<GivenReview>(BASE + '/', { method: 'POST', body: payload })
}

export function fetchPendingReviews(): Promise<{ results: PendingGame[] }> {
  return request<{ results: PendingGame[] }>(BASE + '/pending/')
}

export function fetchGivenReviews(): Promise<{ results: GivenReview[] }> {
  return request<{ results: GivenReview[] }>(BASE + '/mine/given/')
}

export function fetchReceivedReviews(): Promise<ReceivedReviews> {
  return request<ReceivedReviews>(BASE + '/mine/received/')
}

export function fetchMutualPanel(gameId: number | string): Promise<MutualPanel> {
  return request<MutualPanel>(BASE + '/games/' + gameId + '/mutual/')
}

export function fetchReviewQuota(): Promise<ReviewQuota> {
  return request<ReviewQuota>(BASE + '/quota/')
}
