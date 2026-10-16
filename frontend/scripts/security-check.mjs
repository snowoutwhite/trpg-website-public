/**
 * 前端安全静态扫描（红队，自动化）。`npm run security` 的第一段。
 *
 * 管的是「扒拉 HTML / 翻构建产物就能看到不该看的东西」这一类问题：
 *   A. 构建产物里有没有密钥、开发者路径、内网地址、后台路径、sourcemap、邮箱；
 *   B. `.env` 有没有漏进 git；
 *   C. 源码里有没有绕过约定的 XSS 出口（v-html / innerHTML / eval …）；
 *   D. 有没有往浏览器存储里写用户数据；
 *   E. `lib/markdown.ts` 的 sanitize 配置有没有被后人改松；
 *   F. 外链/跳转有没有过协议白名单。
 *
 * 只做**静态**判断；能不能被真的利用由 `scripts/xss-check.mjs` 在真浏览器里打。
 * 两段都进 `npm run security`。
 *
 * 加新规则的约定：一条规则 = 一个 `check()`，失败往 `problems` 里推一句人话 +
 * 命中的文件:行。不要 `process.exit` 在中途退出，要把所有问题一次报全。
 */
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const FRONTEND = resolve(HERE, '..')
const SRC = join(FRONTEND, 'src')
const DIST = join(FRONTEND, 'dist')
const REPO = resolve(FRONTEND, '..')

const problems = []
const notes = []

function problem(rule, message, hits = []) {
  problems.push({ rule, message, hits })
}

function walk(dir, filter) {
  const out = []
  if (!existsSync(dir)) return out
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    const st = statSync(full)
    if (st.isDirectory()) out.push(...walk(full, filter))
    else if (filter(full)) out.push(full)
  }
  return out
}

/** 在一批文件里找正则，返回 `{file, line, text}`。 */
function grep(files, pattern, { ignore } = {}) {
  const hits = []
  for (const file of files) {
    const lines = readFileSync(file, 'utf8').split('\n')
    lines.forEach((text, i) => {
      pattern.lastIndex = 0
      if (!pattern.test(text)) return
      if (ignore && ignore.test(text)) return
      hits.push({ file: relative(REPO, file), line: i + 1, text: text.trim().slice(0, 160) })
    })
  }
  return hits
}

const srcFiles = walk(SRC, (f) => /\.(ts|vue|css|js)$/.test(f))
const distFiles = walk(DIST, () => true)

// ==========================================================================
// A. 构建产物：不该被人扒出来的东西
// ==========================================================================

