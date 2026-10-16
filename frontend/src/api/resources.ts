/** 资源区（apps/resources）。 */
import { buildUrl, request } from './http'
import type { Paginated, PublicUser } from './site'

export type ResourceKind = 'file' | 'link'

export interface ResourceItem {
  id: number
  title: string
  description: string
  kind: ResourceKind
  category: string
  /** kind=link 时的外链；文件类为空串。 */
  url: string
  /** kind=file 时的鉴权下载路径；外链类为 null。 */
  download_url: string | null
  file_extension: string
  uploader: PublicUser | null
  is_approved: boolean
  created_at: string
  updated_at: string
}

export interface ResourceQuery {
  category?: string
  kind?: ResourceKind | ''
  page?: number
  page_size?: number
}

const BASE = '/api/v1/resources/'

export function fetchResources(query: ResourceQuery = {}): Promise<Paginated<ResourceItem>> {
  return request<Paginated<ResourceItem>>(buildUrl(BASE, { ...query }), {
    skipAuthRedirect: true,
  })
}

export function fetchResource(id: number | string): Promise<ResourceItem> {
  return request<ResourceItem>(BASE + id + '/', { skipAuthRedirect: true })
}

/** 分类清单的一项（`apps/resources/services.py:108` `approved_categories()`）。 */
export interface ResourceCategory {
  category: string
  count: number
}

/**
 * GET /api/v1/resources/categories/ —— 已审核资源的分类清单（去重计数），给筛选条用。
 * 后端只数已审核条目、剔掉空分类、按条数倒序（同数按名字），顺序稳定。
 * 游客可读。**不要再从已加载的当前页条目里自己汇总**（那样只覆盖一页，计数是错的）。
 */
export function fetchResourceCategories(): Promise<{ results: ResourceCategory[] }> {
  return request<{ results: ResourceCategory[] }>(BASE + 'categories/', {
    skipAuthRedirect: true,
  })
}
