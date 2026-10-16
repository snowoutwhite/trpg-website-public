/**
 * 统一 fetch 封装。
 *
 * 约定：
 * - 全站走会话 Cookie（django-allauth headless「browser」客户端），因此固定 credentials: 'include'。
 * - 写操作自动从 csrftoken Cookie 读值放进 X-CSRFToken 头（Django 默认 CSRF_HEADER_NAME=HTTP_X_CSRFTOKEN）。
 * - 前端不存任何 token，不写 localStorage。
 * - 失败一律抛 ApiError，字段级错误在 errors[].param 上。
 */

/** 后端错误项，形状取自 allauth headless 的 ErrorResponse 与后端 DRF 统一错误格式。 */
export interface ApiErrorItem {
  message: string
  code: string
  param?: string
}

/** allauth headless 的响应信封；DRF 接口不带 status 字段，直接是数据。 */
export interface AllauthEnvelope<T = unknown> {
  status: number
  data?: T
  meta?: Record<string, unknown>
  errors?: ApiErrorItem[]
}

export class ApiError extends Error {
  readonly status: number
  readonly errors: ApiErrorItem[]
  readonly payload: unknown

  constructor(status: number, errors: ApiErrorItem[], payload: unknown, message?: string) {
    super(message ?? errors[0]?.message ?? '本次操作未能完成，请重试。')
    this.name = 'ApiError'
    this.status = status
    this.errors = errors
    this.payload = payload
  }

  /** 按字段名归拢错误，供表单逐字段显示。 */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {}
    for (const e of this.errors) {
      if (e.param && !out[e.param]) out[e.param] = e.message
    }
    return out
  }

  /** 不属于任何字段的整体错误（表单顶部横幅）。 */
  formMessage(): string {
    const general = this.errors.find((e) => !e.param)
    if (general) return general.message
    if (this.errors.length === 0) return this.message
    return ''
  }
}

/** 未登录时的跳转处理器，由 router 注册，避免 http 反向依赖路由。 */
type UnauthorizedHandler = () => void
let unauthorizedHandler: UnauthorizedHandler | null = null

export function setUnauthorizedHandler(fn: UnauthorizedHandler): void {
  unauthorizedHandler = fn
}

export function readCookie(name: string): string {
  const prefix = name + '='
  for (const part of document.cookie ? document.cookie.split('; ') : []) {
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length))
  }
  return ''
}

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE'])

export interface RequestOptions {
  method?: string
  /** JSON 请求体；GET 时忽略。 */
  body?: unknown
  /** 文件上传用的 multipart 请求体；给了它就不再序列化 body，也不手写 Content-Type。 */
  formData?: FormData
  headers?: Record<string, string>
  /** 这些状态码不抛错，原样返回解析后的响应体（allauth 用 401/409/410 表达流程状态）。 */
  passStatuses?: number[]
  /** 收到 401 时不触发全局跳登录（认证类接口自己处理）。 */
  skipAuthRedirect?: boolean
}

interface RawResult {
  status: number
  payload: unknown
}

async function raw(path: string, options: RequestOptions): Promise<RawResult> {
  const method = (options.method ?? 'GET').toUpperCase()
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(options.headers ?? {}),
  }

  let body: BodyInit | undefined
  if (!SAFE_METHODS.has(method)) {
    if (options.formData !== undefined) {
      // multipart：Content-Type 必须由浏览器自己带 boundary，手写会让后端解析失败。
      body = options.formData
    } else if (options.body !== undefined) {
      headers['Content-Type'] = 'application/json'
      body = JSON.stringify(options.body)
    }
  }
  if (!SAFE_METHODS.has(method)) {
    const csrf = readCookie('csrftoken')
    if (csrf) headers['X-CSRFToken'] = csrf
  }

  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers,
      body,
      credentials: 'include', // 同域会话 Cookie
    })
  } catch {
    throw new ApiError(0, [], null, '网络连接失败，请检查网络后重试。')
  }

  let payload: unknown = null
  if (response.status !== 204) {
    const text = await response.text()
    if (text) {
      try {
        payload = JSON.parse(text)
      } catch {
        payload = text
      }
    }
  }
  return { status: response.status, payload }
}

