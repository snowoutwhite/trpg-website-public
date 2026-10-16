<script setup lang="ts">
/** 重置密码（v2 没画这一页，套认证五页同一张卡）。 */
import { onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useRoute } from 'vue-router'
import AuthShell from './AuthShell.vue'
import PageHead from '../components/PageHead.vue'
import FormField from '../components/FormField.vue'
import CButton from '../components/CButton.vue'
import CNotice from '../components/CNotice.vue'
import BtnLink from '../components/BtnLink.vue'
import { fetchPasswordResetInfo } from '../api/auth'
import { useAuthStore } from '../stores/auth'
import { ApiError } from '../api/http'
// allauth 的「您重置密码的token是无效的。」等内置译文按 code 换成本站文案
import { fieldText, formText } from '../lib/api-error'
import { GENERIC_ART } from '../lib/rule-art'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

/** v2 没画本页；用中性素材，不绑某个规则系统。 */
const art = GENERIC_ART.overview.file

const resetKey = String(route.params.key ?? route.query.key ?? '')
const state = ref<'checking' | 'ready' | 'invalid' | 'done-need-login'>('checking')
const password = ref('')
const submitting = ref(false)
const formError = ref('')
const fieldErrors = ref<Record<string, string>>({})

onMounted(async () => {
  if (!resetKey) {
    state.value = 'invalid'
    formError.value = '这条链接不完整，请通过邮件中的链接进入。'
    return
  }
  try {
    const envelope = await fetchPasswordResetInfo(resetKey)
    state.value = envelope.status === 200 ? 'ready' : 'invalid'
    if (state.value === 'invalid') formError.value = '这条重置链接已失效，请重新申请。'
  } catch (e) {
    state.value = 'invalid'
    formError.value =
      e instanceof ApiError && formText(e)
        ? formText(e)
        : '这条重置链接已失效，请重新申请。'
  }
})

async function onSubmit(): Promise<void> {
  if (submitting.value) return
  submitting.value = true
  formError.value = ''
  fieldErrors.value = {}
  try {
    const ok = await auth.resetPassword(resetKey, password.value)
    if (ok) {
      await router.replace({ name: 'me' })
    } else {
      // 401：密码已改好，但站点配置为重置后不自动登录
      state.value = 'done-need-login'
    }
  } catch (e) {
    if (e instanceof ApiError) {
      fieldErrors.value = fieldText(e)
      formError.value = formText(e)
      if (e.status === 409) {
        state.value = 'invalid'
        formError.value = '这条重置链接已失效，请重新申请。'
      }
    } else {
      formError.value = '密码修改失败，请稍后再试。'
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AuthShell :art="art" kicker="NEW PASSWORD" line="设置新密码后，你的账号和所有记录都会保持不变。">
    <PageHead
      size="section"
      eyebrow="NEW PASSWORD"
      title="设置新密码"
      lead="这条链接只能使用一次。设置新密码后，旧密码会立即失效。"
    />

    <template v-if="state === 'checking'">
      <p class="u-muted">正在检查链接是否有效…</p>
    </template>

    <template v-else-if="state === 'ready'">
      <CNotice v-if="formError" tone="danger">{{ formError }}</CNotice>
      <form novalidate @submit.prevent="onSubmit">
        <FormField
          v-model="password"
          label="新密码"
          type="password"
          autocomplete="new-password"
          hint="密码至少 8 位。设置成功后，旧密码会立即失效。"
          required
          :error="fieldErrors.password"
        />
        <CButton type="submit" block :disabled="submitting">
          {{ submitting ? '提交中…' : '设置新密码' }}
        </CButton>
      </form>
    </template>

    <template v-else-if="state === 'done-need-login'">
      <CNotice tone="ok">新密码已经生效，请使用新密码登录。</CNotice>
      <BtnLink to="/auth/login" block>前往登录</BtnLink>
    </template>

    <template v-else>
      <CNotice tone="danger">{{ formError }}</CNotice>
      <BtnLink to="/auth/password/forgot" variant="ghost" block>重新申请重置密码邮件</BtnLink>
    </template>

    <div class="c-foot">
      <RouterLink class="c-textlink" to="/auth/login">返回登录</RouterLink>
    </div>
  </AuthShell>
</template>
