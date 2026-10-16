/**
 * 团（apps/games）：招募列表、团详情、放团/改团、报名与交卡、GM 管理动作、场次。
 *
 * 字段与路径**逐条核对自后端代码**（2026-09-21 W4b）：
 *   apps/games/urls.py、serializers.py、views.py、models.py。
 *
 * 隐私口径（后端定，前端只是照着用，不得自行放宽）：
 * - 游客能读列表与详情，但**详情里没有任何报名者身份**；名单接口游客 401。
 * - 招募中名单 `GET <id>/signups/` 登录可见；正式名单 `GET <id>/roster/` 只给同团，
 *   GM 拿到的是全量（含卡的 download_url 与审批备注），PL 拿到的是去掉卡的 accepted 名单。
 */
import { buildUrl, request, upload } from './http'
import type { Paginated, PublicUser } from './site'

// --------------------------------------------------------------------------
// 枚举（值与 apps/games/models.py 的常量一致）
// --------------------------------------------------------------------------

export type GameStatus = 'recruiting' | 'closed_signup' | 'running' | 'finished' | 'cancelled'
export type GameMode = 'online' | 'offline'
export type SignupMode = 'first_come' | 'pool_review'
export type SignupStatus =
  | 'pending'
  | 'submitted'
  | 'accepted'
  | 'rejected'
  | 'withdrawn'
  | 'removed'
  | 'no_card'

/** 赞级别五档（apps/profiles/levels.py），放团时的「最低赞级别」门槛用它。 */
export const LEVEL_OPTIONS: { value: string; label: string }[] = [
  { value: 'overwhelmingly_positive', label: '好评如潮' },
  { value: 'mostly_positive', label: '好评居多' },
  { value: 'mixed', label: '中性' },
  { value: 'mostly_negative', label: '倒赞居多' },
  { value: 'overwhelmingly_negative', label: '差评如潮' },
]

export const GAME_STATUS_OPTIONS: { value: GameStatus | ''; label: string }[] = [
  { value: '', label: '全部' },
  { value: 'recruiting', label: '招募中' },
  { value: 'closed_signup', label: '报名已满' },
  { value: 'running', label: '进行中' },
  { value: 'finished', label: '已结团' },
  { value: 'cancelled', label: '已取消' },
]

/**
 * 招募列表的排序白名单（`backend/apps/games/views.py:111-116` 的 `GAME_ORDERING_WHITELIST`）。
 * 白名单之外的值后端静默回落到默认档，不报错。
 */
export type GameOrdering = 'start_at' | '-start_at' | '-created_at'

export const GAME_ORDERING_DEFAULT: GameOrdering = '-created_at'

export const GAME_ORDERING_OPTIONS: { value: GameOrdering; label: string }[] = [
  { value: '-created_at', label: '最新发布' },
  { value: 'start_at', label: '开团时间由近到远' },
  { value: '-start_at', label: '开团时间由远到近' },
]

// --------------------------------------------------------------------------
// 读取用的形状
// --------------------------------------------------------------------------

/** GM 面板上的公开 GM 卡（apps/profiles PublicGMCardSerializer）。档位未公布时 likes/dislikes 为 null。 */
export interface PublicGMCard {
  style_text: string
  games_hosted: number
  /** 被评数未达公布阈值（或站主关掉赞功能）时后端回 null，见 apps/profiles/serializers.py `_MaskedCountsMixin`。 */
  reviews_received: number | null
  likes: number | null
  dislikes: number | null
  level: string
  level_display: string
}

export interface GameSession {
  id: number
  index: number
  label: string
  display_label: string
  held_at: string | null
}

/** 交上来的卡：只在 GM 视角与本人视角出现，且只给鉴权下载路径。 */
export interface SignupCard {
  id: number
  name: string
  rule_system: string
  status: string
  download_url: string
}

