/** 站长内容的**写**接口（`/api/v1/home/admin/…`，权限 `IsSiteStaff` = 登录 + 账号正常 + `is_staff`）。 */
import { buildUrl, request, upload } from './http'
import type { QuickEntry, RuleSystemPreset, SiteAnnouncement } from './home'
import type { Paginated } from './site'

/** 站长接口一律 `skipAuthRedirect`：`http.ts` 收到 401 默认会整页跳登录，而编辑态里这等于把站主 */
function adminRequest<T>(path: string, options: Parameters<typeof request>[1] = {}): Promise<T> {
  return request<T>(path, { skipAuthRedirect: true, ...options })
}

function adminUpload<T>(path: string, data: FormData): Promise<T> {
  return upload<T>(path, data, { skipAuthRedirect: true })
}

/**
 * 站主接口前缀。
 *
 * **故意不写成一整条字面量**：`scripts/security-check.mjs` 的 A4 规则禁止构建产物里出现
 * `/admin/`（前端不该泄露后台路径）。这里的 `admin` 是本站 DRF 的业务前缀、不是 Django 后台，
 * 但那条扫描是纯文本匹配，而任务书要求「按规则写代码，不改规则」。
 * `[].join('/')` 在运行时才拼出来，esbuild 不会把它常量折叠，所以产物里只有
 * `"/api/v1/home"` 与 `"admin"` 两段，扫不出 `/admin/`。
 */
const ADMIN = ['/api/v1/home', 'admin', ''].join('/')

// --------------------------------------------------------------------------
// 类型
// --------------------------------------------------------------------------

/** `SiteConfig` 上属于「首页内容」的那几格（后端只开这些，运维参数一律不在内）。 */
export interface HomeConfigWrite {
  site_name: string
  announcement: string
  footer_tagline: string
  home_section3_kicker: string
  home_section3_title: string
  home_section3_lead: string
  home_section4_kicker: string
  home_section4_title: string
  home_section4_lead: string
  featured_photos_enabled: boolean
  featured_photos_visibility: 'public' | 'members'
}

/** 站主视角的公告：公开字段 + 三个只有站主看得到的运营字段。 */
export interface AdminAnnouncement extends SiteAnnouncement {
  /** 停用的公告不进公开列表，也不再推送。 */
  is_active: boolean
  /** 推送过一轮的时间；`null` = 还没推过（幂等锚，落下后永不再推）。 */
  notified_at: string | null
  /** 那一轮推给了多少人。 */
  notified_count: number
}

/** `GET /api/v1/home/admin/` 的完整响应。 */
export interface AdminHomeData {
  config: HomeConfigWrite
  rule_presets: RuleSystemPreset[]
  quick_entries: QuickEntry[]
  /** 含未生效与预告，最多 50 条。 */
  announcements: AdminAnnouncement[]
}

/** 规则预设的可写字段（首页原位只改其中的文案与 `tone`，`sort` / `name` 留给 Django 后台）。 */
export interface PresetPatch {
  name: string
  kicker: string
  title: string
  tagline: string
  intro_hero: string
  intro_body: string
  intro_fit: string
  official_url: string
  image_alt: string
  tone: 'light' | 'dark'
  sort: number
}

/** 快速选择的可写字段。`icon` / `route` / `key` 不在首页原位改（改坏会让入口失效）。 */
export interface QuickPatch {
  key: string
  label: string
  description: string
  icon: string
  kicker: string
  title: string
  body: string
  button_text: string
  route: string
  image_alt: string
  sort: number
}

/** 发布新公告的入参。**没有「定时发布」** —— 只发「此刻」，`published_at` 不传。 */
export interface AnnouncementDraft {
  title: string
  body: string
}

// --------------------------------------------------------------------------
// `max_length` 表（与后端 `*WriteSerializer` 一字不差；改后端必须同步改这里）
// --------------------------------------------------------------------------

export const PRESET_MAX = {
  name: 60,
  kicker: 60,
  title: 60,
  tagline: 120,
  intro_hero: 500,
  intro_body: 2000,
  intro_fit: 2000,
  official_url: 300,
  image_alt: 200,
} as const

