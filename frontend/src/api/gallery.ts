/**
 * 活动相册（apps/gallery）。
 * 字段核对自 apps/gallery/serializers.py、views.py、urls.py、models.py。
 *
 * 红线：
 * - 三档图片**只有鉴权视图路径**（`/api/v1/gallery/photos/<id>/file/?size=`），
 *   序列化器不回传存储路径；前端直接把这些路径放进 `<img src>`，由浏览器带会话 Cookie 取，
 *   不要 fetch 成 blob（会多一份内存副本，也失去浏览器缓存）。
 * - 相册整体需登录：游客访问一律 401（后端显式抛，不是 403）。
 * - 待审 / 已下架 / 已驳回的照片后端只回给上传者与站主，所以前端见到即可显示状态徽标。
 */
import { buildUrl, request, upload } from './http'
import type { Paginated, PublicUser } from './site'

/** 照片四态，与 apps/gallery/models.PHOTO_STATUS_CHOICES 一致。 */
export type PhotoStatus = 'pending_review' | 'public' | 'taken_down' | 'rejected'

export interface Photo {
  id: number
  game: number
  game_title: string
  uploader: PublicUser
  caption: string
  width: number
  height: number
  size: number
  status: PhotoStatus
  /** 业务界面遵循后端权限与隐私约束。 */
  is_featured: boolean
  created_at: string
  /** 400 px 缩略图（列表用）。 */
  thumbnail_url: string
  /** 最长边 1600 px（点开预览用）。 */
  preview_url: string
  /** 原尺寸（按需下载，不要放进列表）。 */
  original_url: string
  /** 下架 / 驳回理由：后端只给上传者本人与站主，别人拿到空串。 */
  taken_down_reason: string
  can_delete: boolean
}

/** 举报理由枚举，取自 apps/gallery/models.REASON_CHOICES。第一条就是下架诉求入口。 */
export type PhotoReportReason = 'in_photo' | 'inappropriate' | 'other'

export const PHOTO_REPORT_REASONS: { value: PhotoReportReason; label: string }[] = [
  { value: 'in_photo', label: '我在照片里，要求下架' },
  { value: 'inappropriate', label: '不当内容' },
  { value: 'other', label: '其他' },
]

/** 举报人视角：看得到自己举报的去向，看不到处理人是谁（后端刻意不给）。 */
export interface MyPhotoReport {
  id: number
  photo_id: number
  game_id: number
  photo_status: PhotoStatus
  reason: PhotoReportReason
  reason_display: string
  reason_text: string
  status: 'open' | 'handled'
  result: '' | 'restored' | 'taken_down' | 'dismissed'
  result_display: string
  result_note: string
  created_at: string
  handled_at: string | null
}

const BASE = '/api/v1/gallery'

/** 与 apps/gallery/models 的三条限额一致；前端这层只为省一次失败往返，服务端仍读魔数复核。 */
export const PHOTO_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
export const PHOTO_MAX_BYTES = 10 * 1024 * 1024
export const PHOTO_MAX_PER_GAME = 50
/** 占配额的状态：驳回的不占，已下架的占（后端 models.QUOTA_STATUSES 同一口径）。 */
export const PHOTO_QUOTA_STATUSES: PhotoStatus[] = ['pending_review', 'public', 'taken_down']

export function checkPhotoFile(file: File): string {
  const dot = file.name.lastIndexOf('.')
  const extension = dot >= 0 ? file.name.slice(dot + 1).toLowerCase() : ''
  if (!PHOTO_EXTENSIONS.includes(extension)) return '相册仅支持 jpg、png、webp 格式的图片。'
  if (file.size > PHOTO_MAX_BYTES) return '单张照片不能超过 10 MB。'
  if (file.size === 0) return '这个文件内容为空。'
  return ''
}

export function fetchGamePhotos(
  gameId: number | string,
  params: { page?: number; page_size?: number } = {},
): Promise<Paginated<Photo>> {
  return request<Paginated<Photo>>(
    buildUrl(BASE + '/games/' + gameId + '/photos/', { ...params }),
    { skipAuthRedirect: true },
  )
}

/** 上传：仅本团 GM，且团已结团、还在上传窗口内、未超每团 50 张。 */
export function uploadPhoto(
  gameId: number | string,
  file: File,
  caption = '',
): Promise<Photo> {
  const data = new FormData()
  data.append('file', file)
  if (caption) data.append('caption', caption)
  return upload<Photo>(BASE + '/games/' + gameId + '/photos/', data)
}

export function deletePhoto(id: number): Promise<void> {
  return request<void>(BASE + '/photos/' + id + '/', { method: 'DELETE' })
}

/** 举报 / 下架诉求。一人对一张照片只能提一次（后端唯一约束）。 */
export function reportPhoto(
  id: number,
  payload: { reason: PhotoReportReason; reason_text?: string },
): Promise<MyPhotoReport> {
  return request<MyPhotoReport>(BASE + '/photos/' + id + '/report/', {
    method: 'POST',
    body: payload,
  })
}

export function fetchMyPhotoReports(params: { page?: number } = {}): Promise<
  Paginated<MyPhotoReport>
> {
  return request<Paginated<MyPhotoReport>>(buildUrl(BASE + '/reports/mine/', { ...params }))
}

// --------------------------------------------------------------------------
// 站主审核（Django 权限位 `gallery.moderate_photo`，不是 `is_staff`）
// --------------------------------------------------------------------------
//
// 前端只能拿到 `is_staff`（`CurrentUser`），拿不到那个权限位，所以按钮按 `is_staff` 显示，
// 没权限的人点了会收到 403 —— **前端这层只是入口，不是权限边界**。
//
// 注意这里没有「下架一张公开照片」的接口：后端 `take_down_photo` 只在**处理举报**
// （`handlePhotoReport` 的 `taken_down`）里调用，没有单独的 endpoint。所以团相册里
// 站主能做的是「通过 / 驳回」，下架要走举报队列。

/** 待审照片 + 未处理举报的站级队列。 */
export function fetchModerationQueue(): Promise<{
  photos: { count: number; next: string | null; results: Photo[] }
  reports: { count: number; next: string | null; results: unknown[] }
}> {
  return request(BASE + '/moderation/queue/')
}

/** 审核通过：`pending_review` / `taken_down` → `public`。 */
export function approvePhoto(id: number): Promise<Photo> {
  return request<Photo>(BASE + '/moderation/photos/' + id + '/approve/', {
    method: 'POST',
    body: {},
  })
}

/** 驳回：`pending_review` / `taken_down` → `rejected`（不再占每团 50 张配额）。 */
export function rejectPhoto(id: number, reason = ''): Promise<Photo> {
  return request<Photo>(BASE + '/moderation/photos/' + id + '/reject/', {
    method: 'POST',
    body: { reason },
  })
}

/** 处理一条举报。`note` 是写给**举报人**的说明，后端不会把它写进给上传者看的下架理由。 */
export function handlePhotoReport(
  reportId: number,
  action: 'restored' | 'taken_down' | 'dismissed',
  note = '',
): Promise<MyPhotoReport> {
  return request<MyPhotoReport>(BASE + '/moderation/reports/' + reportId + '/handle/', {
    method: 'POST',
    body: { action, note },
  })
}
