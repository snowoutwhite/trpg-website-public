/**
 * 战报（apps/reports）。注意本站有两个「report」：
 * 本模块是**战报**；相册里的「举报」在 `api/gallery.ts`。
 *
 * 字段核对自 apps/reports/serializers.py、views.py、urls.py、models.py。
 *
 * 口径要点：
 * - 每人每团一份：第二次 POST 是更新同一份并回 200，不是 409。
 * - 可见性三层由后端过滤（游客只看精选且公开的），**看不见一律 404**；前端不要自己再猜。
 * - 正文按原文存取，服务端不渲染 Markdown；渲染必须走 `MarkdownView`（已 sanitize）。
 * - 精选 `is_featured` 只有站主在后台能改，前台只读。
 */
import { buildUrl, request, upload } from './http'
import type { Paginated, PublicUser } from './site'

/** 可见范围，apps/reports/models.VISIBILITY_CHOICES。 */
export type ReportVisibility = 'public' | 'same_game'

export const VISIBILITY_OPTIONS: { value: ReportVisibility; label: string; hint: string }[] = [
  { value: 'public', label: '公开', hint: '所有登录用户都能看；被站主选为精选后游客也能看。' },
  { value: 'same_game', label: '仅同团可见', hint: '只有本团到场的人与本团 GM 能看。' },
]

/** 战报里带的团摘要（_GameBriefSerializer）。 */
export interface ReportGame {
  id: number
  title: string
  rule_system: string
  start_at: string
  finished_at: string | null
}

export interface ReportAttachment {
  id: number
  original_name: string
  size: number
  mime: string
  /** 鉴权下载路径，跟随战报可见性；没有 file.url 这种直链。 */
  download_url: string
  created_at: string
}

/** 列表行：正文只给前 200 字摘要，附件只给数量。 */
export interface ReportListItem {
  id: number
  game: ReportGame
  author: PublicUser
  title: string
  excerpt: string
  visibility: ReportVisibility
  is_featured: boolean
  attachment_count: number
  created_at: string
  updated_at: string
}

export interface ReportDetail {
  id: number
  game: ReportGame
  author: PublicUser
  title: string
  body_markdown: string
  visibility: ReportVisibility
  is_featured: boolean
  attachments: ReportAttachment[]
  can_edit: boolean
  can_delete: boolean
  created_at: string
  updated_at: string
}

const BASE = '/api/v1/reports'

/** 与 apps/reports/models 一致：正文 50k 字符安全上限、每份最多 10 个附件。 */
export const BODY_MAX_LENGTH = 50_000
export const MAX_ATTACHMENTS = 10
export const TITLE_MAX_LENGTH = 80

export function fetchReports(
  params: {
    game?: number | string
    author?: number | string
    /** 按所属团的规则名筛（大小写不敏感）；`__other__` = 不命中任何站级预设，与团列表同口径。 */
    rule_system?: string
    /** `'1'` = 只看我主持过或到场过的团的战报；游客给了后端回空页。 */
    mine?: '1'
    page?: number
  } = {},
): Promise<Paginated<ReportListItem>> {
  return request<Paginated<ReportListItem>>(buildUrl(BASE + '/', { ...params }), {
    skipAuthRedirect: true,
  })
}

/** 精选（且公开）战报，游客可读。首页与列表页的「精选」筛选用它。 */
export function fetchFeaturedReports(
  params: {
    /** 与 `fetchReports` 同口径（游客只有精选一档，规则筹码靠它生效）。 */
    rule_system?: string
    page?: number
  } = {},
): Promise<Paginated<ReportListItem>> {
  return request<Paginated<ReportListItem>>(buildUrl(BASE + '/featured/', { ...params }), {
    skipAuthRedirect: true,
  })
}

export function fetchReport(id: number | string): Promise<ReportDetail> {
  return request<ReportDetail>(BASE + '/' + id + '/', { skipAuthRedirect: true })
}

export interface ReportWrite {
  title: string
  body_markdown: string
  visibility: ReportVisibility
}

/** 提交战报：同一个团再提交就是更新那一份（后端回 200 而不是 201）。 */
export function submitReport(gameId: number | string, payload: ReportWrite): Promise<ReportDetail> {
  return request<ReportDetail>(BASE + '/', { method: 'POST', body: { game: gameId, ...payload } })
}

/** 改自己的战报；团与精选都不可改。 */
export function updateReport(
  id: number | string,
  payload: Partial<ReportWrite>,
): Promise<ReportDetail> {
  return request<ReportDetail>(BASE + '/' + id + '/', { method: 'PATCH', body: payload })
}

export function deleteReport(id: number | string): Promise<void> {
  return request<void>(BASE + '/' + id + '/', { method: 'DELETE' })
}

export function fetchAttachments(id: number | string): Promise<{ results: ReportAttachment[] }> {
  return request<{ results: ReportAttachment[] }>(BASE + '/' + id + '/attachments/')
}

/** 附件白名单与 20 MB 与角色卡是同一套（后端复用 charactercards.validators）。 */
export function uploadAttachment(id: number | string, file: File): Promise<ReportAttachment> {
  const data = new FormData()
  data.append('file', file)
  return upload<ReportAttachment>(BASE + '/' + id + '/attachments/', data)
}

/** 从文档导入正文：后端 `POST /reports/import-document/`，只转换、不保存、不建附件。 */
export const IMPORT_EXTENSIONS = ['docx', 'txt']
export const IMPORT_MAX_BYTES = 20 * 1024 * 1024

export interface DocumentImportResult {
  /** 已转成 Markdown 的正文；尖括号已转义、控制字符与方向控制字符已去除。 */
  body_markdown: string
  /** 超过正文上限（BODY_MAX_LENGTH）被截断时为 true。 */
  truncated: boolean
  /** 给用户看的提示原话（图片未导入、按 GBK 读取等），可直接展示。 */
  warnings: string[]
}

/** 本地先挡一遍后缀与大小，省一次上传；最终以后端校验为准。 */
export function checkImportFile(file: File): string {
  const dot = file.name.lastIndexOf('.')
  const extension = dot >= 0 ? file.name.slice(dot + 1).toLowerCase() : ''
  if (!IMPORT_EXTENSIONS.includes(extension)) {
    return '只能导入 Word 文档（.docx）或纯文本文件（.txt）。'
  }
  if (file.size > IMPORT_MAX_BYTES) return '单个文件不能超过 20 MB。'
  if (file.size === 0) return '这个文件内容为空。'
  return ''
}

/** 资格与写战报同一口径（后端按 `game` 判），所以要带上团 id。 */
export function importDocument(
  gameId: number | string,
  file: File,
): Promise<DocumentImportResult> {
  const data = new FormData()
  data.append('game', String(gameId))
  data.append('file', file)
  return upload<DocumentImportResult>(BASE + '/import-document/', data)
}

export function deleteAttachment(id: number | string, attachmentId: number): Promise<void> {
  return request<void>(BASE + '/' + id + '/attachments/' + attachmentId + '/', {
    method: 'DELETE',
  })
}

/** 举报一份战报，理由必填；一人对一份只能举一次。 */
export function reportAbuse(
  id: number | string,
  reason: string,
): Promise<{ id: number; status: string; created_at: string }> {
  return request<{ id: number; status: string; created_at: string }>(BASE + '/' + id + '/report/', {
    method: 'POST',
    body: { reason },
  })
}
