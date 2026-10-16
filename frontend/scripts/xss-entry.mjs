/**
 * XSS 对抗测试的**浏览器侧**入口。由 `scripts/xss-check.mjs` 用 vite 打成一个
 * IIFE、内联进一张 HTML，再丢给本机 chrome-headless-shell 真实执行。
 *
 * 为什么一定要真浏览器：DOMPurify 在没有 window 的 Node 里 `isSupported=false`，
 * `sanitize()` 会**原样返回输入**——用 Node 跑这套测试只会得到一片假绿灯。
 * mXSS 这一类载荷更是只有真 HTML 解析器才能复现。
 *
 * 结果写进 `#out` 的 textContent（JSON），由 `--dump-dom` 取回。
 */
import { createPinia, setActivePinia } from 'pinia'
import { renderMarkdown } from '../src/lib/markdown.ts'
import { safeExternalUrl, safeNextPath } from '../src/lib/url-guard.ts'
import { useAuthStore } from '../src/stores/auth.ts'
import { useSiteStore } from '../src/stores/site.ts'
import { PAYLOADS, FORBIDDEN_TAGS, URL_ATTRS, BAD_SCHEMES } from './xss-payloads.mjs'

/**
 * 换账号泄露：上一个用户的资料必须在登出时从 Pinia 里彻底清掉，
 * 否则 B 登录之前（或登录失败时）页面上还能读到 A 的邮箱/昵称。
 *
 * 这里不起后端：测试环境本来就断网，`authApi.logout()` 的 fetch 必然失败，
 * 正好顺带验证**「登出请求失败时也要清空」**——真实场景里退登时掉线就是这条路径。
 */
async function checkLogoutClears() {
  const bad = []
  const pinia = createPinia()
  setActivePinia(pinia)

  const auth = useAuthStore()
  const site = useSiteStore()
  const leaky = {
    id: 42,
    email: 'victim-a@example.invalid',
    email_verified: true,
    nickname: '上一个用户',
    avatar: '/media/avatars/deadbeef.webp',
    is_gm: true,
    is_banned: false,
    is_muted: false,
    is_deactivated: false,
    date_joined: '2026-01-01T00:00:00Z',
    nickname_change_available_at: null,
    has_pending_gm_application: true,
  }
  auth.authenticated = true
  auth.user = leaky
  auth.pendingEmailVerification = true
  void site.config

  try {
    await auth.logout()
  } catch {
    // 断网时 logout 请求本来就会抛；关键是 finally 里的 clear() 要生效
  }

  if (auth.user !== null) bad.push('登出后 auth.user 还留着上一个用户：' + JSON.stringify(auth.user))
  if (auth.authenticated !== false) bad.push('登出后 auth.authenticated 不是 false：' + String(auth.authenticated))
  if (auth.pendingEmailVerification !== false) bad.push('登出后 pendingEmailVerification 没复位')
  const dump = JSON.stringify(pinia.state.value)
  if (dump.includes(leaky.email)) bad.push('登出后整个 pinia state 里还能搜到上一个用户的邮箱')
  if (dump.includes(leaky.nickname)) bad.push('登出后整个 pinia state 里还能搜到上一个用户的昵称')
  return bad
}

/**
 * 路由守卫：所有「只有本人/本团能看」的页面都必须带 `meta.requiresAuth`，
 * 否则游客深链（比如 `/me/cards`）会先把组件渲染出来再被后端 401，
 * 中间那一帧就可能闪出受保护的骨架。
 *
 * 断言对象是**真实的 router 实例**（`router.getRoutes()`），不是源码正则。
 */
const MUST_REQUIRE_AUTH = [
  '/me',
  '/me/cards',
  '/me/cards/:id',
  '/me/player-card',
  '/me/gm-card',
  '/me/reports',
  '/games/new',
  '/games/:id/edit',
  '/games/:id/reports/edit',
]

/**
 * 并进别的页面的旧路径：**不再渲染组件**，而是 `redirect` 到目标页的 hash。
 *
 * - ：管理 / 互见 / 相册 / 团内战报 → `/games/:id#<tab>`（落点是公开的团详情页，
 *   页内每一格自己按身份渲染说明而不是数据）。
 * - ：报名 / 主持 / 评价 / 举报 / 通知 / 账号设置 → `/me#<组>-<子标签>`
 *   （落点 `/me` 自己带 `requiresAuth`，游客一样被挡在登录页）。
 *
 * 所以上面那条「必须 requiresAuth」的断言对它们已经不成立 —— 但它保护的性质
 * （游客深链不许闪出受保护骨架）必须继续被检查，只是换了检查方式：
 * 这些路径必须是**纯重定向**（没有 component）。把断言删掉等于把保证也删掉，所以是换不是减。
 */
