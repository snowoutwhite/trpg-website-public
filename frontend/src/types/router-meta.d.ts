/** 路由 meta 的增量声明。 */
import 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    /** 顶栏变体。`glass` = 压在首屏深色图上的深色玻璃（白字）； */
    headerVariant?: 'glass' | 'light'
    /**
     * 通栏页：主体挂 `.l-main--flush`（`styles/base.css`），去掉左右与顶部留白。
     *
     * 只给「首屏满幅图 / 整段换底色」的版式用（目前只有首页）：这种页面的留白由页面内
     * 各段的 `.l-section` 自己给，主体再留一层 padding 会把满幅段切成窄条。
     */
    flush?: boolean
  }
}