export interface GameListItem {
  id: number
  gm: PublicUser
  title: string
  rule_system: string
  start_at: string
  mode: GameMode
  mode_display: string
  location: string
  tags: string[]
  min_players: number
  max_players: number
  signup_mode: SignupMode
  signup_mode_display: string
  min_play_count: number | null
  min_level: string
  min_level_display: string
  requires_card: boolean
  card_deadline: string
  status: GameStatus
  status_display: string
  occupied_seats: number
  accepted_count: number
  is_full: boolean
  created_at: string
}

/** 我的报名里附带的团摘要（MySignupSerializer.get_game）。 */
export interface SignupGameBrief {
  id: number
  title: string
  status: GameStatus
  status_display: string
  start_at: string
  card_deadline: string
  requires_card: boolean
  signup_mode: SignupMode
}

export interface MySignup {
  id: number
  game: SignupGameBrief
  order: number
  status: SignupStatus
  status_display: string
  card: SignupCard | null
  card_uploaded_by_gm: boolean
  card_submitted_at: string | null
  review_note: string
  withdraw_requested_at: string | null
  attended: boolean
  created_at: string
}

export interface GameDetail extends GameListItem {
  announcement: string
  requirements: string
  mutual_review: boolean
  campaign_prev: { id: number; title: string } | null
  restrict_to_prev_members: boolean
  cancel_reason: string
  finished_at: string | null
  gm_card: PublicGMCard | null
  sessions: GameSession[]
  /**
   * 评价窗口截止时刻 = 结团时间 + 站级 `review_window_days`；没结团为 null。
   * 后端算好下发（`GameDetailSerializer.get_review_window_ends_at`），
   * **前端不要自己拿 finished_at 再算一遍**，天数是站级可配项，算错会和后端给出相反的提示。
   */
  review_window_ends_at: string | null
  /** 登录者自己的那条报名；游客与未报名者为 null。 */
  my_signup: MySignup | null
  can_signup: boolean
  updated_at: string
}

/** 招募中名单的一条（登录可见）：只有昵称头像与报名顺序。 */
export interface RecruitingSignup {
  id: number
  order: number
  player: PublicUser
  status: SignupStatus
  status_display: string
  created_at: string
}

/** 正式名单的一条（同团可见）。 */
export interface RosterSignup extends RecruitingSignup {
  attended: boolean
}

/** GM 面板名单：全部状态 + 卡 + 审批备注 + 退出申请。 */
export interface GMSignup extends RosterSignup {
  card: SignupCard | null
  card_uploaded_by_gm: boolean
  card_submitted_at: string | null
  review_note: string
  withdraw_requested_at: string | null
  withdraw_reason: string
}

export interface RecruitingRoster {
  count: number
  accepted_count: number
  max_players: number
  results: RecruitingSignup[]
}

/** `is_gm` 决定 results 是 GMSignup[] 还是 RosterSignup[]。 */
export interface RosterResponse {
  is_gm: boolean
  results: RosterSignup[] | GMSignup[]
}

export interface GameTag {
  id: number
  name: string
  is_preset: boolean
}

/** 放团 / 改团的入参（GameWriteSerializer 的字段集合）。 */
export interface GameWrite {
  title?: string
  announcement?: string
  rule_system?: string
  /** ISO 串；表单里用 datetime-local，提交前经 lib/datetime.fromLocalInput 转换。 */
  start_at?: string | null
  mode?: GameMode
  location?: string
  requirements?: string
  tags?: string[]
  min_players?: number
  max_players?: number
  signup_mode?: SignupMode
  /** null = 不设这道门槛。 */
  min_play_count?: number | null
  /** 空串 = 不设这道门槛。 */
  min_level?: string
  requires_card?: boolean
  /** null = 回落到开团时间（后端口径）。 */
  card_deadline?: string | null
  mutual_review?: boolean
  campaign_prev?: number | null
  restrict_to_prev_members?: boolean
}

const BASE = '/api/v1/games'

// --------------------------------------------------------------------------
// 读
// --------------------------------------------------------------------------

