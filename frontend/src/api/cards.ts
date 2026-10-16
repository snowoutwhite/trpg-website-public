/**
 * 角色卡与卡池（apps/charactercards）。
 * 字段核对自 apps/charactercards/serializers.py、views.py、urls.py、validators.py。
 *
 * 红线：任何接口都不回传文件存储路径，源文件只能经 download_url（鉴权视图）取；
 * 游客能浏览卡池但不能下载（后端 can_view_file 的现行口径）。
 */
import { buildUrl, request, upload } from './http'
import type { Paginated, PublicUser } from './site'

export type CardStatus = 'alive' | 'torn'

/**
 * 这张卡跑过的一个团。
 * 后端 `apps/charactercards/services.py:212` 只存 `game_id` / `played_at`，
 * 团名与时间由 games app 注册的 provider 补齐（`apps/games/services.py:1151`）；
 * 团被删掉时补不上，所以除前两项外**都是可选的**。
 */
export interface CardPlay {
  game_id: number
  played_at: string
  title?: string
  start_at?: string | null
  finished_at?: string | null
}

/** 卡池与他人视角：只露名称、规则、次数、跑过的团。 */
export interface PublicCard {
  id: number
  owner: PublicUser
  name: string
  rule_system: string
  status: CardStatus
  status_display: string
  play_count: number
  games_played: CardPlay[]
  is_public: boolean
  is_usable_for_signup: boolean
  has_file: boolean
  can_download: boolean
  download_url: string | null
  created_at: string
}

/** 自己的卡：多一个备注，且名称 / 规则 / 公开 / 状态可改。 */
export interface MyCard extends PublicCard {
  note: string
  updated_at: string
}

export interface CardFileVersion {
  id: number
  version: number
  original_name: string
  size: number
  mime: string
  uploaded_by: PublicUser | null
  /** GM 代传（交卡阶段）为真。 */
  uploaded_by_gm: boolean
  created_at: string
}

export interface CardWrite {
  name?: string
  rule_system?: string
  note?: string
  is_public?: boolean
  status?: CardStatus
}

const BASE = '/api/v1/charactercards'

/** 前端先校验一道，省一次失败往返；服务端仍会读魔数复核（validators.py）。 */
export const CARD_FILE_EXTENSIONS = ['pdf', 'xlsx', 'xls', 'docx', 'txt', 'png', 'jpg', 'jpeg']
export const CARD_FILE_MAX_BYTES = 20 * 1024 * 1024

export function checkCardFile(file: File): string {
  const dot = file.name.lastIndexOf('.')
  const extension = dot >= 0 ? file.name.slice(dot + 1).toLowerCase() : ''
  if (!CARD_FILE_EXTENSIONS.includes(extension)) {
    return '文件格式不受支持，仅支持 ' + CARD_FILE_EXTENSIONS.join('、') + '。'
  }
  if (file.size > CARD_FILE_MAX_BYTES) return '单个文件不能超过 20 MB。'
  if (file.size === 0) return '这个文件内容为空。'
  return ''
}

export type CardPoolOrdering = '' | 'plays'

export function fetchCardPool(params: {
  rule_system?: string
  status?: CardStatus | ''
  /** 只看某个人的公开卡（后端 `pool/` 的 `?owner=<user id>`）；非法值后端一律当「查不到」。 */
  owner?: number | string
  /** 排序：缺省 = 新建在前；`plays` = 参团次数多的在前。白名单外的值后端回落默认。 */
  ordering?: CardPoolOrdering
  page?: number
  page_size?: number
} = {}): Promise<Paginated<PublicCard>> {
  return request<Paginated<PublicCard>>(buildUrl(BASE + '/pool/', { ...params }), {
    skipAuthRedirect: true,
  })
}

/** 单卡元数据：他人的私密卡一律 404（后端 `views._deny`，不区分游客与他人，避免暴露存在性）。 */
export function fetchCard(id: number | string): Promise<PublicCard | MyCard> {
  return request<PublicCard | MyCard>(BASE + '/' + id + '/', { skipAuthRedirect: true })
}

export function fetchMyCards(params: { status?: CardStatus | ''; page?: number } = {}): Promise<
  Paginated<MyCard>
> {
  return request<Paginated<MyCard>>(buildUrl(BASE + '/mine/', { ...params }))
}

export function fetchMyCard(id: number | string): Promise<MyCard> {
  return request<MyCard>(BASE + '/mine/' + id + '/')
}

export function createCard(payload: CardWrite): Promise<MyCard> {
  return request<MyCard>(BASE + '/mine/', { method: 'POST', body: payload })
}

export function updateCard(id: number | string, payload: CardWrite): Promise<MyCard> {
  return request<MyCard>(BASE + '/mine/' + id + '/', { method: 'PATCH', body: payload })
}

export function fetchCardFiles(id: number | string): Promise<{ results: CardFileVersion[] }> {
  return request<{ results: CardFileVersion[] }>(BASE + '/mine/' + id + '/files/')
}

export function uploadCardFile(id: number | string, file: File): Promise<CardFileVersion> {
  const data = new FormData()
  data.append('file', file)
  return upload<CardFileVersion>(BASE + '/mine/' + id + '/files/', data)
}

/** 下载链接：直接给 <a href>，由浏览器带会话 Cookie 走鉴权视图。 */
export function cardDownloadUrl(id: number | string, version?: number): string {
  return buildUrl(BASE + '/' + id + '/download/', { version })
}
