<script setup lang="ts">
/**
 * 空态（v2 `recruit.html .empty`：虚线框 + 一行标题 + 一段说明 + 按钮行；
 * `cards.html .empty`、`reports.html .empty-note`、`resources.html .res-empty` 是它的简化版）。
 *
 * 与「出错」分开：出错是「没取到」，空态是「确实没有」，两种话术不能混。
 * 空态必须给出口 —— 用 `actions` 插槽放「去找团」「清掉筛选」这类下一步。
 */
withDefaults(
  defineProps<{
    /** 一行标题，例如「这个筛选下没有团」。 */
    title?: string
    /** 一段说明；也可以用默认插槽写更长的内容。 */
    text?: string
    /** 紧凑版：列表内嵌的小空态用它，少一半上下留白。 */
    compact?: boolean
  }>(),
  { title: '', text: '', compact: false },
)
</script>

<template>
  <div class="c-empty" :class="compact ? 'c-empty--compact' : null">
    <h3 v-if="title" class="c-empty__title">{{ title }}</h3>
    <p v-if="text" class="c-empty__text">{{ text }}</p>
    <slot />
    <div v-if="$slots.actions" class="c-empty__actions"><slot name="actions" /></div>
  </div>
</template>

<style scoped>
.c-empty {
  padding: var(--sp-7) var(--sp-5);
  text-align: center;
  background: var(--white);
  border: 1px dashed var(--line-2);
  border-radius: var(--radius);
}

.c-empty--compact {
  padding: var(--sp-5) var(--sp-4);
}

.c-empty__title {
  margin: 0;
  font-size: var(--fs-xl);
  line-height: var(--lh-card);
  color: var(--ink);
}

.c-empty__text {
  margin: var(--sp-2) auto 0;
  max-width: 44ch;
  font-size: var(--fs-md);
  line-height: var(--lh-body);
  color: var(--ink-muted);
}

.c-empty__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--sp-2) var(--sp-4);
  margin-top: var(--sp-4);
}

@media (min-width: 768px) {
  .c-empty {
    padding: var(--sp-9) var(--sp-6);
  }

  .c-empty--compact {
    padding: var(--sp-6) var(--sp-5);
  }
}
</style>