export function fetchGames(
  params: {
    tag?: string
    status?: GameStatus | ''
    rule_system?: string
    /** 开团方式；后端只认 `online` / `offline`，别的值静默忽略（不筛）。 */
    mode?: GameMode | ''
    gm?: number | string
    /** 排序；缺省/非白名单值一律回落到 `-created_at`（后端 GAME_ORDERING_WHITELIST）。 */
    ordering?: GameOrdering | ''
    page?: number
    page_size?: number
  } = {},
): Promise<Paginated<GameListItem>> {
  return request<Paginated<GameListItem>>(buildUrl(BASE + '/', { ...params }), {
    skipAuthRedirect: true,
  })
}

export function fetchGame(id: number | string): Promise<GameDetail> {
  return request<GameDetail>(BASE + '/' + id + '/', { skipAuthRedirect: true })
}

/**
 * 团的最小只读摘要：相册页与战报页只要标题 / GM / 状态 / 结团时间，不需要整份详情。
 * 走的是同一个 `GET /api/v1/games/<id>/`（AllowAny），只是类型窄一圈。
 *
 * （原先单独放在 `api/game-brief.ts`，是 W4c 与 W4b 并行时的临时分家；
 *   2026-09-21 安全审计波次并回本文件。）
 */
export type GameBrief = Pick<
  GameDetail,
  'id' | 'title' | 'gm' | 'rule_system' | 'status' | 'status_display' | 'start_at' | 'finished_at'
>

/** 团详情对游客也开放，读不到时由调用方决定是否降级显示（只丢标题，不阻断页面）。 */
export function fetchGameBrief(id: number | string): Promise<GameBrief> {
  return request<GameBrief>(BASE + '/' + id + '/', { skipAuthRedirect: true })
}

export function fetchTags(q = ''): Promise<{ results: GameTag[] }> {
  return request<{ results: GameTag[] }>(buildUrl(BASE + '/tags/', { q }), {
    skipAuthRedirect: true,
  })
}

/** 招募中名单：游客 401（调用处要按登录态决定要不要请求）。 */
export function fetchRecruitingRoster(id: number | string): Promise<RecruitingRoster> {
  return request<RecruitingRoster>(BASE + '/' + id + '/signups/', { skipAuthRedirect: true })
}

/** 正式名单：非同团 403，游客 401。 */
export function fetchRoster(id: number | string): Promise<RosterResponse> {
  return request<RosterResponse>(BASE + '/' + id + '/roster/', { skipAuthRedirect: true })
}

export function fetchMySignups(
  params: { game_status?: GameStatus | ''; page?: number; page_size?: number } = {},
): Promise<Paginated<MySignup>> {
  return request<Paginated<MySignup>>(buildUrl(BASE + '/my-signups/', { ...params }))
}

/**
 * 我的全部报名（翻页取全）：「我的团 id 集」之类要全量的场景用。
 * 默认分页只有 20 条，报名一多就会漏（缺陷 F11）；后端 page_size 上限 100。
 * `maxPages` 是防失控的保险丝，不是业务上限。
 */
export async function fetchAllMySignups(maxPages = 50): Promise<MySignup[]> {
  const out: MySignup[] = []
  for (let page = 1; page <= maxPages; page++) {
    const data = await fetchMySignups({ page, page_size: 100 })
    out.push(...data.results)
    if (!data.next) break
  }
  return out
}

export function fetchSessions(id: number | string): Promise<{ results: GameSession[] }> {
  return request<{ results: GameSession[] }>(BASE + '/' + id + '/sessions/', {
    skipAuthRedirect: true,
  })
}

// --------------------------------------------------------------------------
// 写：放团 / 改团
// --------------------------------------------------------------------------

export function createGame(payload: GameWrite): Promise<GameDetail> {
  return request<GameDetail>(BASE + '/', { method: 'POST', body: payload })
}

export function updateGame(id: number | string, payload: GameWrite): Promise<GameDetail> {
  return request<GameDetail>(BASE + '/' + id + '/', { method: 'PATCH', body: payload })
}

