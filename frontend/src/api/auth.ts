/** django-allauth headless「browser」客户端封装。 */
import { allauthRequest, type AllauthEnvelope } from './http'

const BASE = '/_allauth/browser/v1'

/** allauth 序列化的用户对象（由后端 HeadlessAdapter.serialize_user 决定具体字段）。 */
export interface AllauthUser {
  id: number | string
  display?: string
  email?: string
  username?: string
  has_usable_password?: boolean
}

export interface AllauthFlow {
  id: string
  is_pending?: boolean
}

export interface SessionData {
  user?: AllauthUser
  methods?: unknown[]
  flows?: AllauthFlow[]
}

export type SessionEnvelope = AllauthEnvelope<SessionData>

export interface AccountConfig {
  login_methods?: string[]
  is_open_for_signup?: boolean
  email_verification_by_code_enabled?: boolean
  login_by_code_enabled?: boolean
  password_reset_by_code_enabled?: boolean
}

/** GET /_allauth/browser/v1/config —— 同时会让后端下发 csrftoken Cookie。 */
export function fetchAllauthConfig(): Promise<AllauthEnvelope<{ account?: AccountConfig }>> {
  return allauthRequest<{ account?: AccountConfig }>(BASE + '/config')
}

/** GET /auth/session —— 200 已登录；401 未登录（data.flows 给出可走的流程）；410 会话已失效。 */
export function fetchSession(): Promise<SessionEnvelope> {
  return allauthRequest<SessionData>(BASE + '/auth/session')
}

/** POST /auth/login —— 200 成功；401 还有待完成阶段（如待验邮箱）；409 已登录；400 输入错误。 */
export function login(email: string, password: string): Promise<SessionEnvelope> {
  return allauthRequest<SessionData>(BASE + '/auth/login', {
    method: 'POST',
    body: { email, password },
  })
}

export interface SignupPayload {
  email: string
  password: string
  /** 后端 ACCOUNT_SIGNUP_FORM_CLASS 扩展字段：昵称必填。 */
  nickname: string
  /** 站级开关开启时必填。 */
  invite_code?: string
}

/** POST /auth/signup —— 200 直接登录；401 待邮箱验证（常见）；403 注册关闭；409 已登录。 */
export function signup(payload: SignupPayload): Promise<SessionEnvelope> {
  const body: Record<string, string> = {
    email: payload.email,
    password: payload.password,
    nickname: payload.nickname,
  }
  if (payload.invite_code) body.invite_code = payload.invite_code
  return allauthRequest<SessionData>(BASE + '/auth/signup', { method: 'POST', body })
}

/** DELETE /auth/session —— 登出；allauth 规范返回 401（已无认证会话），不是错误。 */
export function logout(): Promise<SessionEnvelope> {
  return allauthRequest<SessionData>(BASE + '/auth/session', { method: 'DELETE' })
}

/** GET /auth/email/verify —— key 走请求头 X-Email-Verification-Key，用于进页面时先校验链接有效性。 */
export function fetchEmailVerificationInfo(
  key: string,
): Promise<AllauthEnvelope<{ email: string; user: AllauthUser }>> {
  return allauthRequest<{ email: string; user: AllauthUser }>(BASE + '/auth/email/verify', {
    headers: { 'X-Email-Verification-Key': key },
  })
}

/** POST /auth/email/verify —— 200 验证并登录；401 验证成功但仍需登录（非失败）。 */
export function verifyEmail(key: string): Promise<SessionEnvelope> {
  return allauthRequest<SessionData>(BASE + '/auth/email/verify', {
    method: 'POST',
    body: { key },
  })
}

/** POST /auth/email/verify/resend —— 需后端开启 ACCOUNT_EMAIL_VERIFICATION_SUPPORTS_RESEND；429 表示太频繁。 */
export function resendEmailVerification(): Promise<AllauthEnvelope> {
  return allauthRequest(BASE + '/auth/email/verify/resend', { method: 'POST' })
}

/** POST /auth/password/request —— 请求重置邮件；无论邮箱是否存在都返回 200（不泄露账号存在性）。 */
export function requestPasswordReset(email: string): Promise<AllauthEnvelope> {
  return allauthRequest(BASE + '/auth/password/request', {
    method: 'POST',
    body: { email },
  })
}

