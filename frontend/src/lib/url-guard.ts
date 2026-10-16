/**
 * URL 守卫：凡是**值可能来自用户或后端可写字段**的地址，进 DOM 之前都从这里过一道。
 *
 * 为什么前端还要再挡一次（后端已经用 `URLValidator(schemes=["http","https"])` 限过）：
 * - 后端那道校验只覆盖「新建/修改资源」这条路径；历史数据、直接改库、或哪天换了写入口，
 *   都可能让一个 `javascript:` 落进 `item.url`。而前端这一侧只要一渲染，就是**点一下就中**。
 * - 「改动最小化」不等于「只留一层」：这里是纯函数、没有依赖，代价几乎为零。
 *
 * 注意本模块**不负责转义**（Vue 的插值与属性绑定已经不会产生 HTML 注入），
 * 只负责回答「这个地址允许出现在 href / 跳转目标里吗」。
 */

/**
 * 浏览器解析 URL 前会吃掉的空白与控制字符。
 * `java\tscript:` / `java\nscript:` / 前导空格都是靠这些字符绕过朴素前缀判断的，
 * 所以比对协议之前先按浏览器的口径抹平。
 */
// eslint-disable-next-line no-control-regex
const URL_NOISE = /[\u0000-\u0020\u00a0\u1680\u180e\u2000-\u2029\u205f\u3000]/g

/** 外链只认 http/https，且必须带 `//`（`https:foo` 在浏览器里其实是相对地址）。 */
const EXTERNAL_OK = /^https?:\/\//i

/**
 * 外链白名单：通过返回原值，不通过返回空串。
 *
 * 调用方拿到空串就**不要渲染这个链接**（不是渲染成 `href=""`，那会指向当前页）。
 */
export function safeExternalUrl(raw: string | null | undefined): string {
  if (!raw) return ''
  const flat = raw.replace(URL_NOISE, '')
  return EXTERNAL_OK.test(flat) ? raw : ''
}

/**
 * 登录 / 401 之后回跳用的「站内路径」白名单。
 *
 * 只接受以单个 `/` 开头的本站绝对路径。挡掉三类写法：
 * - `//evil.example/x`、`/\evil.example/x`：协议相对地址，浏览器按**跨站**解析
 *   （URL 规范里 `\` 在 special scheme 下等同 `/`），是经典的开放重定向；
 * - `javascript:` / `data:`：`router.replace()` 拿到它虽然多半只会匹配到 404 路由，
 *   但不能依赖路由器的实现细节来当安全边界；
 * - 超长串：避免把攻击载荷原样带进地址栏。
 */
export function safeNextPath(raw: unknown, fallback = '/me'): string {
  if (typeof raw !== 'string') return fallback
  const flat = raw.replace(URL_NOISE, '')
  if (flat.length === 0 || flat.length > 512) return fallback
  if (flat[0] !== '/') return fallback
  // 反斜杠按 `/` 归一化后再看第二个字符，`/\evil.com` 与 `//evil.com` 一起挡掉
  if (flat.replace(/\\/g, '/').startsWith('//')) return fallback
  return flat
}