if (distFiles.length === 0) {
  problem('dist', 'frontend/dist 不存在或是空的：先 `npm run build` 再扫，否则这一整节等于没测。')
} else {
  // A1 密钥样式的字面量
  const secretish = grep(
    distFiles.filter((f) => /\.(js|css|html|json|svg)$/.test(f)),
    /(?:secret|api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|private[_-]?key|passwd|BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,})/i,
    // 字段名 password / new_password 是表单字段，不是密钥值
    { ignore: /autocomplete|type:?\s*`?password|`password`|"password"|current_password|new_password/ },
  )
  if (secretish.length) problem('dist-secret', '构建产物里出现了像密钥的字符串。', secretish)

  // A2 开发者本机路径
  const devPaths = grep(distFiles, /\/(?:Users|home)\/[A-Za-z0-9._-]+\//)
  if (devPaths.length) problem('dist-devpath', '构建产物里泄露了开发者本机路径。', devPaths)

  // A3 内网 / 本机地址
  const intranet = grep(
    distFiles,
    /(?:127\.0\.0\.1|0\.0\.0\.0|localhost:\d|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)/,
  )
  if (intranet.length) problem('dist-intranet', '构建产物里出现了内网/本机地址。', intranet)

  // A4 后台路径：前端根本不需要知道 Django admin 在哪
  const adminPath = grep(distFiles, /manage-console|DJANGO_[A-Z_]+|\/admin\//)
  if (adminPath.length) {
    problem('dist-admin', '构建产物里出现了后台路径或 Django 环境变量名（前端不该知道）。', adminPath)
  }

  // A5 sourcemap：生产产物不许带，否则整份 TS 源码可被还原
  const maps = distFiles.filter((f) => f.endsWith('.map'))
  const mapRefs = grep(distFiles, /sourceMappingURL/)
  if (maps.length) problem('dist-sourcemap', 'dist 里有 .map 文件。', maps.map((f) => ({ file: relative(REPO, f), line: 0, text: '' })))
  if (mapRefs.length) problem('dist-sourcemap', 'dist 里有 sourceMappingURL 引用。', mapRefs)

  // A6 真实邮箱：占位 example.com 放行，其余一律报
  const emails = grep(distFiles, /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/, {
    ignore: /@example\.(com|org|net)|@localhost|w3\.org|schemas\.|@媒体|@media|@import|@keyframes|@supports/,
  })
  if (emails.length) problem('dist-email', '构建产物里出现了真实邮箱地址。', emails)

  // A7 VITE_ 变量：只许放地址一类公开配置，出现未知的就报
  const viteVars = grep(distFiles, /VITE_(?!API_TARGET\b)[A-Z0-9_]+/)
  if (viteVars.length) {
    problem('dist-vite-env', 'dist 里出现了 VITE_API_TARGET 之外的 VITE_ 变量名（VITE_ 变量会被编译进产物，任何人都能看到）。', viteVars)
  }
}

// ==========================================================================
// B. .env：不许入库
// ==========================================================================

for (const name of ['.env', '.env.local', '.env.production', '.env.development']) {
  const rel = 'frontend/' + name
  let ignored
  try {
    execFileSync('git', ['check-ignore', '-q', rel], { cwd: REPO, stdio: 'ignore' })
    ignored = true
  } catch {
    ignored = false
  }
  if (!ignored) problem('env-gitignore', `${rel} 没有被 .gitignore 忽略；一旦有人建了这个文件就会被 commit 进去。`)
}
try {
  const tracked = execFileSync('git', ['ls-files', 'frontend'], { cwd: REPO, encoding: 'utf8' })
    .split('\n')
    .filter((p) => /\/\.env(?!\.example$)/.test(p))
  if (tracked.length) problem('env-tracked', 'git 里已经跟踪了 .env 文件。', tracked.map((p) => ({ file: p, line: 0, text: '' })))
} catch {
  notes.push('（跳过 git 跟踪检查：不在 git 仓库里或 git 不可用）')
}
// .env.example 里不许有真值
const exampleEnv = join(FRONTEND, '.env.example')
if (existsSync(exampleEnv)) {
  const bad = readFileSync(exampleEnv, 'utf8')
    .split('\n')
    .map((l, i) => ({ l: l.trim(), i }))
    .filter(({ l }) => /^(?!#)[A-Z0-9_]*(SECRET|KEY|TOKEN|PASSWORD)[A-Z0-9_]*=.+/i.test(l))
  if (bad.length) {
    problem('env-example', '.env.example 里疑似填了真值（模板只许留空）。', bad.map(({ l, i }) => ({ file: 'frontend/.env.example', line: i + 1, text: l })))
  }
}

// ==========================================================================
// C. 源码里的 XSS 出口
// ==========================================================================

const MARKDOWN_VIEW = join(SRC, 'components', 'MarkdownView.vue')
const vHtml = grep(
  srcFiles.filter((f) => f !== MARKDOWN_VIEW),
  /v-html\s*=/,
  { ignore: /^\s*[*/]|no-v-html/ },
)
if (vHtml.length) {
  problem('v-html', '除了 components/MarkdownView.vue，任何地方都不许用 v-html（用户内容一律插值渲染）。', vHtml)
}

const sinks = grep(srcFiles, /\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML|document\.write|\beval\s*\(|new\s+Function\s*\(|dangerouslySetInnerHTML/, {
  ignore: /^\s*[*/]/,
})
if (sinks.length) problem('dom-sink', '源码里出现了直接写 HTML / 执行字符串的危险出口。', sinks)

// C2 target=_blank 必须带 rel=noopener
const blanks = grep(srcFiles, /target\s*=\s*["']_blank["']/).filter((h) => !/noopener/.test(h.text))
if (blanks.length) problem('noopener', 'target="_blank" 没有配 rel="noopener noreferrer"（被打开的页面能通过 window.opener 反向操纵本站）。', blanks)

// C3 :href 绑定：只有白名单里的表达式可以直接绑，其余必须过 safeExternalUrl()
const HREF_ALLOWED = [
  /:href="safeExternalUrl\(/, // 已过协议白名单
  /:href="[a-zA-Z.?[\]0-9_]*download_url"/, // 后端下发的鉴权下载路径（同源）
  /:href="cardDownloadUrl\(/,
  /:href="current\.original_url"/,
  /:href="'#' \+ /, // 页内锚点
]
const hrefBinds = grep(srcFiles, /:href="/).filter((h) => !HREF_ALLOWED.some((ok) => ok.test(h.text)))
if (hrefBinds.length) {
  problem(
    'href-bind',
    '有 :href 绑定没走协议白名单：凡是值可能来自用户/后端可写字段的，都要 safeExternalUrl() 过一遍（javascript: 链接是点一下就中的 XSS）。' +
      '\n      确认某条确实安全的话，把它加进 scripts/security-check.mjs 的 HREF_ALLOWED 并写明理由。',
    hrefBinds,
  )
}

// ==========================================================================
// D. 浏览器存储 / 日志
// ==========================================================================

const storage = grep(srcFiles, /\b(localStorage|sessionStorage|indexedDB)\b|document\.cookie\s*=/, {
  ignore: /^\s*[*/]|no-restricted-globals|禁止用/,
})
if (storage.length) {
  problem('storage', '不许往浏览器存储里写凭据或用户数据（会话由后端 HttpOnly Cookie 承担）。', storage)
}

const logs = grep(srcFiles, /\bconsole\.(log|info|debug|warn|error|dir|table)\s*\(/, { ignore: /^\s*[*/]/ })
if (logs.length) {
  problem('console', '源码里有 console.*：生产构建没有配 drop，打出来的用户对象/邮箱会留在任何人的控制台里。', logs)
}

// ==========================================================================
// E. sanitize 配置不许被改松
// ==========================================================================

const mdPath = join(SRC, 'lib', 'markdown.ts')
if (!existsSync(mdPath)) {
  problem('markdown', '找不到 src/lib/markdown.ts —— 全站唯一的 HTML 产出口不见了？')
} else {
  const md = readFileSync(mdPath, 'utf8')
  const code = md
    .split('\n')
    .filter((l) => !/^\s*(\*|\/\/|\/\*)/.test(l))
    .join('\n')
  const must = [
    [/USE_PROFILES/, false, 'USE_PROFILES 会把自定义 ALLOWED_TAGS/ALLOWED_ATTR 整个覆盖成内置 html 档，白名单作废（dompurify 3.4.15 dist/purify.es.mjs:866）'],
    [/ADD_ATTR/, false, 'ADD_ATTR 会放宽属性白名单（尤其 target），外链的 rel 由钩子补，不要用 ADD_ATTR'],
    [/ADD_TAGS/, false, 'ADD_TAGS 会放宽标签白名单'],
    [/ADD_DATA_URI_TAGS/, false, 'ADD_DATA_URI_TAGS 会让更多标签接受 data: URI'],
    [/ALLOW_UNKNOWN_PROTOCOLS/, false, 'ALLOW_UNKNOWN_PROTOCOLS 会放行任意自定义协议'],
    [/WHOLE_DOCUMENT/, false, 'WHOLE_DOCUMENT 会把 html/head/body 一并放行'],
    [/RETURN_DOM|RETURN_TRUSTED_TYPE/, false, '本站只用字符串返回值，改返回类型会让 MarkdownView 的假设失效'],
    [/ALLOW_DATA_ATTR:\s*false/, true, 'ALLOW_DATA_ATTR 必须显式 false（data-* 可能夹带隐私字段）'],
    [/ALLOW_ARIA_ATTR:\s*false/, true, 'ALLOW_ARIA_ATTR 必须显式 false'],
    [/ALLOWED_URI_REGEXP/, true, '必须显式给 URL 协议白名单'],
    [/afterSanitizeAttributes/, true, '必须保留 afterSanitizeAttributes 钩子：它同时负责 data: 图二次拦截与外链 rel=noopener'],
  ]
  for (const [pattern, shouldExist, why] of must) {
    const found = pattern.test(code)
    if (found !== shouldExist) {
      problem('markdown-config', `lib/markdown.ts 的 sanitize 配置被改松了：${why}。`)
    }
  }
  for (const tag of ['script', 'iframe', 'object', 'embed', 'style', 'form', 'input', 'svg', 'math', 'link', 'meta', 'base']) {
    if (new RegExp(`ALLOWED_TAGS[\\s\\S]*?\\]`).exec(code)?.[0]?.includes(`'${tag}'`)) {
      problem('markdown-config', `lib/markdown.ts 的 ALLOWED_TAGS 里出现了 <${tag}>，白名单被放宽。`)
    }
  }
  const attrBlock = /ALLOWED_ATTR[\s\S]*?\]/.exec(code)?.[0] ?? ''
  for (const attr of ['style', 'target', 'srcset', 'onerror', 'onload', 'formaction', 'srcdoc']) {
    if (attrBlock.includes(`'${attr}'`)) {
      problem('markdown-config', `lib/markdown.ts 的 ALLOWED_ATTR 里出现了 ${attr}，属性白名单被放宽。`)
    }
  }
}

// ==========================================================================
// G. 隐私红线：邮箱、匿名评价
// ==========================================================================

/**
 * 允许出现 `.email` 的文件。判据是「这份数据只可能是**本人自己的**」：
 * - MeView：本人的身份条（只用 `email_verified` 这个布尔值下一个「邮箱待验证」标记）；
 * - components/me/SecurityPanel.vue：本人的「登录方式」块 —— 当前登录邮箱与正在验证的新邮箱，
 *   两者都来自只对本人开放的接口（`/accounts/me/` 与 allauth `/account/email`）。
 *   改邮箱住在这里，所以这一条是**跟着 UI 搬家**，不是把红线放宽；
 * - 登录 / 注册 / 找回密码：用户自己正在输入的那个邮箱（字段级错误也在里面）；
 * - VerifyEmailView：本人正在验证的那个邮箱；
 * - api/：类型定义与请求体，不产生 DOM。
 * 其它任何组件碰 `.email` 都要人工复核 —— 他人的邮箱不该在任何页面上出现，
 * 连 title / data-* / aria-label 里都不行。
 */
const EMAIL_OK = [
  'src/views/MeView.vue',
  'src/components/me/SecurityPanel.vue',
  'src/views/LoginView.vue',
  'src/views/SignupView.vue',
  'src/views/PasswordForgotView.vue',
  'src/views/VerifyEmailView.vue',
]
const emailHits = grep(
  srcFiles.filter((f) => f.endsWith('.vue') && !EMAIL_OK.some((ok) => f.endsWith(ok.replace('src/', '')))),
  /\.email\b|email_verified|"email"|'email'/,
  { ignore: /^\s*[*/]|email_enabled|inputmode|autocomplete|type="email"/ },
)
if (emailHits.length) {
  problem('privacy-email', '有组件碰了 email 字段：邮箱只许在本人页面出现，他人视角（含 title / data-* / aria-label）一律不行。', emailHits)
}

/**
 * 匿名评价红线：被评者看到的评价里，**任何能还原「谁写的」的线索都不许有**。
 * 后端 `AnonymousReview` 白名单只有 verdict / verdict_display / text / reviewee_role / game，
 * 前端再加编号、时间、排序，等于把 HMAC 打乱过的顺序重新可视化出来。
 */
const reviewsApi = existsSync(join(SRC, 'api', 'reviews.ts')) ? readFileSync(join(SRC, 'api', 'reviews.ts'), 'utf8') : ''
const anonBlock = /interface AnonymousReview[\s\S]*?\n}/.exec(reviewsApi)?.[0] ?? ''
if (!anonBlock) {
  problem('privacy-review', '在 api/reviews.ts 里找不到 AnonymousReview 接口，匿名红线无法校验。')
} else {
  for (const field of ['id', 'created_at', 'updated_at', 'reviewer', 'order', 'submitted_at']) {
    if (new RegExp(`\\b${field}\\??:`).test(anonBlock)) {
      problem('privacy-review', `AnonymousReview 里多了 \`${field}\`：这是评价人身份/顺序线索，要找后端删字段，不是前端藏起来。`)
    }
  }
}