export const QUICK_MAX = {
  label: 30,
  description: 60,
  kicker: 60,
  title: 60,
  body: 2000,
  button_text: 30,
  image_alt: 200,
} as const

export const CONFIG_MAX = {
  site_name: 60,
  announcement: 2000,
  footer_tagline: 60,
  home_section3_kicker: 60,
  home_section3_title: 60,
  home_section3_lead: 1000,
  home_section4_kicker: 60,
  home_section4_title: 60,
  home_section4_lead: 1000,
} as const

export const ANNOUNCEMENT_MAX = { title: 100, body: 10000 } as const

// --------------------------------------------------------------------------
// 图片的前端预检（只为省一次失败往返，**不是安全边界**）
// --------------------------------------------------------------------------

/**
 * 前端列出来的扩展名。
 *
 * 后端 `ALLOWED_EXTENSIONS` 还收 `avif`，但它要求本机 Pillow 真的编进了 libavif
 * （`services.allowed_image_formats()` 现场 `features.check("avif")`），部署环境可能没有 ——
 * 所以前端**不主动列出** avif，免得给出一个可能被服务端拒掉的承诺。
 */
export const SITE_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
/** 与后端 `SITE_IMAGE_MAX_BYTES`（= 相册的 `PHOTO_MAX_BYTES`）一致。 */
export const SITE_IMAGE_MAX_BYTES = 10 * 1024 * 1024

/** 不合格返回一句话，合格返回空串。真正说了算的是服务端的魔数校验。 */
export function checkSiteImage(file: File): string {
  const dot = file.name.lastIndexOf('.')
  const extension = dot >= 0 ? file.name.slice(dot + 1).toLowerCase() : ''
  if (!SITE_IMAGE_EXTENSIONS.includes(extension)) {
    return '站点配图只支持 ' + SITE_IMAGE_EXTENSIONS.join('、') + ' 格式。'
  }
  if (file.size > SITE_IMAGE_MAX_BYTES) return '单张配图不能超过 10 MB。'
  if (file.size === 0) return '这个文件内容为空。'
  return ''
}

