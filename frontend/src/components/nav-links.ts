/** 导航结构（v2）。 */
import type { IconName } from './icons'

export interface NavLink {
  to: string
  label: string
  icon: IconName
}

/** 顶栏主导航（≥768px 显示，手机上隐藏，由底栏承担）。 */
export const MAIN_NAV: NavLink[] = [
  { to: '/recruit', label: '找团', icon: 'compass' },
  { to: '/cards', label: '卡池', icon: 'cards' },
  { to: '/reports', label: '战报', icon: 'report' },
  { to: '/resources', label: '资源', icon: 'folder' },
  { to: '/guide', label: '手册', icon: 'book' },
]

/** 手机底栏五格（<768px 显示）。 */
export const BOTTOM_NAV: NavLink[] = [
  { to: '/', label: '首页', icon: 'home' },
  { to: '/recruit', label: '找团', icon: 'compass' },
  { to: '/cards', label: '卡池', icon: 'cards' },
  { to: '/reports', label: '战报', icon: 'report' },
  { to: '/me', label: '我', icon: 'person' },
]