/**
 * 渲染匿名评价的地方：不许出现时间与序号。
 *
 * **：把两条空转的规则修成真检查。**
 * 原清单里 `src/views/MutualReviewsView.vue`与 `src/views/ReviewsView.vue`
 * 都已不在仓库里，下面那句 `existsSync` 让它们**静默跳过** ——
 * 两条规则实际上一直在扫空气。现在改三件事，**都是加强不是放宽**：
 *   1. 清单只列**现承载组件**（互见 → `components/game/GameMutualTab.vue`；
 *      「我收到的」→ `components/me/ReviewsPanel.vue` 的右栏），并且**文件必须存在** ——
 *      指向一个不存在的文件直接报错，规则不许再静默空转；切片取空了同样报错。
 *   2. 禁用词从 6 个加到 12 个：补上评价人字段、提交/评审时间、`formatDate(`、`timeLeft(`
 *      与几种显式排序 / 序号写法。
 *   3. 新增**自动发现**：凡是碰了匿名评价数据（`AnonymousReview` / `fetchMutualPanel` /
 *      `fetchReceivedReviews`）的 `.vue` 都必须在清单里 —— 以后再搬家，忘了改清单会被这条抓住，
 *      不会像这次一样悄悄变成空转。
 * 只扫右栏那一段的原因不变：左栏「我给出的」本来就该显示窗口日期，整份扫会误报。
 */
