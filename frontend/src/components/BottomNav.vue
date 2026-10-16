<script setup lang="ts">
/** 手机底部主导航（五格：首页 / 找团 / 卡池 / 战报 / 我），≥768px 隐藏。 */
import { RouterLink } from 'vue-router'
import AppIcon from './AppIcon.vue'
import { BOTTOM_NAV } from './nav-links'
</script>

<template>
  <nav class="btm c-bottom-nav" aria-label="主导航">
    <RouterLink
      v-for="link in BOTTOM_NAV"
      :key="link.to"
      :to="link.to"
      class="btm__item"
      :class="link.to === '/' ? 'btm__item--home' : null"
    >
      <AppIcon :name="link.icon" :size="20" />
      <span class="btm__label">{{ link.label }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.btm {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 30;
  display: flex;
  padding-bottom: var(--safe-bottom);
  color: var(--ink-muted);
  background: linear-gradient(200deg, var(--glass-light-1), var(--glass-light-2));
  border-top: 1px solid var(--line);
  box-shadow: var(--glass-shadow-light);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
}

@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .btm {
    background: var(--glass-light-solid);
  }
}

.btm__item {
  flex: 1 1 0;
  min-width: 0;
  min-height: var(--bottom-nav-h);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: inherit;
  text-decoration: none;
  border-top: 2px solid transparent;
  transition: color var(--dur) var(--ease), border-color var(--dur) var(--ease);
}

/* 首页那格用 exact 判断：`/` 是所有路由的前缀，router-link-active 会在每一页都命中 */
.btm__item.router-link-active:not(.btm__item--home),
.btm__item--home.router-link-exact-active {
  color: var(--brand);
  border-top-color: var(--brand);
}

.btm__label {
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-wide);
  line-height: 1;
}

@media (min-width: 768px) {
  .btm {
    display: none;
  }
}
</style>
