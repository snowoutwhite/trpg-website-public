<script setup lang="ts">
/** 账户与通知 · 邮件偏好（v2 `me.html` 的「邮件偏好」块）。 */
import { computed, onMounted, ref } from 'vue'
import LoadState from '../LoadState.vue'
import SwitchRow from './SwitchRow.vue'
import { ApiError } from '../../api/http'
import { errorText } from '../../lib/api-error'
import {
  fetchEmailPreference,
  updateEmailPreference,
  type EmailPreference,
} from '../../api/notifications'

const preference = ref<EmailPreference | null>(null)
const loading = ref(true)
const error = ref('')
const saveError = ref('')
const saved = ref(false)
const saving = ref(false)

onMounted(async () => {
  try {
    preference.value = await fetchEmailPreference()
  } catch (e) {
    error.value = errorText(e, '邮件偏好暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
})

const events = computed(() => preference.value?.available_events ?? [])

/**
 * 保存结果只在下面这一行固定高度的状态栏里显示（v2 上手检查 2026-09-23）：
 * 原先用 `v-if` 插入一整个提示框，每拨一次开关它就先消失再出现，下面所有开关跟着上下跳一次。
 * 状态栏永远占着一行的位置，只换里面的字，版面一个像素都不动。
 */
const statusText = computed(() => {
  if (saveError.value) return saveError.value
  if (saved.value) return '设置已保存。'
  return ''
})
const master = computed({
  get: () => preference.value?.email_enabled === true,
  set: (value: boolean) => void save({ email_enabled: value }),
})

/** 某个事件当前是开是关：没设过就跟随总开关（后端同口径：per_event 缺省 = 跟随）。 */
function isOn(name: string): boolean {
  const per = preference.value?.per_event ?? {}
  return name in per ? per[name] === true : preference.value?.email_enabled === true
}

function setEvent(name: string, value: boolean): void {
  if (!preference.value) return
  void save({ per_event: { ...preference.value.per_event, [name]: value } })
}

async function save(next: Partial<EmailPreference>): Promise<void> {
  if (!preference.value || saving.value) return
  saving.value = true
  saveError.value = ''
  saved.value = false
  // PATCH 响应不带 available_events，把 GET 拿到的清单留着
  const list = preference.value.available_events
  try {
    const data = await updateEmailPreference(next)
    preference.value = { ...data, available_events: list }
    saved.value = true
  } catch (e) {
    saveError.value = (e instanceof ApiError ? e.formMessage() : '') || errorText(e, '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section aria-labelledby="mail-head">
    <div class="head">
      <h2 id="mail-head" class="u-h-card">邮件偏好</h2>
      <span class="u-small">决定哪些事情会发邮件提醒你</span>
    </div>

    <LoadState :loading="loading" :error="error">
      <template v-if="preference">
        <p class="u-small intro">
          本页只控制是否向你的邮箱发送提醒邮件。无论这里如何设置，站内的通知列表都会照常收到每一条消息。
          所有邮件提醒默认关闭；打开总开关后，可以再逐项决定哪些事情需要发邮件。
        </p>

        <SwitchRow
          v-model="master"
          label="接收邮件通知"
          desc="总开关。关闭后，下面的所有分项都不会发送邮件。"
        />

        <SwitchRow
          v-for="row in events"
          :key="row.event"
          :model-value="isOn(row.event)"
          :label="row.label"
          :disabled="!preference.email_enabled"
          @update:model-value="setEvent(row.event, $event)"
        />

        <p v-if="!events.length" class="u-small note">
          暂时无法获取可以逐项设置的事件清单，目前只能使用总开关。
        </p>
        <p v-else class="u-small note">
          没有单独设置过的分项，会与总开关保持一致。你对某一项做过单独设置后，该项以你的设置为准。
        </p>

        <p
          class="u-small status"
          :class="{ 'status--error': saveError }"
          role="status"
          aria-live="polite"
        >
          {{ statusText }}
        </p>
      </template>
    </LoadState>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-bottom: var(--sp-3);
}

.head h2 {
  margin: 0;
}

.intro,
.note {
  margin: 0 0 var(--sp-3);
  line-height: var(--lh-body);
  color: var(--ink-muted);
}

.note {
  margin: var(--sp-3) 0 0;
}

/* 固定占一行：有字没字高度都一样，保存结果出现时不推挤上面的开关 */
.status {
  min-height: 1.6em;
  margin: var(--sp-2) 0 0;
  line-height: var(--lh-body);
  color: var(--ok);
}

.status--error {
  color: var(--danger);
}
</style>
