<script setup lang="ts">
/** 按钮（v2 `.btn` / `.btn.ghost` / `.btn.light` / `.btn.block`）。 */
withDefaults(
  defineProps<{
    /** primary 实底 / ghost 线框 / light 压深色图 / danger 破坏性 / text 文字型。 */
    variant?: 'primary' | 'ghost' | 'light' | 'danger' | 'text'
    /** 撑满一行（表单提交键、手机上的主按钮）。 */
    block?: boolean
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
  }>(),
  { variant: 'primary', block: false, type: 'button', disabled: false },
)
</script>

<template>
  <button
    class="c-btn"
    :class="[variant === 'primary' ? null : 'c-btn--' + variant, block ? 'c-btn--block' : null]"
    :type="type"
    :disabled="disabled"
  >
    <slot />
  </button>
</template>
