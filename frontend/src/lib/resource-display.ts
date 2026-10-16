/** 资源区的展示辅助（列表页与详情页共用，免得两边各写一遍）。 */
import { GENERIC_ART } from './rule-art'

/** 通用素材四张，按分类名稳定轮换（同一个分类永远是同一张，不会刷新一次换一张）。 */
const ART_POOL = [
  GENERIC_ART.books.file,
  GENERIC_ART.portrait.file,
  GENERIC_ART.camp.file,
  GENERIC_ART.overview.file,
]

/**
 * 分类名 → 底图。空分类落到第一张。
 *
 * 用字符和累加取模，不用 `Math.random`，也不用「列表里第几个」——
 * 翻页或换筛选时同一条资源必须还是同一张图。
 */
export function resourceArt(category: string): string {
  const key = (category ?? '').trim()
  if (!key) return ART_POOL[0]
  let sum = 0
  for (let i = 0; i < key.length; i += 1) sum = (sum + key.charCodeAt(i)) % 9973
  return ART_POOL[sum % ART_POOL.length]
}

/** 同一分类里并排几张图别一模一样：取景点按序号轮换（v2 `POS`）。 */
const FOCAL_POINTS = ['46% center', '66% 40%', '30% 55%', '52% 68%']

export function resourceFocal(index: number): string {
  return FOCAL_POINTS[Math.abs(index) % FOCAL_POINTS.length]
}

/** 外链的站点名，给「外部链接 · example.com」用；解析不了就给一句中性的。 */
export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return '站外'
  }
}

/**
 * 条目类型一行字：文件给后缀（`PDF`），外链给站点名。
 * **没有大小**（后端没这个字段，见文件头）。
 */
export function resourceTypeText(item: {
  kind: string
  url: string
  file_extension: string
}): string {
  if (item.kind === 'link') return '外部链接 · ' + hostOf(item.url)
  return item.file_extension ? item.file_extension.toUpperCase() + ' 文件' : '文件'
}
