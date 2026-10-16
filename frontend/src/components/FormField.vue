<script setup lang="ts">
/**
 * 输入行（v2 `.field` + `login.html` / `signup.html` 的 `.req` 必填徽标）。
 * 视觉底座是 `styles/base.css` 的全局 `.c-field` / `.c-input`（实线框、44px 触控高、6px 圆角）。
 *
 * v2 改造（差距分析 §2.5）：旧骨架的「虚线下划线 + 朱砂星号」换成
 * **实线框 + 线框徽标**；`no`（表单序号）保留 —— 分支上的放团表单、写战报表单还在用，
 * props 与旧骨架完全一致，现有 view 不用改。
 *
 * 无障碍：label 与 input 用同一个 `useId()` 绑定；hint 与 error 通过 `aria-describedby` 串起来，
 * 出错时再加 `aria-invalid`。必填徽标是可读文字（「必填」），不是只给视力用户的星号。
 */
import { computed, useId } from 'vue'

const props = withDefaults(
  defineProps<{
    label: string
    /** 表单里的序号，如 01。 */
    no?: string
    type?: string
    hint?: string
    error?: string
    placeholder?: string
    autocomplete?: string
    required?: boolean
    inputmode?: 'text' | 'email' | 'numeric' | 'none'
    /** 原生 maxlength（昵称 24 字等），不传则不限。 */
    maxlength?: number
  }>(),
  { type: 'text', required: false },
)

const model = defineModel<string>({ default: '' })
const id = useId()
const describedBy = computed(() => {
  const ids: string[] = []
  if (props.hint) ids.push(id + '-hint')
  if (props.error) ids.push(id + '-err')
  return ids.length ? ids.join(' ') : undefined
})
</script>

<template>
  <div class="c-field">
    <div class="c-field__head">
      <span v-if="no" class="c-field__no">{{ no }}</span>
      <label class="c-field__label" :for="id">{{ label }}</label>
      <span v-if="required" class="c-field__req">必填</span>
    </div>
    <input
      :id="id"
      v-model="model"
      class="c-input"
      :type="type"
      :placeholder="placeholder"
      :autocomplete="autocomplete"
      :inputmode="inputmode"
      :required="required"
      :maxlength="maxlength"
      :aria-invalid="error ? 'true' : undefined"
      :aria-describedby="describedBy"
    />
    <!-- 业务信息 -->
    <slot name="trailing" />
    <p v-if="hint" :id="id + '-hint'" class="c-field__hint">{{ hint }}</p>
    <p v-if="error" :id="id + '-err'" class="c-field__error">{{ error }}</p>
  </div>
</template>

<style scoped>
/* v2 login.html / signup.html 的 .req：线框小徽标，不是星号 */
.c-field__req {
  padding: 1px 5px;
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps);
  line-height: 1.6;
  color: var(--brand-ink);
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
}
</style>