const MUST_REDIRECT = [
  '/games/:id/manage',
  '/games/:id/mutual',
  '/games/:id/photos',
  '/games/:id/reports',
  '/me/signups',
  '/me/games',
  '/me/reviews',
  '/me/photo-reports',
  '/me/notifications',
  '/me/account',
]

async function checkRouteGuards() {
  const bad = []
  let routes
  try {
    const mod = await import('../src/router/index.ts')
    routes = mod.router.getRoutes()
  } catch (e) {
    return ['未验证：路由表导入失败（' + String(e) + '），本项没有结论，不要当成通过']
  }
  const byPath = new Map(routes.map((r) => [r.path, r]))
  for (const path of MUST_REQUIRE_AUTH) {
    const route = byPath.get(path)
    if (!route) {
      bad.push(`路由 ${path} 不见了（改路径了？清单要同步改）`)
      continue
    }
    if (route.meta?.requiresAuth !== true) bad.push(`路由 ${path} 没有 meta.requiresAuth`)
  }
  for (const path of MUST_REDIRECT) {
    const route = byPath.get(path)
    if (!route) {
      bad.push(`路由 ${path} 不见了（改路径了？清单要同步改）`)
      continue
    }
    if (!route.redirect) bad.push(`路由 ${path} 应该是纯重定向（并进团详情标签），现在没有 redirect`)
    if (route.components && Object.keys(route.components).length) {
      bad.push(`路由 ${path} 还挂着组件：重定向路由不该渲染任何东西`)
    }
  }
  // 登录/注册页反过来必须 guestOnly，免得已登录用户又走一遍登录流程
  for (const path of ['/auth/login', '/auth/signup']) {
    if (byPath.get(path)?.meta?.guestOnly !== true) bad.push(`路由 ${path} 没有 meta.guestOnly`)
  }
  return bad
}

/**
 * `lib/url-guard.ts` 的用例：外链协议白名单 + 登录回跳路径白名单。
 * 形状 [输入, 期望输出]；`''` 表示「必须被拒」。
 */
const EXTERNAL_CASES = [
  ['https://example.com/x', 'https://example.com/x'],
  ['http://example.com/x', 'http://example.com/x'],
  ['HTTPS://Example.com/x', 'HTTPS://Example.com/x'],
  ['javascript:alert(1)', ''],
  ['  javascript:alert(1)', ''],
  ['java\tscript:alert(1)', ''],
  ['java\nscript:alert(1)', ''],
  ['jAvAsCrIpT:alert(1)', ''],
  ['data:text/html,<script>alert(1)</script>', ''],
  ['vbscript:msgbox(1)', ''],
  ['file:///etc/passwd', ''],
  ['blob:https://example.com/x', ''],
  ['//evil.example/x', ''],
  ['https:evil.example', ''],
  ['/relative/path', ''],
  ['', ''],
  [null, ''],
]

const NEXT_CASES = [
  ['/me/cards', '/me/cards'],
  ['/games/1/manage?tab=x#y', '/games/1/manage?tab=x#y'],
  ['//evil.example/x', '/me'],
  ['/\\evil.example/x', '/me'],
  ['/\\\\evil.example/x', '/me'],
  ['\\\\evil.example/x', '/me'],
  ['https://evil.example/x', '/me'],
  ['javascript:alert(1)', '/me'],
  ['  //evil.example', '/me'],
  ['me', '/me'],
  ['', '/me'],
  [123, '/me'],
  ['/' + 'a'.repeat(600), '/me'],
]

function checkUrlGuard() {
  const bad = []
  for (const [input, want] of EXTERNAL_CASES) {
    const got = safeExternalUrl(input)
    if (got !== want) bad.push(`safeExternalUrl(${JSON.stringify(input)}) = ${JSON.stringify(got)}，期望 ${JSON.stringify(want)}`)
  }
  for (const [input, want] of NEXT_CASES) {
    const got = safeNextPath(input, '/me')
    if (got !== want) bad.push(`safeNextPath(${JSON.stringify(input)}) = ${JSON.stringify(got)}，期望 ${JSON.stringify(want)}`)
  }
  return bad
}

/** 浏览器解析 URL 时会吃掉的空白与控制字符；断言前按同样口径归一化（与 DOMPurify 的 ATTR_WHITESPACE 同集）。 */
// eslint-disable-next-line no-control-regex
const URL_NOISE = /[\u0000-\u0020\u00a0\u1680\u180e\u2000-\u2029\u205f\u3000]/g

