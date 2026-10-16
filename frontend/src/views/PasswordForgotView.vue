<script setup lang="ts">
/** 忘记密码：请求一封重置信（v2 `login.html` 的 `#pane-forgot` 面板）。 */
import { ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import AuthShell from './AuthShell.vue'
import PageHead from '../components/PageHead.vue'
import FormField from '../components/FormField.vue'
import CButton from '../components/CButton.vue'
import CNotice from '../components/CNotice.vue'
import { requestPasswordReset } from '../api/auth'

const route = useRoute()
import { ApiError } from '../api/http'
// allauth / Django 的内置译文（邮箱格式、必填…）按 code 换成本站文案
import { fieldText, formText } from '../lib/api-error'
import { ruleArtFile } from '../lib/rule-art'

withDefaults(
  defineProps<{
    /** 嵌在登录页的分栏里时为真：不再套一层美术分栏。 */
    embedded?: boolean
  }>(),
  { embedded: false },
)

/** 独立成页时用登录页同一张美术（它就是登录页的那个面板）。 */
const art = ruleArtFile('coc')

const email = ref('')
const submitting = ref(false)
const sent = ref(false)
const formError = ref('')
const fieldErrors = ref<Record<string, string>>({})

async function onSubmit(): Promise<void> {
  if (submitting.value) return
  submitting.value = true
  formError.value = ''
  fieldErrors.value = {}
  try {
    await requestPasswordReset(email.value.trim())
    sent.value = true
  } catch (e) {
    if (e instanceof ApiError) {
      fieldErrors.value = fieldText(e)
      formError.value = formText(e) || (e.status === 429 ? '发送过于频繁，请稍后再试。' : '')
    } else {
      formError.value = '邮件发送失败，请稍后再试。'
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AuthShell
    :bare="embedded"
    :art="art"
    kicker="RESET"
    line="忘记密码时，可以通过注册邮箱重新设置，你的账号和记录都不会受影响。"
    credit="CALL OF CTHULHU"
  >
    <PageHead
      size="section"
      eyebrow="RESET"
      title="找回密码"
      lead="请填写注册时使用的邮箱，本站会向这个邮箱发送一封包含重置链接的邮件。链接有有效期，过期后可以在本页重新申请。"
    />

    <CNotice v-if="sent" tone="ok">
      如果这个邮箱在本站注册过，重置密码的邮件已经发出。请打开邮件中的链接设置新密码；如果没有收到，请检查垃圾邮件文件夹。
    </CNotice>
    <CNotice v-else-if="formError" tone="danger">{{ formError }}</CNotice>

    <form v-if="!sent" novalidate @submit.prevent="onSubmit">
      <FormField
        v-model="email"
        label="注册邮箱"
        type="email"
        inputmode="email"
        autocomplete="email"
        placeholder="you@example.com"
        hint="无论这个邮箱是否在本站注册过，提交后显示的提示都相同，这是为了防止他人借此查询某个邮箱是否注册了本站账号。"
        required
        :error="fieldErrors.email"
      />
      <CButton type="submit" block :disabled="submitting">
        {{ submitting ? '发送中…' : '发送重置链接' }}
      </CButton>
    </form>

    <div class="c-foot">
      <span class="u-small">想起密码了？</span>
      <RouterLink class="c-textlink" :to="{ path: '/auth/login', query: route.query }">返回登录 →</RouterLink>
    </div>
  </AuthShell>
</template>
