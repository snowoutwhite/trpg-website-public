/** 站长内容（apps/homecontent）：首页一次要的全部内容、公告历史。 */
import { buildUrl, request } from './http'
import type { Paginated, PublicUser } from './site'

/** 规则预设配图三档。站主没传图时三个都是空串，调用方回落 `lib/rule-art.ts`。 */
export interface RuleImageTiers {
  /** 2560 宽，首屏铺底用。 */
  full: string
  /** 1200 宽，卡面用。 */
  card: string
  /** 400 宽，列表缩略用。 */
  thumb: string
}

/** 规则介绍三段（后端是 intro_hero / intro_body / intro_fit 三个字段，序列化成一个对象）。 */
export interface RuleIntro {
  hero: string
  body: string
  fit: string
}

/** 首屏轮播一帧 = 全站分类轴的一个取值。 */
export interface RuleSystemPreset {
  id: number
  /** 规则名，与 `SiteConfig.rule_system_presets` 镜像一致（大小写不敏感唯一）。 */
  name: string
  kicker: string
  title: string
  tagline: string
  intro: RuleIntro
  /** 官方站点，后端只收 http/https；空串表示没填。 */
  official_url: string
  image: RuleImageTiers
  image_alt: string
  /** 这张图适合压白字还是墨字，决定 `BlurStage` 的遮罩方向。 */
  tone: 'light' | 'dark'
  sort: number
}

/** 首页第二段「你想从哪里开始？」的一项。 */
export interface QuickEntry {
  id: number
  key: string
  label: string
  description: string
  /** 图标名，对应 `AppIcon` 的 PATHS 键。 */
  icon: string
  kicker: string
  title: string
  body: string
  button_text: string
  /** 后端只收站内路由（单个 `/` 开头），不会是站外地址。 */
  route: string
  image: string
  image_alt: string
  sort: number
}

/** 站长公告。`is_read` 三态见文件头。 */
export interface SiteAnnouncement {
  id: number
  title: string
  body: string
  published_at: string
  author: PublicUser | null
  /** null = 没有对应的站内通知（游客 / 公告推送时还没注册）。 */
  is_read: boolean | null
  /** 对应站内通知的 id，标已读时要用；没有通知时是 null。 */
  notification_id: number | null
}

/** 首页某一段的文案三件套。 */
export interface HomeSectionCopy {
  kicker: string
  title: string
  lead: string
}

/** 首页的站级文案块（SiteConfig 里属于「首页内容」的那几格，不含任何运维参数）。 */
export interface HomeSiteCopy {
  site_name: string
  announcement: string
  /** 页脚署名句。 */
  footer_tagline: string
  section3: HomeSectionCopy
  section4: HomeSectionCopy
}

/** 首页照片墙的一张照片。**故意不带 uploader**（后端序列化器里就没有）。 */
export interface FeaturedPhoto {
  id: number
  caption: string
  game_id: number
  game_title: string
  width: number
  height: number
  /** 字节出口，已带 `?size=`；不要自己拼存储路径。 */
  thumbnail_url: string
  preview_url: string
}

export interface FeaturedPhotoBlock {
  enabled: boolean
  visibility: 'public' | 'members'
  /** 三道闸算完的结论：false 时 `results` 必为空，前端直接隐藏整段。 */
  visible: boolean
  results: FeaturedPhoto[]
}

/** GET /api/v1/home/ 的完整响应。 */
export interface HomeContent {
  site: HomeSiteCopy
  rule_presets: RuleSystemPreset[]
  quick_entries: QuickEntry[]
  /** 最新一条生效公告；没有就是 null。 */
  announcement: SiteAnnouncement | null
  featured_photos: FeaturedPhotoBlock
}

/**
 * GET /api/v1/home/ —— 游客可读。
 *
 * `skipAuthRedirect`：这是公开接口，任何 401 都不该把游客踢去登录页。
 */
export function fetchHome(): Promise<HomeContent> {
  return request<HomeContent>('/api/v1/home/', { skipAuthRedirect: true })
}

/** GET /api/v1/announcements/ —— 公告历史，游客可读，分页。 */
export function fetchAnnouncements(
  params: { page?: number; page_size?: number } = {},
): Promise<Paginated<SiteAnnouncement>> {
  return request<Paginated<SiteAnnouncement>>(buildUrl('/api/v1/announcements/', { ...params }), {
    skipAuthRedirect: true,
  })
}
