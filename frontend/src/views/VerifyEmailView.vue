<script setup lang="ts">
/** 验证邮箱（v2 没画这一页，套认证五页同一张卡）。 */
import { onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import AuthShell from './AuthShell.vue'
import PageHead from '../components/PageHead.vue'
import CButton from '../components/CButton.vue'
import CNotice from '../components/CNotice.vue'
import BtnLink from '../components/BtnLink.vue'
import { fetchEmailVerificationInfo, resendEmailVerification } from '../api/auth'
import { useAuthStore } from '../stores/auth'
import { ApiError } from '../api/http'
// allauth 的「令牌无效或过期。」等内置译文按 code 换成本站文案
import { formText } from '../lib/api-error'
import { GENERIC_ART } from '../lib/rule-art'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

/** 验证页使用通用桌游素材，不绑定具体规则系统。 */
const art = GENERIC_ART.portrait.file

const verifyKey = String(route.params.key ?? route.query.key ?? '')
const state = ref<'idle' | 'checking' | 'ready' | 'invalid' | 'done' | 'done-need-login'>('idle')
const targetEmail = ref('')
const message = ref('')
const submitting = ref(false)
const resent = ref(false)

onMounted(async () => {
  if (!verifyKey) return
  state.value = 'checking'
  try {
    const envelope = await fetchEmailVerificationInfo(verifyKey)
    if (envelope.status === 200 && envelope.data) {
      targetEmail.value = envelope.data.email ?? ''
      state.value = 'ready'
    } else {
      state.value = 'invalid'
      message.value = '这条验证链接已失效，请重新申请验证邮件。'
    }
  } catch (e) {
    state.value = 'invalid'
    message.value =
      e instanceof ApiError && formText(e)
        ? formText(e)
        : '这条验证链接已失效，请重新申请验证邮件。'
  }
})

async function onVerify(): Promise<void> {
  if (submitting.value) return
  submitting.value = true
  message.value = ''
  try {
    const ok = await auth.verifyEmail(verifyKey)
    if (ok) {
      state.value = 'done'
      setTimeout(() => void router.replace({ name: 'me' }), 900)
    } else {
      // 401：邮箱已验证成功，但站点配置为验证后不自动登录
      state.value = 'done-need-login'
    }
  } catch (e) {
    state.value = 'invalid'
    message.value =
      e instanceof ApiError && formText(e)
        ? formText(e)
        : '邮箱验证失败，请重新申请验证邮件。'
  } finally {
    submitting.value = false
  }
}

async function onResend(): Promise<void> {
  if (submitting.value) return
  submitting.value = true
  message.value = ''
  try {
    await resendEmailVerification()
    resent.value = true
  } catch (e) {
    message.value =
      e instanceof ApiError && e.status === 429
        ? '发送过于频繁，请稍后再试。'
        : '邮件发送失败，请稍后再试。'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AuthShell
    :art="art"
    kicker="VERIFY EMAIL"
    line="完成邮箱验证后，你的账号才能正常使用。"
  >
    <PageHead
      size="section"
      eyebrow="VERIFY EMAIL"
      title="验证邮箱"
      lead="本站要求所有账号验证邮箱。完成验证之前，你将无法登录并使用本站。"
    />

    <!-- 链接里没有校验码：注册后落到这里，提示去收信 -->
    <template v-if="!verifyKey">
      <CNotice tone="warn">
        验证邮件已经发出。打开邮件中的链接即可完成验证；如果没有收到，请先检查垃圾邮件文件夹，也可以点击下方按钮重新发送。
      </CNotice>
      <CNotice v-if="resent" tone="ok">已重新发送一封验证邮件，请查收。</CNotice>
      <CNotice v-if="message" tone="danger">{{ message }}</CNotice>
      <CButton variant="ghost" block :disabled="submitting" @click="onResend">
        {{ submitting ? '发送中…' : '重新发送验证邮件' }}
      </CButton>
    </template>

    <template v-else-if="state === 'checking'">
      <p class="u-muted">正在检查链接是否有效…</p>
    </template>

    <template v-else-if="state === 'ready'">
      <CNotice tone="brand">
        点击下方按钮，即可完成邮箱 <strong>{{ targetEmail }}</strong> 的验证
      </CNotice>
      <CButton block :disabled="submitting" @click="onVerify">
        {{ submitting ? '验证中…' : '确认验证' }}
      </CButton>
    </template>

    <template v-else-if="state === 'done'">
      <CNotice tone="ok">邮箱验证已完成，正在为你登录并打开网站…</CNotice>
    </template>

    <template v-else-if="state === 'done-need-login'">
      <CNotice tone="ok">邮箱验证已完成，现在可以登录了。</CNotice>
      <BtnLink to="/auth/login" block>前往登录</BtnLink>
    </template>

    <template v-else>
      <CNotice tone="danger">{{ message }}</CNotice>
    </template>

    <div class="c-foot">
      <span class="u-small">已经完成验证？</span>
      <RouterLink class="c-textlink" to="/auth/login">返回登录 →</RouterLink>
    </div>
  </AuthShell>
</template>
