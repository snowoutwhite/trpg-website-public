/** 业务界面遵循后端权限与隐私约束。 */
import type { RuleSystemPreset } from '../api/home'
import type { CardStatus } from '../api/cards'
import { ruleArtFile } from './rule-art'

/** 状态筛选钮的文案常量。 */
export const CARD_STATUS_OPTIONS: readonly { value: CardStatus | ''; label: string }[] = [
  { value: '', label: '全部' },
  { value: 'alive', label: '尚存' },
  { value: 'torn', label: '撕卡' },
]

/** 卡池排序（地址栏 `?sort=` 的值）。`plays` 发给后端 `?ordering=plays`，见 CardPoolView 文件头。 */
export type CardSort = 'latest' | 'plays'

export const CARD_SORT_DEFAULT: CardSort = 'latest'

export const CARD_SORT_OPTIONS: readonly { value: CardSort; label: string }[] = [
  { value: 'latest', label: '最新' },
  { value: 'plays', label: '参团最多' },
]

/** 卡面要用的规则美术：后端规则预设自带的三档图优先，拿不到回落本地 `lib/rule-art.ts`。 */
export interface CardArt {
  image: RuleSystemPreset['image'] | null
  file: string
}

/**
 * 取一张卡的美术资源。
 * `preset` 传 `useHomeStore().presetByName(card.rule_system)` 的结果；为 null 表示
 * 站主没配这个规则（或接口没拿到），此时整块回落本地素材，绝不会出现空白卡面。
 */
export function cardArt(
  preset: RuleSystemPreset | null,
  ruleSystem: string,
  size: keyof RuleSystemPreset['image'] = 'card',
): CardArt {
  const image = preset ? preset.image : null
  const fromPreset = image ? image[size] || image.full || image.card || image.thumb : ''
  return { image, file: fromPreset || ruleArtFile(ruleSystem) }
}

/** 文件名后缀 → 一个短标签（PDF / XLSX / TXT…）。没有后缀时给「文件」。 */
export function fileKindText(name: string | null | undefined): string {
  const matched = /\.([a-z0-9]+)$/i.exec(name ?? '')
  return matched ? matched[1].toUpperCase() : '文件'
}

/** 字节数 → 人话（后端 `CharacterCardFile.size` 是精确字节数）。 */
export function fileSizeText(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}
