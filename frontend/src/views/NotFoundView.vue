<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import BlurStage from '../components/BlurStage.vue'
import BtnLink from '../components/BtnLink.vue'
</script>

<template>
  <BlurStage as="section" class="nf u-rise" :foreground="false" alt="">
    <div class="nf__inner">
      <p class="u-kicker nf__kicker">404</p>
      <h1 class="u-h-display nf__title">找不到这个页面</h1>
      <p class="nf__lead">你访问的页面不存在。可能是链接已经失效，或者网址输入有误。请返回首页重新查找。</p>
      <BtnLink to="/" variant="light">返回首页</BtnLink>
    </div>
  </BlurStage>
</template>

<style scoped>
.nf {
  border-radius: var(--radius-lg);
}

/** 原来 `max-width: 44ch` 加在这一层，`ch` 是按 14px 正文算的（≈308px）， */
.nf__inner {
  max-width: 560px;
  padding: var(--sp-8) var(--sp-5);
}

@media (min-width: 768px) {
  .nf__inner {
    padding: var(--sp-9) var(--sp-7);
  }
}

.nf__kicker {
  margin: 0;
  color: var(--on-dark-kicker);
  text-shadow: var(--text-shadow-dark);
}

.nf__title {
  margin: var(--sp-2) 0 var(--sp-3);
  color: var(--on-dark);
  text-shadow: var(--hero-text-shadow);
}

.nf__lead {
  margin: 0 0 var(--sp-5);
  max-width: 44ch;
  font-size: var(--fs-md);
  line-height: var(--lh-read);
  color: var(--on-dark-2);
  text-shadow: var(--text-shadow-dark);
}
</style>
