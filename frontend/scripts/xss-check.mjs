/**
 * XSS 对抗测试（红队，自动化）。`npm run security` 的第二段。
 *
 * 做法：
 *   1. 用项目自带的 vite 把 `scripts/xss-entry.mjs`（它 import 真正的
 *      `src/lib/markdown.ts`）打成一个 IIFE；
 *   2. 内联进一张临时 HTML；
 *   3. 丢给本机 chrome-headless-shell（playwright 缓存里的那份）`--dump-dom` 真实执行；
 *   4. 把浏览器回传的 JSON 拆开断言。
 *
 * 为什么不在 Node 里直接跑：DOMPurify 没有 window 时 `isSupported=false`，
 * `sanitize()` 原样返回输入 —— 在 Node 里跑这套测试会得到一整片假绿灯。
 * mXSS 那一批载荷也只有真 HTML 解析器才复现得出来。
 *
 * 浏览器找不到时**退出码 2**（区别于断言失败的 1），并明说「未验证」，
 * 不允许因为跑不起来就当成通过。
 */
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const ROOT = resolve(HERE, '..')

/** 可能的无头浏览器位置，从上到下试。 */
const BROWSERS = [
  join(
    process.env.HOME ?? '',
    'Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell',
  ),
  join(
    process.env.HOME ?? '',
    'Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium',
  ),
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/chromium',
  '/usr/bin/google-chrome',
]

function findBrowser() {
  if (process.env.XSS_CHECK_BROWSER) return process.env.XSS_CHECK_BROWSER
  for (const path of BROWSERS) {
    if (path && existsSync(path)) return path
  }
  // 兜底：搜一下 playwright 缓存目录里任何一个 headless shell
  return null
}

async function bundle(outDir) {
  const { build } = await import('vite')
  // 路由表 import 了一堆 .vue（虽然是懒加载，打包器仍要解析），所以得挂 vue 插件。
  const vue = (await import('@vitejs/plugin-vue')).default
  await build({
    root: ROOT,
    configFile: false,
    logLevel: 'warn',
    plugins: [vue()],
    resolve: { alias: { '@': resolve(ROOT, 'src') } },
    // 这里没挂 @vitejs/plugin-vue，vue/pinia 的编译期常量得自己给，
    // 否则打出来的包一运行就 ReferenceError: __VUE_OPTIONS_API__ is not defined。
    define: {
      __VUE_OPTIONS_API__: 'true',
      __VUE_PROD_DEVTOOLS__: 'false',
      __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: 'false',
      [['process', 'env', 'NODE_ENV'].join('.')]: '"production"',
    },
    build: {
      outDir,
      emptyOutDir: true,
      sourcemap: false,
      minify: false,
      lib: {
        entry: resolve(HERE, 'xss-entry.mjs'),
        formats: ['iife'],
        name: 'XssCheck',
        fileName: () => 'xss-entry.js',
      },
    },
  })
  return join(outDir, 'xss-entry.js')
}

function runBrowser(browser, htmlPath) {
  const args = [
    '--headless',
    '--disable-gpu',
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--no-first-run',
    '--disable-extensions',
    // 断网：任何载荷想外连都失败，同时避免测试依赖网络
    '--host-resolver-rules=MAP * ~NOTFOUND',
    '--virtual-time-budget=8000',
    '--dump-dom',
    'file://' + htmlPath,
  ]
  return execFileSync(browser, args, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'ignore'] })
}

/** 与 xss-entry.mjs 的 MUST_REQUIRE_AUTH / MUST_REDIRECT 条数保持一致，只用于打印。 */
const MUST_GUARD_COUNT = 9
const MUST_REDIRECT_COUNT = 10

function fail(lines) {
  for (const line of lines) console.error(line)
}

