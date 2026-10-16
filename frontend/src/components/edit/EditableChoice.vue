<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
const props = withDefaults(
  defineProps<{
    value: string
    /** 说明这是哪一格，直接当 `aria-label`。 */
    label: string
    options: { value: string; text: string }[]
    tone?: 'light' | 'dark'
    error?: string
  }>(),
  { tone: 'light', error: '' },
)

const emit = defineEmits<{ 'update:value': [string] }>()

function onChange(event: Event): void {
  emit('update:value', (event.target as HTMLSelectElement).value)
}
</script>

<template>
  <label class="ec" :class="'ec--' + tone">
    <span class="ec__label">{{ label }}</span>
    <select
      class="ec__box"
      data-edit
      :value="value"
      :aria-label="label"
      :aria-invalid="props.error ? 'true' : undefined"
      @change="onChange"
    >
      <option v-for="option in options" :key="option.value" :value="option.value">
        {{ option.text }}
      </option>
    </select>
    <span v-if="props.error" class="ec__err">{{ props.error }}</span>
  </label>
</template>

<style scoped>
.ec {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ec__label,
.ec__err {
  font-family: var(--font-sans);
  font-size: var(--fs-2xs);
  font-weight: 400;
  letter-spacing: var(--ls-caps-sm);
  line-height: 1.4;
  text-shadow: none;
}

.ec--light .ec__label {
  color: var(--ink-muted);
}

.ec--dark .ec__label {
  color: var(--on-dark-2);
}

.ec__box {
  align-self: flex-start;
  min-width: 10em;
  min-height: 32px; /* 弹层里的小选择框，随原地编辑一并收紧（2026-09-23） */
  padding: 2px var(--sp-2);
  font-family: var(--font-sans);
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps-sm);
  border-radius: var(--radius);
}

.ec--light .ec__box {
  color: var(--ink);
  background: var(--glass-light-1);
  border: 1px dashed var(--brand-ink);
}

.ec--dark .ec__box {
  color: var(--on-dark);
  background: var(--scrim-3);
  border: 1px dashed var(--on-dark);
  text-shadow: none;
}

.ec__box:focus-visible {
  outline: 2px solid var(--brand-ink);
  outline-offset: 1px;
  border-style: solid;
}

.ec--dark .ec__box:focus-visible {
  outline-color: var(--on-dark);
}

.ec__err {
  color: var(--danger);
}

.ec--dark .ec__err {
  padding: 1px var(--sp-2);
  color: var(--on-dark);
  background: var(--danger);
  border-radius: var(--radius);
}
</style>