/** 任何真的跑起来的脚本都会在这里留名。 */
const fired = []
window.__xssHit = (tag) => fired.push(String(tag))
window.alert = (v) => fired.push('alert:' + v)
window.prompt = (v) => fired.push('prompt:' + v)
window.confirm = (v) => fired.push('confirm:' + v)

const baseUriBefore = document.baseURI
/** 页面自带的 script 数量（onerror 兜底 + 本包），多出来的才是被注入的。 */
const scriptsBefore = document.querySelectorAll('script').length

function attrViolations(el) {
  const bad = []
  const tag = el.tagName.toLowerCase()
  if (FORBIDDEN_TAGS.has(tag)) bad.push(`标签 <${tag}> 存活`)
  if (el.namespaceURI !== 'http://www.w3.org/1999/xhtml') {
    bad.push(`非 HTML 命名空间元素 <${tag}>（${el.namespaceURI}）`)
  }
  for (const attr of Array.from(el.attributes)) {
    const name = attr.name.toLowerCase()
    const value = attr.value
    if (name.startsWith('on')) bad.push(`事件属性 ${name}="${value}"`)
    if (name === 'style') bad.push('style 属性存活')
    if (name === 'srcdoc') bad.push('srcdoc 属性存活')
    if (name.startsWith('data-')) bad.push(`data-* 属性存活：${name}`)
    if (URL_ATTRS.includes(name) && BAD_SCHEMES.test(value.replace(URL_NOISE, ''))) {
      bad.push(`危险协议 ${name}="${value}"`)
    }
  }
  if (tag === 'a' && el.getAttribute('target') === '_blank') {
    const rel = (el.getAttribute('rel') || '').toLowerCase()
    if (!rel.includes('noopener')) bad.push('a[target=_blank] 缺 rel=noopener')
  }
  return bad
}

async function main() {
  const results = []
  const stage = document.getElementById('stage')

  for (const payload of PAYLOADS) {
    let html = ''
    let error = ''
    try {
      html = renderMarkdown(payload.md)
    } catch (e) {
      error = String(e)
    }
    const host = document.createElement('div')
    host.setAttribute('data-case', payload.name)
    stage.appendChild(host)
    // 这一行就是 v-html 走的同一条路径
    host.innerHTML = html

    const violations = []
    if (error) violations.push('renderMarkdown 抛异常：' + error)
    // 断言只看**解析后的真实 DOM**，不做字符串正则粗筛。
    // 理由（第一版栽过）：`<code>&lt;img onerror=…&gt;</code>` 与 `title="a&quot; onerror=…"`
    // 这类输出里，`onerror=` 只是转义过的文本/属性值，字符串正则会一路误报；
    // 而 v-html 走的就是 innerHTML 这条解析路径，DOM 里没有的东西也伤不到人。
    for (const el of host.querySelectorAll('*')) violations.push(...attrViolations(el))

    results.push({ name: payload.name, kind: payload.kind, html, violations })
  }

  // 留时间给异步向量：img onerror / iframe / ontoggle / autofocus / 图片请求
  await new Promise((resolve) => setTimeout(resolve, 600))

  const global = []
  if (document.querySelectorAll('script').length > scriptsBefore) global.push('文档里多出了 <script>')
  if (document.querySelectorAll('iframe,object,embed,form,base,link,meta[http-equiv]').length) {
    global.push('文档里多出了 iframe/object/embed/form/base/link/meta')
  }
  if (document.baseURI !== baseUriBefore) global.push('document.baseURI 被 <base> 改掉了')
  // DOM clobbering：document.body 被 <form id="body"> 之类顶替
  if (!(document.body instanceof HTMLBodyElement)) global.push('document.body 被顶替')

  // 用 base64 回传：--dump-dom 会把 textContent 里的 < & 转义，base64 只含 ASCII 字母数字，
  // 不会被 HTML 序列化改写，省掉一层容易出错的反转义。
  const json = JSON.stringify({
    fired,
    global,
    results,
    urlGuard: checkUrlGuard(),
    logout: await checkLogoutClears(),
    routeGuards: await checkRouteGuards(),
  })
  const bytes = new TextEncoder().encode(json)
  let binary = ''
  for (const b of bytes) binary += String.fromCharCode(b)
  document.getElementById('out').textContent = 'XSSJSONB64:' + btoa(binary) + ':END'
}

// file:// 下的脚本是 opaque origin，window.onerror 只会给一句 "Script error."，
// 所以在这里自己把真实堆栈写进 #out，省得排查时两眼一抹黑。
main().catch((e) => {
  document.getElementById('out').textContent = 'XSSERR:' + ((e && e.stack) || String(e))
})