async function main() {
  const browser = findBrowser()
  if (!browser) {
    console.error('✗ 找不到无头浏览器（chrome-headless-shell / Chromium / Chrome）。')
    console.error('  这套 XSS 断言**必须**在真浏览器里跑：DOMPurify 在 Node 里 isSupported=false，')
    console.error('  sanitize() 会原样返回输入，用 Node 跑等于假绿灯。')
    console.error('  装一个浏览器，或用 XSS_CHECK_BROWSER=<可执行文件> 指定路径后重跑。')
    process.exit(2)
  }

  const workDir = mkdtempSync(join(tmpdir(), 'trpg-xss-'))
  try {
    const buildDir = join(workDir, 'build')
    await bundle(buildDir)
    // 打好的包**单独成文件**用 <script src> 引：载荷字符串里有字面量 `</script>`，
    // 内联进 HTML 会把 script 标签提前闭掉（第一版就栽在这儿）。
    const htmlPath = join(buildDir, 'xss.html')
    writeFileSync(
      htmlPath,
      '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>xss</title></head>' +
        '<body><pre id="out">PENDING</pre><div id="stage"></div>' +
        '<script>window.onerror=function(m,s,l,c,e){' +
        "document.getElementById('out').textContent='XSSERR:'+(e&&e.stack||m);return true};" +
        '</script>' +
        '<script src="./xss-entry.js"></script></body></html>',
      'utf8',
    )

    const dom = runBrowser(browser, htmlPath)
    const err = /XSSERR:([\s\S]*?)<\/pre>/.exec(dom)
    if (err) {
      console.error('✗ 浏览器里脚本报错，测试没跑完：')
      console.error(err[1].slice(0, 2000))
      process.exit(2)
    }
    const match = /XSSJSONB64:([A-Za-z0-9+/=]*):END/.exec(dom)
    if (!match) {
      console.error('✗ 浏览器没有回传结果（页面可能报错了）。原始 DOM 前 2000 字：')
      console.error(dom.slice(0, 2000))
      process.exit(2)
    }
    const report = JSON.parse(Buffer.from(match[1], 'base64').toString('utf8'))

    const broken = report.results.filter((r) => r.violations.length > 0)
    const executed = report.fired
    const globalIssues = report.global

    console.log(`XSS 对抗测试：${report.results.length} 条载荷，浏览器 = ${browser.split('/').pop()}`)

    if (executed.length) {
      fail(['', '✗ 有脚本真的执行了（这是最高级别的破防）：'])
      for (const tag of executed) fail(['  - ' + tag])
    }
    if (globalIssues.length) {
      fail(['', '✗ 文档级别的污染：'])
      for (const g of globalIssues) fail(['  - ' + g])
    }
    if (broken.length) {
      fail(['', '✗ 洗出来的 DOM 仍然带着危险结构：'])
      for (const r of broken) {
        fail([`  [${r.kind}] ${r.name}`])
        for (const v of r.violations) fail(['      · ' + v])
        fail(['      输出：' + r.html.replace(/\s+/g, ' ').slice(0, 200)])
      }
    }

    const logoutIssues = report.logout ?? []
    if (logoutIssues.length) {
      fail(['', '✗ 登出没有清空 Pinia（换账号会看到上一个用户的数据）：'])
      for (const l of logoutIssues) fail(['  - ' + l])
    }

    const guardIssues = report.routeGuards ?? []
    if (guardIssues.length) {
      fail(['', '✗ 路由守卫有缺口（游客深链会先渲染受保护页面）：'])
      for (const g of guardIssues) fail(['  - ' + g])
    }

    const urlGuard = report.urlGuard ?? []
    if (urlGuard.length) {
      fail(['', '✗ lib/url-guard.ts 的协议白名单不对：'])
      for (const u of urlGuard) fail(['  - ' + u])
    }

    if (
      executed.length ||
      globalIssues.length ||
      broken.length ||
      urlGuard.length ||
      logoutIssues.length ||
      guardIssues.length
    ) {
      console.error('')
      console.error(
        `XSS 对抗测试失败：${broken.length} 条载荷破防，${executed.length} 次脚本执行，` +
          `${urlGuard.length} 条 url-guard 用例不过，${logoutIssues.length} 条登出清空断言不过，` +
          `${guardIssues.length} 条路由守卫断言不过。`,
      )
      process.exit(1)
    }

    // 正向用例也要确认没被洗过头（外链活着且带 noopener，站内链接活着）
    const positives = {
      'md-autolink-http': /<a [^>]*href="https:\/\/example\.com\/ok"[^>]*rel="noopener noreferrer"/,
      'md-relative-link': /<a [^>]*href="\/guide\/intro"/,
      'md-mailto': /<a [^>]*href="mailto:hi@example\.com"/,
    }
    const regressions = []
    for (const [name, pattern] of Object.entries(positives)) {
      const item = report.results.find((r) => r.name === name)
      if (!item || !pattern.test(item.html)) {
        regressions.push(`${name}：期望的正常输出不见了（sanitize 洗过头？）→ ${item ? item.html : '缺这条载荷'}`)
      }
    }
    if (regressions.length) {
      fail(['', '✗ 正向用例回归（安全但把正常内容也吃了）：', ...regressions.map((r) => '  - ' + r)])
      process.exit(1)
    }

    console.log(`✓ 全部 ${report.results.length} 条载荷未破防：0 次脚本执行、0 个危险标签/属性/协议残留。`)
    console.log('✓ 正向用例正常：外链带 rel=noopener noreferrer、站内相对链接与 mailto 存活。')
    console.log('✓ url-guard：safeExternalUrl / safeNextPath 全部用例通过（含协议相对地址与反斜杠变体）。')
    console.log('✓ 登出清空：auth store 在登出请求失败时也会清掉 me/会话状态，pinia state 里搜不到上一个用户。')
    console.log(
      `✓ 路由守卫：${MUST_GUARD_COUNT} 条受保护路由全部带 requiresAuth，` +
        `${MUST_REDIRECT_COUNT} 条并进团详情 / 「我的」标签的旧路径是纯重定向（不渲染组件），登录/注册页带 guestOnly。`,
    )
  } finally {
    rmSync(workDir, { recursive: true, force: true })
  }
}

await main()