const ANON_FORBIDDEN = [
  'created_at',
  'updated_at',
  'submitted_at',
  'reviewed_at',
  'formatDateTime',
  'formatDate(',
  'timeLeft(',
  '.reviewer',
  '{{ i ',
  '{{ i}}',
  '{{ index',
  '.sort(',
]
const ANON_RENDERERS = [
  ['src/components/game/GameMutualTab.vue', (s) => s],
  ['src/components/me/ReviewsPanel.vue', (s) => (/右：我收到的[\s\S]*$/.exec(s)?.[0] ?? '')],
]
for (const [file, slice] of ANON_RENDERERS) {
  const full = join(FRONTEND, file)
  if (!existsSync(full)) {
    problem(
      'privacy-review',
      `${file} 不在仓库里：匿名评价区的扫描清单指向了一个不存在的文件，这条规则等于没扫。` +
        `搬家了就把清单改到现承载组件上（scripts/security-check.mjs 的 ANON_RENDERERS）。`,
    )
    continue
  }
  const body = slice(readFileSync(full, 'utf8'))
  if (!body.trim()) {
    problem(
      'privacy-review',
      `${file} 的匿名评价区切片取空了：切片正则与文件对不上，这条规则等于没扫。`,
    )
    continue
  }
  for (const forbidden of ANON_FORBIDDEN) {
    if (body.includes(forbidden)) {
      problem('privacy-review', `${file} 的匿名评价区出现了 \`${forbidden}\`：不得给收到的评价加时间、序号或评价人线索。`)
    }
  }
}

