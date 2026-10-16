/**
 * 站内通知与邮件偏好（apps/notifications）。全部只作用于当前登录者。
 * 字段核对自 apps/notifications/serializers.py、views.py、events.py。
 */
import { buildUrl, request } from './http'
import type { Paginated, PublicUser } from './site'

export interface NotificationItem {
  id: number
  /** 业务界面遵循后端权限与隐私约束。 */
  event: string
  /** 后端给的中文标题。 */
  title: string
  /** 触发者；匿名场景（如团后评价）后端必须留空。 */
  actor: PublicUser | null
  target_type: string | null
  target_object_id: number | null
  payload: Record<string, unknown>
  created_at: string
  /** null 表示未读。 */
  read_at: string | null
}

export interface EmailPreference {
  /** 邮件提醒总开关，默认关。 */
  email_enabled: boolean
  /** 按事件覆盖总开关，形如 {"signup_result": true}。 */
  per_event: Record<string, boolean>
  /** GET 时后端附带的事件清单（PATCH 响应里没有）。 */
  available_events?: { event: string; label: string }[]
}

const BASE = '/api/v1/notifications/'

export function fetchNotifications(
  /** `event`：只看某一种事件（键见 `available_events`）；认不出的值后端静默忽略。 */
  params: { unread?: '1'; event?: string; page?: number; page_size?: number } = {},
): Promise<Paginated<NotificationItem>> {
  return request<Paginated<NotificationItem>>(buildUrl(BASE, { ...params }))
}

export function fetchUnreadCount(): Promise<{ unread: number }> {
  return request<{ unread: number }>(BASE + 'unread-count/', { skipAuthRedirect: true })
}

/** 不传 ids 则全部标已读。 */
export function markRead(ids?: number[]): Promise<{ updated: number; unread: number }> {
  return request<{ updated: number; unread: number }>(BASE + 'read/', {
    method: 'POST',
    body: ids && ids.length ? { ids } : {},
  })
}

export function fetchEmailPreference(): Promise<EmailPreference> {
  return request<EmailPreference>(BASE + 'preference/')
}

export function updateEmailPreference(
  payload: Partial<Pick<EmailPreference, 'email_enabled' | 'per_event'>>,
): Promise<EmailPreference> {
  return request<EmailPreference>(BASE + 'preference/', { method: 'PATCH', body: payload })
}
