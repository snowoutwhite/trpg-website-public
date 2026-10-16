<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
withDefaults(
  defineProps<{
    /** brand = 品牌墨绿竖线（默认）；其余三档走语义色。 */
    tone?: 'brand' | 'ok' | 'warn' | 'danger'
    /** 加粗的一行小标题，可不给。 */
    title?: string
    /** 显示右上角的关闭按钮。 */
    dismissible?: boolean
    /** 关闭按钮的无障碍名字。 */
    dismissLabel?: string
  }>(),
  { tone: 'brand', dismissible: false, dismissLabel: '知道了' },
)

defineEmits<{ dismiss: [] }>()
</script>

<template>
  <div
    class="c-note c-notice"
    :class="'c-notice--' + tone"
    :role="tone === 'danger' ? 'alert' : undefined"
  >
    <div class="c-notice__body">
      <p v-if="title" class="c-notice__title">{{ title }}</p>
      <div class="c-notice__text"><slot /></div>
      <div v-if="$slots.actions" class="c-notice__actions"><slot name="actions" /></div>
    </div>
    <button
      v-if="dismissible"
      class="c-notice__close"
      type="button"
      :aria-label="dismissLabel"
      @click="$emit('dismiss')"
    >
      {{ dismissLabel }}
    </button>
  </div>
</template>

<style scoped>
.c-notice {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
}

.c-notice__body {
  flex: 1 1 auto;
  min-width: 0;
}

.c-notice__title {
  margin: 0 0 var(--sp-1);
  font-size: var(--fs-base);
  line-height: var(--lh-card);
  color: var(--ink);
}

.c-notice__text {
  min-width: 0;
}

.c-notice__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2) var(--sp-4);
  margin-top: var(--sp-2);
}

/* 关闭按钮也要满足 40px 触控区 */
.c-notice__close {
  flex: none;
  min-height: 40px;
  padding: 0 var(--sp-2);
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-muted);
  background: none;
  border: 0;
}

.c-notice__close:hover {
  color: var(--brand-ink);
}

/* 品牌色竖线：v2 的默认提示口吻 */
.c-notice--brand {
  color: var(--ink-soft);
  background: var(--brand-wash);
  border-left-color: var(--brand);
}

.c-notice--ok {
  color: var(--ok);
  background: var(--ok-wash);
  border-left-color: var(--ok);
}

.c-notice--warn {
  color: var(--warn);
  background: var(--warn-wash);
  border-left-color: var(--warn);
}

.c-notice--danger {
  color: var(--danger);
  background: var(--danger-wash);
  border-left-color: var(--danger);
}
</style>
