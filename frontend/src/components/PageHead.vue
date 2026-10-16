<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
withDefaults(
  defineProps<{
    /** 眼标，例如「Recruit · 找团」。 */
    eyebrow?: string
    title: string
    lead?: string
    /** display（默认，clamp 25–38）或 section（clamp 22–30，标题很长的详情页用）。 */
    size?: 'display' | 'section'
  }>(),
  { size: 'display' },
)
</script>

<template>
  <header class="c-page-head u-rise">
    <div class="c-page-head__main">
      <p v-if="eyebrow" class="u-kicker">{{ eyebrow }}</p>
      <h1 :class="size === 'section' ? 'u-h-section' : 'u-h-display'">{{ title }}</h1>
      <p v-if="lead" class="u-lead c-page-head__lead">{{ lead }}</p>
    </div>
    <div v-if="$slots.aside" class="c-page-head__aside"><slot name="aside" /></div>
  </header>
</template>

<style scoped>
.c-page-head {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  margin-bottom: var(--sp-5);
}

.c-page-head__main {
  min-width: 0;
}

.c-page-head__main h1 {
  margin: var(--sp-2) 0 0;
}

.c-page-head__lead {
  margin: var(--sp-3) 0 0;
  max-width: 54ch;
}

.c-page-head__aside {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-4);
}

@media (min-width: 768px) {
  .c-page-head {
    flex-direction: row;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--sp-5) var(--sp-7);
    margin-bottom: var(--sp-6);
  }

  .c-page-head__aside {
    flex: none;
    justify-content: flex-end;
  }
}
</style>
