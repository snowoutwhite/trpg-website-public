<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
withDefaults(
  defineProps<{
    /** 眼标，10px 大字距大写。 */
    kicker?: string
    title: string
    /** 右栏导语。 */
    lead?: string
    /** 标题字号档：section（默认，clamp 22–30）或 display（clamp 25–38）。 */
    size?: 'section' | 'display'
    /** 标题层级，默认 h2（页内分区）。 */
    level?: 'h2' | 'h3'
  }>(),
  { kicker: '', lead: '', size: 'section', level: 'h2' },
)
</script>

<template>
  <div class="c-section-head">
    <div class="c-section-head__main">
      <p v-if="kicker" class="u-kicker">{{ kicker }}</p>
      <component
        :is="level"
        class="c-section-head__title"
        :class="size === 'display' ? 'u-h-display' : 'u-h-section'"
      >
        {{ title }}
      </component>
    </div>
    <div v-if="lead || $slots.aside" class="c-section-head__aside">
      <p v-if="lead" class="u-lead c-section-head__lead">{{ lead }}</p>
      <slot name="aside" />
    </div>
  </div>
</template>

<style scoped>
.c-section-head {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  margin-bottom: var(--sp-5);
}

.c-section-head__main {
  min-width: 0;
}

.c-section-head__title {
  margin: var(--sp-3) 0 0;
}

.c-section-head__main .u-kicker + .c-section-head__title {
  margin-top: var(--sp-2);
}

.c-section-head__lead {
  margin: 0;
}

@media (min-width: 768px) {
  .c-section-head {
    flex-direction: row;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--sp-5);
    margin-bottom: var(--sp-6);
  }

  .c-section-head__aside {
    flex: 0 1 380px;
    min-width: 0;
  }
}
</style>
