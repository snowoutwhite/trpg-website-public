/**
 * 图标路径表（单色描边，viewBox 24×24，线宽 1.4）。
 *
 * 为什么单独成模块而不是留在 `AppIcon.vue` 里：`nav-links.ts` 要按图标名做类型约束
 * （写错名字应该在 typecheck 就炸，而不是运行时渲染出一个空 svg），
 * 而从 SFC 里导出类型要靠额外的普通 `<script>` 块，得不偿失。
 *
 * 出处：旧骨架的 15 个路径原样保留（现有 view 仍在用），
 * 另补 v2 `index.html` 的 `ICONS` 六个（sprout / compass / flag / folder / book / contact，
 * 其中 folder、book 与旧表重名，沿用旧路径不重复造）与底栏要的 home / report。
 * v2 原稿用了 `<circle>` / `<rect>`，这里一律改写成等价的 `<path>`，
 * 免得 `AppIcon` 为两个图标多出一套图元渲染分支。
 */
export const ICON_PATHS = {
  notice: ['M5 3h11l3 3v15H5z', 'M8.5 9h7', 'M8.5 13h7', 'M8.5 17h4'],
  cards: ['M3 8l8-4 10 4-10 4z', 'M3 12l8 4 10-4', 'M3 16l8 4 10-4'],
  book: ['M4 4h6a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H4z', 'M20 4h-6a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h6z'],
  glossary: ['M4 5h16', 'M4 12h10', 'M4 19h7', 'M17 14l4 6', 'M17 20l4-6'],
  person: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M4.5 20c1.3-3.6 4-5.5 7.5-5.5s6.2 1.9 7.5 5.5'],
  logout: ['M14 4H6v16h8', 'M12 12h9', 'M18 8.5l3.5 3.5L18 15.5'],
  arrow: ['M5 12h13', 'M12.5 6.5L19 12l-6.5 5.5'],
  back: ['M19 12H6', 'M11.5 6.5L5 12l6.5 5.5'],
  search: ['M11 4.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13z', 'M15.8 15.8L20.5 20.5'],
  download: ['M12 4v11', 'M8 11.5l4 4 4-4', 'M5 20h14'],
  bell: ['M6 9.5a6 6 0 0 1 12 0c0 4 1.5 5.4 2 5.9H4c.5-.5 2-1.9 2-5.9z', 'M10 19a2 2 0 0 0 4 0'],
  plus: ['M12 5.5v13', 'M5.5 12h13'],
  folder: ['M3 6.5h6l2 2.5h10V19a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z'],
  link: [
    'M10.5 13.5a4 4 0 0 0 5.7 0l2.5-2.5a4 4 0 0 0-5.7-5.7l-1.2 1.2',
    'M13.5 10.5a4 4 0 0 0-5.7 0l-2.5 2.5a4 4 0 0 0 5.7 5.7l1.2-1.2',
  ],
  file: ['M6 3.5h7l5 5V20.5H6z', 'M13 3.5v5h5'],

  /* ---- v2 新增 ---- */
  /** 首页（底栏第一格） */
  home: ['M4 10.5L12 4l8 6.5', 'M6 9.6V20h12V9.6', 'M10 20v-5.5h4V20'],
  /** 战报（底栏与顶栏「战报」） */
  report: ['M6 3.5h9l4 4V20.5H6z', 'M15 3.5v4h4', 'M9 12h7', 'M9 15.5h7', 'M9 8.5h3'],
  /** 找团 / 罗盘（v2 ICONS.compass，circle 改写为 path） */
  compass: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M15.5 8.5l-2 5-5 2 2-5z'],
  /** 新人指南（v2 ICONS.sprout） */
  sprout: ['M7 20h10', 'M12 20v-8', 'M12 12c0-4 3-6 7-6 0 4-3 6-7 6z', 'M12 14c0-3-2.5-5-6-5 0 3 2.5 5 6 5z'],
  /** 开团（v2 ICONS.flag） */
  flag: ['M5 21V4', 'M5 4h11l-2 4 2 4H5'],
  /** 角色卡（v2 ICONS.contact，rect + circle 改写为 path） */
  contact: [
    'M5 5h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z',
    'M9 9a2 2 0 1 0 0 4 2 2 0 0 0 0-4z',
    'M6 16c.5-1.5 1.7-2 3-2s2.5.5 3 2',
    'M14 10h4',
    'M14 13h4',
  ],
  /** 业务界面遵循后端权限与隐私约束。 */
  edit: ['M4 20h4L19 9l-4-4L4 16z', 'M14.5 5.5l4 4'],
} as const satisfies Record<string, readonly string[]>

export type IconName = keyof typeof ICON_PATHS
