/**
 * 站级配置与当前用户资料（本站自有 DRF 接口，非 allauth）。
 *
 * 字段名**以后端代码为准**，已逐条核对：
 *   apps/siteconfig/serializers.py: PublicSiteConfigSerializer
 *   apps/accounts/serializers.py:   MeSerializer / PublicUserSerializer
 */
import { request } from './http'

/** 分页信封：common/pagination.py StandardPagination（?page=&page_size=，默认 20、上限 100）。 */
export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

/** 任何第三方可见处的用户表示（PublicUserSerializer，绝不含邮箱）。 */
export interface PublicUser {
  id: number
  nickname: string
  avatar: string | null
  is_gm: boolean
}

/** GET /api/v1/siteconfig/ —— 站级单例里对游客也安全公开的那部分。 */
export interface SiteConfig {
  /** 站名，页头与标题用它，不硬编码。 */
  site_name: string
  /** 公告栏文案（后端字段就叫 announcement，不是 tagline）。 */
  announcement: string
  /** 赞功能总开关，关闭时全站隐藏赞级别与评价入口。 */
  like_feature_enabled: boolean
  /** 注册是否必须填邀请码，决定注册页是否显示该字段。 */
  invite_code_required: boolean
  /** 相册审核模式：public / pre_review / post_report。 */
  gallery_moderation_mode: string
  /** 规则系统预设：玩家卡偏好规则、角色卡规则共用这一份。 */
  rule_system_presets: string[]
  /** 赞级别公布阈值：被评数达到才显示档位。 */
  like_level_publish_threshold: number
  review_window_days: number
  gallery_upload_window_days: number
  gm_auto_promote_threshold: number
  /** ICP 备案号；未填时是空串。页脚那行按空串判断显示与否。 */
  icp_beian: string
}

/** GET /api/v1/accounts/me/ —— 只有本人能拿到 email。 */
export interface CurrentUser {
  id: number
  email: string
  email_verified: boolean
  nickname: string
  /** 头像 URL，未设置时为 null。 */
  avatar: string | null
  /** 是否具有 GM 身份（GM 同时保留 PL 身份）。 */
  is_gm: boolean
  /**
   * 是否站主（Django `is_staff`），决定顶栏是否出现「编辑」入口。
   * 后端 `MeSerializer` 自 2026-09-22 起只读下发（`apps/accounts/serializers.py`），
   * 写入被对抗用例拦住；前端仍按 `=== true` 判断，缺省不给入口。
   */
  is_staff: boolean
  is_banned: boolean
  is_muted: boolean
  is_deactivated: boolean
  date_joined: string
  /** 下次可改昵称的时间；null 表示随时可改（昵称 30 天一次）。 */
  nickname_change_available_at: string | null
  has_pending_gm_application: boolean
}

export function fetchSiteConfig(): Promise<SiteConfig> {
  return request<SiteConfig>('/api/v1/siteconfig/', { skipAuthRedirect: true })
}

export function fetchCurrentUser(): Promise<CurrentUser> {
  return request<CurrentUser>('/api/v1/accounts/me/', { skipAuthRedirect: true })
}
