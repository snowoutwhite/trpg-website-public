<script setup lang="ts">
/** 开关行（v2 `me.html` 的 `.switch-row` + `.switch`）：左边一行说明，右边一个滑块。 */
withDefaults(
  defineProps<{
    label: string
    /** 第二行小字说明。 */
    desc?: string
    /** 正在保存或总开关关着时置灰。 */
    disabled?: boolean
  }>(),
  { desc: '', disabled: false },
)

const model = defineModel<boolean>({ required: true })
</script>

<template>
  <div class="sw-row">
    <span class="sw-row__text">
      <span class="sw-row__label">{{ label }}</span>
      <span v-if="desc" class="sw-row__desc u-small">{{ desc }}</span>
    </span>
    <button
      class="sw"
      type="button"
      :aria-pressed="model ? 'true' : 'false'"
      :aria-label="label"
      :disabled="disabled"
      @click="model = !model"
    >
      <span class="sw__track" aria-hidden="true"></span>
    </button>
  </div>
</template>

<style scoped>
.sw-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  min-height: 44px;
  padding: var(--sp-3) 0;
  border-bottom: 1px solid var(--line);
  max-width: 640px;
}

.sw-row__text {
  min-width: 0;
}

.sw-row__label {
  display: block;
  font-size: var(--fs-base);
  line-height: var(--lh-body);
}

.sw-row__desc {
  display: block;
  margin-top: 2px;
  line-height: var(--lh-body);
  color: var(--ink-muted);
}

/** 所以按钮本身撑到 44×56，轨道画在里面的 `.sw__track` 上。 */
.sw {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: flex-end;
  width: 56px;
  height: 44px;
  padding: 0;
  background: none;
  border: 0;
  cursor: pointer;
}

.sw__track {
  position: relative;
  width: 44px;
  height: 26px;
  background: var(--white);
  border: 1px solid var(--line-2);
  border-radius: var(--radius-pill);
  transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease);
}

.sw__track::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 20px;
  height: 20px;
  background: var(--line-2);
  border-radius: 50%;
  transition: left var(--dur) var(--ease), background var(--dur) var(--ease);
}

.sw[aria-pressed='true'] .sw__track {
  background: var(--brand);
  border-color: var(--brand);
}

.sw[aria-pressed='true'] .sw__track::after {
  left: 20px;
  background: var(--on-brand);
}

.sw:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
