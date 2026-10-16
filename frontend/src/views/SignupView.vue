<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import AuthShell from './AuthShell.vue'
import PageHead from '../components/PageHead.vue'
import FormField from '../components/FormField.vue'
import CButton from '../components/CButton.vue'
import CNotice from '../components/CNotice.vue'
import { useAuthStore } from '../stores/auth'
import { useSiteStore } from '../stores/site'
import { ApiError } from '../api/http'
// allauth / Django 的内置译文按 code 换成本站文案（邮箱已注册、密码太短、必填…）
import { fieldText, formText } from '../lib/api-error'
import { ruleArtFile } from '../lib/rule-art'

const router = useRouter()
const auth = useAuthStore()
const site = useSiteStore()
const { config } = storeToRefs(site)

/** v2 注册页用 DND 的规则美术。 */
const art = ruleArtFile('dnd')

/** 邀请码字段是否出现，由 GET /api/v1/siteconfig/ 的 invite_code_required 决定。 */
const needInvite = computed(() => config.value.invite_code_required === true)

const nickname = ref('')
const email = ref('')
const password = ref('')
const inviteCode = ref('')
const submitting = ref(false)
const formError = ref('')
const fieldErrors = ref<Record<string, string>>({})

void site.load()

/**
 * 注册失败的顶部横幅，按状态码 / 响应形状分支（缺陷 F1）。
 *
 * 不能写成 `formText(e) || 专用文案`：`extractErrors` 在后端没给错误项时会按状态码兜底
 * 生成一条通用 message，`||` 右边永远走不到。几种 403 / 429 的实际形状：
 * - 注册关闭：allauth `ForbiddenResponse`，JSON 信封 `{status: 403}`，没有 errors；
 * - CSRF 失效：Django 的 CSRF 失败页，HTML 文本，不是 JSON 信封；
 * - 限速：allauth `RateLimitResponse`，JSON 信封 `{status: 429}`，没有 errors。
 * 后端真带了具体错误项（errors 数组 / 本站错误信封）时仍用 `formText` 的译文。
 */
function signupErrorText(e: ApiError): string {
  const payload = e.payload
  const isJson = payload !== null && typeof payload === 'object'
  const p = (isJson ? payload : {}) as Record<string, unknown>
  const hasBackendErrors = Array.isArray(p.errors) || (p.error !== null && typeof p.error === 'object')
  if (e.status === 429) return '注册尝试过于频繁，请稍后再试。'
  if (e.status === 403 && !hasBackendErrors) {
    return isJson ? '本站目前暂停注册。' : '页面已过期，请刷新页面后重新提交。'
  }
  return formText(e)
}

async function onSubmit(): Promise<void> {
  if (submitting.value) return
  submitting.value = true
  formError.value = ''
  fieldErrors.value = {}
  try {
    const ok = await auth.signup({
      nickname: nickname.value.trim(),
      email: email.value.trim(),
      password: password.value,
      invite_code: needInvite.value ? inviteCode.value.trim() : undefined,
    })
    // 站点强制邮箱验证：正常路径是 401 + verify_email 待完成，而不是直接登录
    await router.replace(ok ? { name: 'me' } : { name: 'verify-email' })
  } catch (e) {
    if (e instanceof ApiError) {
      fieldErrors.value = fieldText(e)
      formError.value = signupErrorText(e)
    } else {
      formError.value = '注册失败，请稍后再试。'
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AuthShell
    :art="art"
    kicker="JOIN THE TABLE"
    line="注册账号后，你就可以报名参加站内的团。"
    credit="DUNGEONS &amp; DRAGONS"
  >
    <PageHead
      size="section"
      eyebrow="CREATE ACCOUNT"
      title="注册"
      lead="注册只需要邮箱、昵称和密码。本站不收集手机号，不支持第三方账号登录，也不会向其他任何人展示你的邮箱。"
    />

    <CNotice v-if="formError" tone="danger">{{ formError }}</CNotice>

    <form novalidate @submit.prevent="onSubmit">
      <FormField
        v-model="email"
        label="邮箱"
        type="email"
        inputmode="email"
        autocomplete="email"
        placeholder="you@example.com"
        hint="邮箱用于接收验证邮件、报名相关的通知以及重置密码的邮件。只有你本人和站主能看到你的邮箱。"
        required
        :error="fieldErrors.email"
      />
      <FormField
        v-model="nickname"
        label="昵称"
        autocomplete="nickname"
        :maxlength="24"
        placeholder="站内显示的名字"
        hint="昵称在全站唯一，最多 24 个字。注册后，每 30 天只能修改一次昵称，每次修改都会留下记录。"
        required
        :error="fieldErrors.nickname"
      />
      <FormField
        v-model="password"
        label="密码"
        type="password"
        autocomplete="new-password"
        hint="密码至少需要 8 位。"
        required
        :error="fieldErrors.password"
      />
      <!-- 邀请码：站级开关 SiteConfig.invite_code_required 打开时才出现，也才会被提交 -->
      <FormField
        v-if="needInvite"
        v-model="inviteCode"
        label="邀请码"
        autocomplete="off"
        placeholder="请输入邀请码"
        hint="本站目前要求凭邀请码注册，没有邀请码将无法完成注册。你可以向认识的站内成员或站主索取邀请码。"
        required
        :error="fieldErrors.invite_code"
      />

      <CButton type="submit" block :disabled="submitting">
        {{ submitting ? '提交中…' : '注册' }}
      </CButton>
    </form>

    <p class="u-small auth-tip">
      注册后，系统会向你的邮箱发送一封验证邮件。请点击邮件中的链接完成验证；验证完成之前，你将无法登录。如果没有收到邮件，请先检查垃圾邮件文件夹，也可以在验证页面重新发送。发布团、报名、交卡和评价的规则都写在新人手册中，建议你在报名前阅读一遍：<RouterLink class="c-textlink u-tap" to="/guide">新人手册 →</RouterLink>
    </p>

    <div class="c-foot">
      <span class="u-small">已经有账号了？</span>
      <RouterLink class="c-textlink" to="/auth/login">去登录 →</RouterLink>
    </div>
  </AuthShell>
</template>

<style scoped>
/* v2 `.after-signup`：表单下面的一段小字说明 */
.auth-tip {
  display: block;
  margin: var(--sp-4) 0 0;
  line-height: 1.8;
  color: var(--ink-faint);
}
</style>
