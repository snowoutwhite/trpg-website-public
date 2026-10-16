/** 规则美术映射：`rule_system` → 一张站主选定的底图。 */

/** 一个规则系统对应的美术资源。 */
export interface RuleArt {
  /** 前景清晰图的 URL（`<img src>` 用），已含站点根路径。 */
  file: string
  /** 给 `.c-blur-stage` 提供 `--art` 的 CSS 类名（同图虚化铺底用）。 */
  cssClass: string
}

/** 素材在站点里的公开路径前缀（`frontend/public/rule-art/` → 构建后 `/rule-art/`）。 */
export const RULE_ART_BASE = '/rule-art/'

/** 未知规则、空值、接口没配图时的兜底（v2 `shared.js` 的 `ruleFile()` 同样回落到 village.svg）。 */
export const RULE_ART_DEFAULT: RuleArt = {
  file: RULE_ART_BASE + 'village.svg',
  cssClass: 'art-default',
}

/**
 * 规则名 → 美术资源。键是**规范化后**的规则名（去首尾空白 + 转小写），
 * 因为 `rule_system` 是自由文本，站主可能写「dnd」「DnD」「DND 」。
 */
const RULE_ART_MAP: Readonly<Record<string, RuleArt>> = {
  dnd: { file: RULE_ART_BASE + 'castle.svg', cssClass: 'art-dnd' },
  coc: { file: RULE_ART_BASE + 'red-dice.svg', cssClass: 'art-coc' },
  三角机构: { file: RULE_ART_BASE + 'game-chip.svg', cssClass: 'art-triangle' },
  fu: { file: RULE_ART_BASE + 'sailboat.svg', cssClass: 'art-fu' },
}

/**
 * 另外 4 张通用素材：不绑定规则，供「快速选择」「精选战报」「个人空间」这类
 * 需要一张中性配图的位置直接取用（对应 `base.css` 的 `.art-*` 类）。
 */
export const GENERIC_ART: Readonly<Record<'camp' | 'portrait' | 'overview' | 'books', RuleArt>> = {
  camp: { file: RULE_ART_BASE + 'village.svg', cssClass: 'art-camp' },
  portrait: { file: RULE_ART_BASE + 'player-pawn.svg', cssClass: 'art-portrait' },
  overview: { file: RULE_ART_BASE + 'white-dice.svg', cssClass: 'art-overview' },
  books: { file: RULE_ART_BASE + 'playing-card.svg', cssClass: 'art-books' },
}

function normalize(ruleSystem: string | null | undefined): string {
  return (ruleSystem ?? '').trim().toLowerCase()
}

/**
 * 模糊匹配用的键序：**长的在前**。
 *
 * 为什么要模糊匹配：站级预设名可能带版本号（站主可能写「DND 5E」「COC 7th」，也可能写
 * 「三角机构 2e」），而 `Game.rule_system` 是自由文本。只做精确匹配的话这些全落到
 * art-default，首页与团卡会集体变成同一张默认图。
 *
 * 为什么按长度倒序而不是对象声明序：短键会吃掉长键的名字（`fu` 是很多名字里的子串），
 * 长键先试可以让「三角机构 2e」命中三角机构而不是某个两字母键，并且结果不依赖
 * `RULE_ART_MAP` 的书写顺序 —— 同一个规则名在任何环境下都取到同一张图。
 */
const RULE_ART_KEYS: readonly string[] = Object.keys(RULE_ART_MAP).sort(
  (a, b) => b.length - a.length,
)

/** 取一个规则系统的美术资源；未知值回落 `art-default`，**永远不会返回 null**。 */
export function ruleArt(ruleSystem: string | null | undefined): RuleArt {
  // Object.hasOwn：`rule_system` 是自由文本，「constructor」「__proto__」之类会命中原型链属性，不能用 `??` 兜底
  const key = normalize(ruleSystem)
  if (!key) return RULE_ART_DEFAULT
  if (Object.hasOwn(RULE_ART_MAP, key)) return RULE_ART_MAP[key]
  // 先「以预设键开头」（「DND 5E」→ dnd），再退一步看「包含」（「克苏鲁 COC 七版」→ coc）
  for (const candidate of RULE_ART_KEYS) {
    if (key.startsWith(candidate)) return RULE_ART_MAP[candidate]
  }
  for (const candidate of RULE_ART_KEYS) {
    if (key.includes(candidate)) return RULE_ART_MAP[candidate]
  }
  return RULE_ART_DEFAULT
}

/** 只要 CSS 类名（`.c-blur-stage` 的同图虚化铺底）。 */
export function ruleArtClass(ruleSystem: string | null | undefined): string {
  return ruleArt(ruleSystem).cssClass
}

/** 只要图片 URL（`<img src>` 的前景清晰图）。 */
export function ruleArtFile(ruleSystem: string | null | undefined): string {
  return ruleArt(ruleSystem).file
}

/**
 * 这个规则名是否**确实**配了图（口径与 `ruleArt()` 一致：精确 → 开头 → 包含）。
 * 没配图的规则要隐藏「了解该规则」一类依赖图文的入口。
 */
export function hasRuleArt(ruleSystem: string | null | undefined): boolean {
  return ruleArt(ruleSystem) !== RULE_ART_DEFAULT
}