// --------------------------------------------------------------------------
// 写：PL 侧
// --------------------------------------------------------------------------

export function signupGame(id: number | string): Promise<MySignup> {
  return request<MySignup>(BASE + '/' + id + '/signup/', { method: 'POST', body: {} })
}

/** 截止前直接退出；截止后落一条待 GM 确认的申请（看返回的 pending_gm_confirm）。 */
export function withdrawSignup(
  id: number | string,
  reason = '',
): Promise<{ withdrawn: boolean; pending_gm_confirm: boolean; signup: MySignup }> {
  return request(BASE + '/' + id + '/withdraw/', { method: 'POST', body: { reason } })
}

export function submitCard(id: number | string, cardId: number): Promise<MySignup> {
  return request<MySignup>(BASE + '/' + id + '/submit-card/', {
    method: 'POST',
    body: { card_id: cardId },
  })
}

// --------------------------------------------------------------------------
// 写：GM 侧
// --------------------------------------------------------------------------

export function reviewSignup(
  id: number | string,
  signupId: number,
  approved: boolean,
  note = '',
): Promise<GMSignup> {
  return request<GMSignup>(BASE + '/' + id + '/signups/' + signupId + '/review/', {
    method: 'POST',
    body: { approved, note },
  })
}

/** GM 代传卡：multipart，字段名 file（另可带 name / rule_system / note）。 */
export function gmUploadCard(
  id: number | string,
  signupId: number,
  file: File,
  extra: { name?: string; rule_system?: string; note?: string } = {},
): Promise<GMSignup> {
  const data = new FormData()
  data.append('file', file)
  if (extra.name) data.append('name', extra.name)
  if (extra.rule_system) data.append('rule_system', extra.rule_system)
  if (extra.note) data.append('note', extra.note)
  return upload<GMSignup>(BASE + '/' + id + '/signups/' + signupId + '/upload-card/', data)
}

export function removeSignup(
  id: number | string,
  signupId: number,
  reason: string,
): Promise<GMSignup> {
  return request<GMSignup>(BASE + '/' + id + '/signups/' + signupId + '/remove/', {
    method: 'POST',
    body: { reason },
  })
}

export function confirmWithdraw(
  id: number | string,
  signupId: number,
  approved: boolean,
  note = '',
): Promise<GMSignup> {
  return request<GMSignup>(BASE + '/' + id + '/signups/' + signupId + '/confirm-withdraw/', {
    method: 'POST',
    body: { approved, note },
  })
}

export function expandGame(id: number | string, maxPlayers: number): Promise<GameDetail> {
  return request<GameDetail>(BASE + '/' + id + '/expand/', {
    method: 'POST',
    body: { max_players: maxPlayers },
  })
}

export function startGame(id: number | string): Promise<GameDetail> {
  return request<GameDetail>(BASE + '/' + id + '/start/', { method: 'POST', body: {} })
}

/** 结团必须交到场名单（空数组 = 无人到场）。只有到场者计次数、能评价。 */
export function finishGame(id: number | string, attendedSignupIds: number[]): Promise<GameDetail> {
  return request<GameDetail>(BASE + '/' + id + '/finish/', {
    method: 'POST',
    body: { attended_signup_ids: attendedSignupIds },
  })
}

export function cancelGame(id: number | string, reason: string): Promise<GameDetail> {
  return request<GameDetail>(BASE + '/' + id + '/cancel/', { method: 'POST', body: { reason } })
}

export function createSession(
  id: number | string,
  payload: { index: number; label?: string; held_at?: string | null },
): Promise<GameSession> {
  return request<GameSession>(BASE + '/' + id + '/sessions/', { method: 'POST', body: payload })
}

export function deleteSession(id: number | string, sessionId: number): Promise<void> {
  return request<void>(BASE + '/' + id + '/sessions/' + sessionId + '/', { method: 'DELETE' })
}