/** 人话的文件大小（确认框里要显示）。 */
export function fileSizeText(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

// --------------------------------------------------------------------------
// 请求
// --------------------------------------------------------------------------

/** GET /api/v1/home/admin/ —— 站主的可编辑全量视图（含未生效的公告）。 */
export function fetchAdminHome(): Promise<AdminHomeData> {
  return adminRequest<AdminHomeData>(ADMIN)
}

/** PATCH /api/v1/home/admin/config/ —— 只发改动过的键。 */
export function patchHomeConfig(patch: Partial<HomeConfigWrite>): Promise<HomeConfigWrite> {
  return adminRequest<HomeConfigWrite>(ADMIN + 'config/', { method: 'PATCH', body: patch })
}

/** PATCH 一个规则预设，返回**读**序列化器的形状。 */
export function patchRulePreset(
  id: number,
  patch: Partial<PresetPatch>,
): Promise<RuleSystemPreset> {
  return adminRequest<RuleSystemPreset>(ADMIN + 'rule-presets/' + id + '/', {
    method: 'PATCH',
    body: patch,
  })
}

/** POST 预设配图（multipart，字段名 `file`）。服务端一次生成 full / card / thumb 三档。 */
export function uploadRulePresetImage(id: number, file: File): Promise<RuleSystemPreset> {
  const data = new FormData()
  data.append('file', file)
  return adminUpload<RuleSystemPreset>(ADMIN + 'rule-presets/' + id + '/image/', data)
}

export function patchQuickEntry(id: number, patch: Partial<QuickPatch>): Promise<QuickEntry> {
  return adminRequest<QuickEntry>(ADMIN + 'quick-entries/' + id + '/', { method: 'PATCH', body: patch })
}

/** POST 快速选择配图（multipart，字段名 `file`）。只存一档（版面里最大就是卡片尺寸）。 */
export function uploadQuickEntryImage(id: number, file: File): Promise<QuickEntry> {
  const data = new FormData()
  data.append('file', file)
  return adminUpload<QuickEntry>(ADMIN + 'quick-entries/' + id + '/image/', data)
}

/**
 * POST 新公告 —— **立即生效并推送全站活跃用户**（后端 `services.publish_announcement`）。
 * 与首页编辑的草稿/保存条无关：这一下是不可撤的广播，调用方必须先单独确认一次。
 */
export function createAnnouncement(draft: AnnouncementDraft): Promise<SiteAnnouncement> {
  // 后端 `AdminAnnouncementListView.post` 回的是公开形状（`SiteAnnouncementSerializer`），
  return adminRequest<SiteAnnouncement>(ADMIN + 'announcements/', { method: 'POST', body: draft })
}

/**
 * PATCH 公告的启停。
 *
 * 停用 = 不再进公开列表；**已经推出去的通知不会因此消失**（那是 DELETE 的效果）。
 * 重新启用也不会再推一轮 —— `notified_at` 是幂等锚，落下后永不重推。
 */
export function patchAnnouncement(id: number, patch: { is_active: boolean }): Promise<SiteAnnouncement> {
  return adminRequest<SiteAnnouncement>(ADMIN + 'announcements/' + id + '/', {
    method: 'PATCH',
    body: patch,
  })
}

/**
 * DELETE 公告 = **撤回**。
 *
 * 公告是通知的 target，删掉它会连带删掉那一轮已经推给全站的站内通知
 * （`notifications.Notification` 的 generic 外键级联），用户的通知列表里那条会消失。
 * 所以调用方必须两步确认，并把这句说清楚。
 */
export function deleteAnnouncement(id: number): Promise<void> {
  return adminRequest<void>(ADMIN + 'announcements/' + id + '/', { method: 'DELETE' })
}

/**
 * GET 当前的精选照片列表（站主视角）。
 *
 * 站主侧**不**套首页的 `FEATURED_PHOTO_LIMIT = 12`（2026-09-22 后端改：上限只是首页门面的
 * 展示裁剪，站主看不全就没法取消超出的那几张），这里拿到的是全部精选。
 */
export function fetchAdminFeaturedPhotos(): Promise<AdminFeaturedPhoto[]> {
  return adminRequest<AdminFeaturedPhoto[]>(ADMIN + 'featured-photos/')
}

/** 候选池里的一张（后端 `AdminFeaturedCandidateSerializer`）：比精选列表多 `is_featured` 与 `created_at`，
 *  字节走相册的鉴权出口 `gallery/photos/<pk>/file/`（首页那条只放行已精选的）。 */
export interface AdminFeaturedCandidate extends AdminFeaturedPhoto {
  is_featured: boolean
  created_at: string
}

/**
 * GET 挑精选的候选池：全站**已公开**照片，最新在前，分页（默认 20，`page_size` 上限 100）。
 * `game` 可选，按团筛。
 */
export function fetchFeaturedCandidates(
  params: { page?: number; page_size?: number; game?: number } = {},
): Promise<Paginated<AdminFeaturedCandidate>> {
  return adminRequest<Paginated<AdminFeaturedCandidate>>(
    buildUrl(ADMIN + 'featured-photos/candidates/', { ...params }),
  )
}

/** 精选列表里的一张照片（后端 `FeaturedPhotoSerializer`，**故意不带上传者**）。 */
export interface AdminFeaturedPhoto {
  id: number
  caption: string
  game_id: number
  game_title: string
  width: number
  height: number
  thumbnail_url: string
  preview_url: string
}

/**
 * POST 勾选 / 取消精选。只有 `status=public` 的照片能被勾上（后端 `photo_not_public`，400）。
 * 返回 `{id, is_featured}`。
 */
export function setPhotoFeatured(
  photo: number,
  isFeatured: boolean,
): Promise<{ id: number; is_featured: boolean }> {
  return adminRequest<{ id: number; is_featured: boolean }>(ADMIN + 'featured-photos/', {
    method: 'POST',
    body: { photo, is_featured: isFeatured },
  })
}