/** 业务界面遵循后端权限与隐私约束。 */
function extractFromEnvelope(error: Record<string, unknown>): ApiErrorItem[] {
  const code = typeof error.code === 'string' ? error.code : 'error'
  const message = typeof error.message === 'string' ? error.message : '本次操作未能完成，请重试。'
  const out: ApiErrorItem[] = [{ message, code }]
  const detail = error.detail
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    for (const [field, value] of Object.entries(detail as Record<string, unknown>)) {
      const text = Array.isArray(value) ? String(value[0]) : String(value)
      if (!text) continue
      if (field === 'non_field_errors') out.push({ message: text, code })
      else out.push({ message: text, code, param: field })
    }
  }
  return out
}

function extractErrors(status: number, payload: unknown): ApiErrorItem[] {
  if (payload && typeof payload === 'object') {
    const p = payload as Record<string, unknown>
    // allauth headless：{status, errors:[{message, code, param}]}
    if (Array.isArray(p.errors)) return p.errors as ApiErrorItem[]
    // 本站 DRF 统一错误格式
    if (p.error && typeof p.error === 'object' && !Array.isArray(p.error)) {
      return extractFromEnvelope(p.error as Record<string, unknown>)
    }
    // DRF 常见形状：{detail: "..."} 或 {field: ["msg", ...]}
    if (typeof p.detail === 'string') return [{ message: p.detail, code: 'error' }]
    const out: ApiErrorItem[] = []
    for (const [key, value] of Object.entries(p)) {
      const msg = Array.isArray(value) ? String(value[0]) : typeof value === 'string' ? value : ''
      if (msg) out.push({ message: msg, code: 'invalid', param: key === 'non_field_errors' ? undefined : key })
    }
    if (out.length) return out
  }
  return [{ message: defaultMessage(status), code: 'error' }]
}

function defaultMessage(status: number): string {
  if (status === 403) return '你没有权限进行此操作。'
  if (status === 404) return '未找到相关内容。'
  if (status === 429) return '操作过于频繁，请稍后再试。'
  if (status >= 500) return '服务器出现异常，请稍后再试。'
  return '本次操作未能完成，请重试。'
}

/** 发一个请求；非 2xx 且不在 passStatuses 内则抛 ApiError。 */
export async function request<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { status, payload } = await raw(path, options)
  const passed = options.passStatuses ?? []

  if (status >= 200 && status < 300) return payload as T
  if (passed.includes(status)) return payload as T

  if (status === 401 && !options.skipAuthRedirect) unauthorizedHandler?.()
  throw new ApiError(status, extractErrors(status, payload), payload)
}

/** 拼查询串：值为 undefined 或空串的参数一律略去，避免把 `?kind=` 发给后端。 */
export function buildUrl(
  base: string,
  params: Record<string, string | number | boolean | undefined> = {},
): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const query = search.toString()
  return query ? base + '?' + query : base
}

/** 上传文件：multipart/form-data，CSRF 头与会话 Cookie 与普通请求一致。 */
export function upload<T = unknown>(
  path: string,
  formData: FormData,
  options: Omit<RequestOptions, 'body' | 'formData'> = {},
): Promise<T> {
  return request<T>(path, { method: 'POST', ...options, formData })
}

/** allauth headless 专用：200/401/409/410 都是有意义的流程状态，统一返回信封。 */
export async function allauthRequest<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<AllauthEnvelope<T>> {
  const payload = await request<AllauthEnvelope<T>>(path, {
    ...options,
    skipAuthRedirect: true,
    passStatuses: [401, 409, 410, ...(options.passStatuses ?? [])],
  })
  if (payload && typeof payload === 'object') return payload
  return { status: 200 }
}
