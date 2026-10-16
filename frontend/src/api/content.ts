/**
 * 术语表 / 新人指南 / FAQ（apps/content）。游客可读，全部不分页。
 * 字段名核对自 apps/content/serializers.py 与 urls.py。
 */
import { request } from './http'

export interface GlossaryTerm {
  id: number
  term: string
  definition: string
  /** 别名，用于搜索命中（KP/守密人 指向同一条）。 */
  aliases: string[]
  order: number
}

export interface GuideSummary {
  id: number
  title: string
  slug: string
  order: number
}

export interface GuideDetail extends GuideSummary {
  /** Markdown 原文，渲染必须经 MarkdownView 的白名单 sanitize。 */
  body_markdown: string
  updated_at: string
}

export interface FaqItem {
  id: number
  question: string
  answer: string
  order: number
}

const BASE = '/api/v1/content'

export function fetchGlossary(): Promise<GlossaryTerm[]> {
  return request<GlossaryTerm[]>(BASE + '/glossary/')
}

export function fetchGuides(): Promise<GuideSummary[]> {
  return request<GuideSummary[]>(BASE + '/guides/')
}

export function fetchGuide(slug: string): Promise<GuideDetail> {
  return request<GuideDetail>(BASE + '/guides/' + encodeURIComponent(slug) + '/')
}

export function fetchFaqs(): Promise<FaqItem[]> {
  return request<FaqItem[]>(BASE + '/faqs/')
}
