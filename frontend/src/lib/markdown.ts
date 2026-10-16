/**
 * Markdown → 安全 HTML。
 *
 * 全站唯一被允许把字符串交给 v-html 的产出口（渲染在 `components/MarkdownView.vue`）。
 * 两道工序缺一不可：
 *   1. `marked` 把 Markdown 编译成 HTML（同步模式，不用异步扩展）；
 *   2. `DOMPurify` 按**白名单**重洗一遍 DOM —— 标签、属性、URL 协议三层都是白名单。
 *
 * 白名单里没有 script / iframe / object / embed / style / form / svg；
 * 事件属性（on*）不在允许属性里，因此 `<img src=x onerror=...>` 会被剥成裸 <img>；
 * `javascript:` 之类的 URL 过不了 ALLOWED_URI_REGEXP。
 * **`data:` 图片得靠下面的钩子另外堵**——DOMPurify 对 `img` 的 `data:` 有硬编码放行，
 * 见 `installHook()` 的注释（2026-09-21 前端安全对抗代理实测出来的口子）。
 * 外链统一补 target=_blank + rel="noopener noreferrer"（在 sanitize 之后的钩子里设，
 * 所以不需要把 target / rel 放进允许属性，恶意输入也伪造不出来）。
 */
import DOMPurify from 'dompurify'
import { Marked } from 'marked'

const marked = new Marked({ gfm: true, breaks: false, async: false })

/** 允许出现的标签：正文排版 + 表格 + 代码块，仅此而已。 */
const ALLOWED_TAGS = [
  'p', 'br', 'hr',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'strong', 'em', 'del', 's', 'sup', 'sub', 'mark',
  'blockquote', 'pre', 'code',
  'ul', 'ol', 'li',
  'table', 'thead', 'tbody', 'tr', 'th', 'td',
  'a', 'img', 'span', 'div',
]

/** 允许出现的属性：没有任何 on* 事件属性，也没有 style。 */
const ALLOWED_ATTR = ['href', 'title', 'alt', 'src', 'start', 'colspan', 'rowspan', 'align']

/** URL 协议白名单：http/https/mailto，或不含协议的站内相对地址（无冒号即无协议）。 */
const ALLOWED_URI_REGEXP = /^(?:https?:|mailto:|[^:]*$)/i

/** URL 型属性：二次校验就盯这几个。 */
const URI_ATTRS = ['href', 'src', 'xlink:href', 'action', 'formaction', 'poster', 'background']

/**
 * 浏览器解析 URL 前会吃掉的空白与控制字符，比对协议之前先按同样口径抹平。
 * 取值与 dompurify 3.4.15 的 `ATTR_WHITESPACE` 一致（已核对 dist/purify.es.mjs）。
 */
// eslint-disable-next-line no-control-regex
const ATTR_WHITESPACE = /[\u0000-\u0020\u00a0\u1680\u180e\u2000-\u2029\u205f\u3000]/g

let hookInstalled = false

/**
 * sanitize 之后的属性收口，做两件事：
 *
 * 1. **URL 协议二次校验**。不能只靠 `ALLOWED_URI_REGEXP`：dompurify 3.4.15
 *    在 `dist/purify.es.mjs:2045` 有一条硬编码的例外 —— `src`/`href`/`xlink:href`
 *    只要以 `data:` 开头、且标签在内置的 `DATA_URI_TAGS`
 *    （`audio/video/img/source/image/track`，见同文件 741 行）里，就**绕过白名单直接放行**，
 *    而这个集合只能 `ADD_DATA_URI_TAGS` 往里加、没有任何配置能把 `img` 摘出去。
 *    结果就是 `<img src="data:image/svg+xml;base64,…">` 会原样活下来。
 *    本站不要 `data:` 图：它能把任意字节内联进正文，绕过图片上传的大小与魔数校验。
 *    所以这里对留下来的 URL 属性再按 `ALLOWED_URI_REGEXP` 过一遍，不合格就整条删掉。
 * 2. **外链补 `target="_blank" rel="noopener noreferrer"`**。放在这里设而不是进属性白名单，
 *    恶意输入就伪造不出 `target`（白名单里根本没有它，进来先被剥掉，再由我们补）。
 */
function installHook(): void {
  if (hookInstalled) return
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (!(node instanceof Element)) return

    for (const name of URI_ATTRS) {
      if (!node.hasAttribute(name)) continue
      const raw = node.getAttribute(name) ?? ''
      if (!ALLOWED_URI_REGEXP.test(raw.replace(ATTR_WHITESPACE, ''))) {
        node.removeAttribute(name)
      }
    }

    if (node.tagName !== 'A') return
    const href = node.getAttribute('href') ?? ''
    if (/^(?:https?:)?\/\//i.test(href)) {
      node.setAttribute('target', '_blank')
      node.setAttribute('rel', 'noopener noreferrer')
    }
  })
  hookInstalled = true
}

/** 把 Markdown 渲染成可以安全交给 v-html 的 HTML 字符串。 */
export function renderMarkdown(source: string): string {
  if (!source) return ''
  installHook()
  const rawHtml = marked.parse(source, { async: false })
  return DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOWED_URI_REGEXP,
    FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'style', 'form', 'input', 'link', 'meta'],
    FORBID_ATTR: ['style', 'srcset', 'formaction', 'xlink:href'],
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
    // 注意：**绝不能**同时传 USE_PROFILES —— 已核对 dompurify 3.4.15 源码
    // （dist/purify.es.mjs 第 866 行）：USE_PROFILES 会把上面的 ALLOWED_TAGS /
    // ALLOWED_ATTR 整个覆盖成内置 html 档（含 form、input 等），白名单等于作废。
  })
}