/** GET /auth/password/reset —— key 走请求头 X-Password-Reset-Key，校验重置链接是否仍有效。 */
export function fetchPasswordResetInfo(key: string): Promise<AllauthEnvelope<{ user: AllauthUser }>> {
  return allauthRequest<{ user: AllauthUser }>(BASE + '/auth/password/reset', {
    headers: { 'X-Password-Reset-Key': key },
  })
}

/** POST /auth/password/reset —— 200 重置后自动登录；401 重置成功但需自行登录。 */
export function resetPassword(key: string, password: string): Promise<SessionEnvelope> {
  return allauthRequest<SessionData>(BASE + '/auth/password/reset', {
    method: 'POST',
    body: { key, password },
  })
}

/** POST /account/password/change —— 已登录用户改密码。 */
export function changePassword(currentPassword: string, newPassword: string): Promise<AllauthEnvelope> {
  return allauthRequest(BASE + '/account/password/change', {
    method: 'POST',
    body: { current_password: currentPassword, new_password: newPassword },
  })
}

/** 信封里是否存在某个待完成流程（如注册后待验邮箱）。 */
export function hasPendingFlow(envelope: SessionEnvelope, flowId: string): boolean {
  return Boolean(envelope.data?.flows?.some((f) => f.id === flowId && f.is_pending))
}

// --------------------------------------------------------------------------
//
// 路径与方法核对自本机 django-allauth 65.19.4 源码
// （`allauth/headless/account/urls.py` 的 `manage_email` +
//  `views.ManageEmailView` 的 input_class 映射）：
//   GET    列出本人全部邮箱地址
//   POST   {email}            新增一个地址并发验证信（AddEmailInput）
//   PATCH  {email, primary}   把**已验证**的地址设为主地址（MarkAsPrimaryEmailInput）
//   DELETE {email}            删除一个地址；主地址删不掉（DeleteEmailInput）
//   PUT    {email}            重发那个地址的验证信（ResendEmailVerificationInput）
//
// 后端 `ACCOUNT_CHANGE_EMAIL = True` + `ACCOUNT_MAX_EMAIL_ADDRESSES = 2`
// （`backend/config/settings/base.py`）：所以「改邮箱」= 加一个新地址、去新邮箱点验证信，
// 验证通过后新地址成为登录邮箱。**前端不替用户替换地址**，只把流程摆出来。
// --------------------------------------------------------------------------

/** 一条邮箱地址（allauth `EmailAddressesResponse` 的元素）。 */
export interface AllauthEmail {
  email: string
  verified: boolean
  primary: boolean
}

/** GET /account/email —— 本人的邮箱地址列表。 */
export function fetchEmailAddresses(): Promise<AllauthEnvelope<AllauthEmail[]>> {
  return allauthRequest<AllauthEmail[]>(BASE + '/account/email')
}

/** POST /account/email —— 添加新地址并发验证信（改邮箱的第一步）。 */
export function addEmailAddress(email: string): Promise<AllauthEnvelope<AllauthEmail[]>> {
  return allauthRequest<AllauthEmail[]>(BASE + '/account/email', {
    method: 'POST',
    body: { email },
  })
}

/** PUT /account/email —— 重发某个地址的验证信。 */
export function resendEmailAddressVerification(
  email: string,
): Promise<AllauthEnvelope<{ verification_sent?: boolean }>> {
  return allauthRequest<{ verification_sent?: boolean }>(BASE + '/account/email', {
    method: 'PUT',
    body: { email },
  })
}

/** DELETE /account/email —— 删掉一个非主地址（例如放弃一次改邮箱）。 */
export function removeEmailAddress(email: string): Promise<AllauthEnvelope<AllauthEmail[]>> {
  return allauthRequest<AllauthEmail[]>(BASE + '/account/email', {
    method: 'DELETE',
    body: { email },
  })
}

/** PATCH /account/email —— 把已验证的地址设为主地址（登录邮箱）。 */
export function markEmailPrimary(email: string): Promise<AllauthEnvelope<AllauthEmail[]>> {
  return allauthRequest<AllauthEmail[]>(BASE + '/account/email', {
    method: 'PATCH',
    body: { email, primary: true },
  })
}
