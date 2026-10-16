<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
withDefaults(
  defineProps<{
    /** 是否选中。 */
    active?: boolean
    /** 右侧计数，undefined 表示不显示。0 会正常显示（「这个筛选下确实是 0 条」是有用信息）。 */
    count?: number
    disabled?: boolean
  }>(),
  { active: false, disabled: false },
)
</script>

<template>
  <button
    class="c-chip"
    type="button"
    :aria-pressed="active ? 'true' : 'false'"
    :disabled="disabled"
  >
    <slot />
    <span v-if="count !== undefined" class="c-chip__count">{{ count }}</span>
  </button>
</template>

<style scoped>
.c-chip__count {
  margin-left: var(--sp-2);
  font-size: var(--fs-2xs);
  letter-spacing: 0;
  opacity: 0.75;
}
</style>