// 自动发现：碰了匿名评价数据的 .vue 必须在上面的清单里（搬家忘改清单会被这条抓住）
for (const full of srcFiles.filter((f) => f.endsWith('.vue'))) {
  if (!/AnonymousReview|fetchMutualPanel|fetchReceivedReviews/.test(readFileSync(full, 'utf8'))) continue
  const rel = relative(FRONTEND, full)
  if (ANON_RENDERERS.some(([file]) => file === rel)) continue
  problem(
    'privacy-review',
    `${rel} 读了匿名评价数据，却不在匿名评价区的扫描清单里：` +
      `把它（连同要扫的切片）加进 scripts/security-check.mjs 的 ANON_RENDERERS，不要让新页面绕过这条红线。`,
  )
}

// ==========================================================================
// F. vite 构建配置
// ==========================================================================

const viteConfig = readFileSync(join(FRONTEND, 'vite.config.ts'), 'utf8')
if (!/sourcemap:\s*false/.test(viteConfig)) {
  problem('vite-sourcemap', 'vite.config.ts 没有显式 `build.sourcemap: false`；生产带 sourcemap 等于把整份源码送出去。')
}

// ==========================================================================
// 报告
// ==========================================================================

const SCANNED = `扫描范围：src/ ${srcFiles.length} 个文件，dist/ ${distFiles.length} 个文件。`
console.log('前端安全静态扫描')
console.log(SCANNED)
for (const note of notes) console.log(note)

if (problems.length === 0) {
  console.log('✓ 产物：无密钥/开发者路径/内网地址/后台路径/sourcemap/真实邮箱/额外 VITE_ 变量。')
  console.log('✓ 配置：.env 未入库且被忽略；.env.example 无真值；vite build.sourcemap=false。')
  console.log('✓ 出口：v-html 只在 MarkdownView；无 innerHTML/eval/document.write；:href 全部过白名单；')
  console.log('        target=_blank 全带 noopener；无 localStorage/sessionStorage/cookie 写入；无 console.*。')
  console.log('✓ sanitize：DOMPurify 白名单未被 USE_PROFILES / ADD_ATTR / ADD_TAGS 之类放宽。')
  console.log('✓ 隐私：email 只出现在本人页面；AnonymousReview 无 id/时间/评价人，匿名评价区无时间与序号。')
  process.exit(0)
}

console.error('')
for (const { rule, message, hits } of problems) {
  console.error(`✗ [${rule}] ${message}`)
  for (const h of hits.slice(0, 12)) {
    console.error(`      ${h.file}${h.line ? ':' + h.line : ''}  ${h.text}`)
  }
  if (hits.length > 12) console.error(`      …… 另有 ${hits.length - 12} 处`)
}
console.error('')
console.error(`静态扫描失败：${problems.length} 类问题。`)
process.exit(1)
