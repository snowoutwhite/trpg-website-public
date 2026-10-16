/**
 * 账号自助接口（apps/accounts）。管理动作（审批 GM、封禁、邀请码）只在后台，不开放 API。
 * 字段核对自 apps/accounts/serializers.py、views.py、services.py。
 */
import { request, upload } from './http'
import type { CurrentUser } from './site'

export interface GMApplication {
  id: number
  reason: string
  /** pending / approved / rejected。 */
  status: string
  review_note: string
  created_at: string
  reviewed_at: string | null
}

const BASE = '/api/v1/accounts/me'

/** 头像：后端按魔数校验并缩到 256px 转 WebP；前端只做类型与大小的先行拦截。 */
export const AVATAR_MAX_BYTES = 2 * 1024 * 1024
export const AVATAR_TYPES = ['image/jpeg', 'image/png', 'image/webp']

export function checkAvatarFile(file: File): string {
  if (!AVATAR_TYPES.includes(file.type)) return '头像只支持 jpg / png / webp'
  if (file.size > AVATAR_MAX_BYTES) return '头像不能超过 2 MB'
  return ''
}

/** 改昵称：30 天一次，太频繁时后端抛 nickname_change_too_soon，消息里带下次可改时间。 */
export function changeNickname(nickname: string): Promise<CurrentUser> {
  return request<CurrentUser>(BASE + '/nickname/', { method: 'POST', body: { nickname } })
}

export function uploadAvatar(file: File): Promise<CurrentUser> {
  const data = new FormData()
  data.append('avatar', file)
  return upload<CurrentUser>(BASE + '/avatar/', data)
}

export function clearAvatar(): Promise<CurrentUser> {
  return request<CurrentUser>(BASE + '/avatar/', { method: 'DELETE' })
}

export function fetchGMApplication(): Promise<{ application: GMApplication | null }> {
  return request<{ application: GMApplication | null }>(BASE + '/gm-application/')
}

export function applyForGM(reason: string): Promise<GMApplication> {
  return request<GMApplication>(BASE + '/gm-application/', { method: 'POST', body: { reason } })
}

/** 注销：匿名化保留，不物理删除；后端会顺带登出。 */
export function deactivateAccount(): Promise<{ detail: string }> {
  return request<{ detail: string }>(BASE + '/deactivate/', { method: 'POST' })
}
