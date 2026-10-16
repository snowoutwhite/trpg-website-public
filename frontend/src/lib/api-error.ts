/** 后端错误 → 页面文案的统一映射（缺陷 D2 / D2b）。 */
import { ApiError } from '../api/http'
import type { ApiErrorItem } from '../api/http'

/** 后端兜底文案，对用户没有信息量：一律换成调用方给的上下文话。 */
const CONTEXTLESS_CODES = new Set([
  'not_found',
  'bad_request',
  'business_error',
  'error',
  // 字段级校验失败：整体那句对用户没有落点，具体原因落到各格红字（终版表十·通用兜底）。
  'validation_error',
])

/** 全站统一的 code → 人话。只收「后端原话不够用」或「要提示下一步」的码。 */
const CODE_TEXT: Record<string, string> = {
  // 未登录：DRF 内置那句「身份认证信息未提供。」对用户零信息量
  not_authenticated: '这项操作需要登录，请先登录后再试。',
  // 账号处置（后端 common/exceptions.py 的三个码）
  account_muted: '你的账号目前处于禁言状态，禁言期间不能放团、报名或提交评价。',
  account_banned: '你的账号已被封禁，无法进行这项操作。',
  account_deactivated: '这个账号已经注销，无法进行这项操作。',
  // 交卡（2026-09-23 拆码后这两个码各有唯一来源，文案取后端各自的 default_detail 原句）
  card_not_usable: '这张角色卡已经撕卡，不能再用于报名。',
  // games/services.py::SignupCardFileMissing —— 拿空壳卡去交卡
  signup_card_file_missing: '这张角色卡还没有上传文件。请先为它上传角色卡文件，再回来交卡。',
  // charactercards/views.py::CardFileMissing —— 下载一张没传过文件的卡
  card_file_missing: '这张角色卡还没有上传文件，因此暂时无法下载。',
  // 权限
  // games/services.py::NotGameGM —— 非本团 GM 做团管理动作
  not_game_gm: '只有本团的 GM 才能进行这项操作。',
  // 相册三码（2026-09-23 从 not_game_gm / game_not_finished / already_reported 拆出，文案取 gallery 原句）
  photo_not_game_gm: '只有本团的 GM 才能上传本团的照片。',
  photo_game_not_finished: '本团结团后才能上传照片。',
  // photo_already_reported 不进映射表：后端按情形回两句不同原话（「已举报过」/「上一条举报还在处理中」），由 errorText() 直接带出
  // games/services.py::NotGM —— 非 GM 想放团
  not_gm: '只有拥有 GM 身份的账号才能放团。',
  // profiles/views.py::NoGMCard —— 非 GM 打开「我的 GM 卡」
  no_gm_card: '你还没有获得 GM 身份，因此暂时没有 GM 卡。',
  // 其他
  throttled: '你的操作过于频繁，请等待片刻后再试。',
}

/** 取后端错误信封里的机器码；不是 ApiError（或网络失败）时返回空串。 */
export function errorCode(e: unknown): string {
  if (!(e instanceof ApiError)) return ''
  return e.errors[0]?.code ?? ''
}

/** 取 HTTP 状态码；不是 ApiError 时返回 0（网络失败也是 0）。 */
export function errorStatus(e: unknown): number {
  return e instanceof ApiError ? e.status : 0
}

/**
 * 把任意异常翻译成一句能直接显示的中文。
 *
 * @param fallback 这个页面/这次动作的上下文话，用于「后端没给有用信息」时。
 * @param overrides 本页特有的 code → 文案，优先级最高。
 */
export function errorText(
  e: unknown,
  fallback: string,
  overrides: Record<string, string> = {},
): string {
  if (!(e instanceof ApiError)) return fallback
  // 网络失败（status 0）：「网络连接失败，请检查网络后重试。」比页面兜底话更有信息量。
  if (e.status === 0) return e.message || fallback
  const code = errorCode(e)
  if (code && overrides[code]) return overrides[code]
  if (code && CODE_TEXT[code]) return CODE_TEXT[code]
  if (!code || CONTEXTLESS_CODES.has(code)) return fallback
  return e.message || fallback
}

/**
 * Django / DRF / allauth 的**内置译文** → 本站终版文案。
 *
 * 这些消息不经过本站的错误信封（`common/exceptions.py`），文字由框架的 .po 决定，
 * 本机没有 gettext 工具链、且「你/您」人称尚未定案，所以不做 .po 覆盖，
 * 改为在前端按错误自带的 `code` 识别后换成本站文案。
 * key 取自 `allauth/account/adapter.py` 的 `error_messages` 键与 Django 校验器的 code。
 */
const BUILTIN_TEXT: Record<string, string> = {
  // allauth
  email_password_mismatch: '邮箱或密码不正确，请重新输入。',
  too_many_login_attempts: '登录尝试过于频繁，系统已暂时限制登录，请等待几分钟后再试。',
  email_taken: '这个邮箱已经注册过账号。请直接登录；如果忘记了密码，可以通过「忘记密码」重新设置。',
  invalid_or_expired_key: '这条链接已经失效，可能已经使用过或已超过有效期。',
  invalid_password_reset: '这条重置密码的链接已经失效，请重新申请一封重置密码邮件。',
  incorrect_password: '当前密码不正确，请重新输入。',
  enter_current_password: '请先填写当前密码。',
  duplicate_email: '这个邮箱已经关联在你的账号上，无需重复提交。',
  max_email_addresses: '你已经有一个等待验证的新邮箱。请先完成那个邮箱的验证，或撤销上一次邮箱变更，然后再提交。',
  account_inactive: '这个账号已停用，无法登录。',
  unverified_primary_email: '请先完成邮箱验证，然后再继续操作。',
  // Django 内置校验器
  password_too_short: '密码长度不足，至少需要 8 位。',
  required: '这一项必须填写。',
}

/** `code` 本身太泛、必须连 `param` 一起认的内置译文，key = `code:param`。 */
const BUILTIN_PARAM_TEXT: Record<string, string> = {
  'invalid:email': '邮箱格式不正确，请检查后重试。',
}

/** 单条错误项 → 显示文案：内置译文换成本站话，其余用后端原话。 */
function itemText(item: ApiErrorItem): string {
  const code = item.code ?? ''
  if (item.param && BUILTIN_PARAM_TEXT[code + ':' + item.param]) {
    return BUILTIN_PARAM_TEXT[code + ':' + item.param]
  }
  if (BUILTIN_TEXT[code]) return BUILTIN_TEXT[code]
  return item.message
}

/**
 * 表单顶部横幅：`ApiError.formMessage()` 的翻译版。
 *
 * 认证五页与「登录方式」面板直接显示 allauth 的原话，所以这几处必须走本函数，
 * 否则「您提供的电子邮件地址和/或密码不正确。」之类的内置译文会原样露给用户。
 */
export function formText(e: unknown): string {
  if (!(e instanceof ApiError)) return ''
  const general = e.errors.find((item) => !item.param)
  if (general) return itemText(general)
  if (e.errors.length === 0) return e.message
  return ''
}

/** 字段级红字：`ApiError.fieldErrors()` 的翻译版。 */
export function fieldText(e: unknown): Record<string, string> {
  if (!(e instanceof ApiError)) return {}
  const out: Record<string, string> = {}
  for (const item of e.errors) {
    if (item.param && !out[item.param]) out[item.param] = itemText(item)
  }
  return out
}
