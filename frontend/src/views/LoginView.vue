<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import AuthShell from './AuthShell.vue'
import PasswordForgotView from './PasswordForgotView.vue'
import PageHead from '../components/PageHead.vue'
import FormField from '../components/FormField.vue'
import CButton from '../components/CButton.vue'
import CNotice from '../components/CNotice.vue'
import { useAuthStore } from '../stores/auth'
import { ApiError } from '../api/http'
// allauth 的内置译文（「您提供的电子邮件地址和/或密码不正确。」等）按 code 换成本站文案
import { errorCode, fieldText, formText } from '../lib/api-error'
import { safeNextPath } from '../lib/url-guard'
import { ruleArtFile } from '../lib/rule-art'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

/** v2 登录页用 COC 的规则美术。 */
const art = ruleArtFile('coc')
/** v2 的 `#forgot` 面板：同一张卡，只换右侧内容。 */
const showForgot = computed(() => route.hash === '#forgot')

/** 封禁号用正确的邮箱和密码登录时的提示（封禁理由不对外，与站内其他封禁提示一致）。 */
const BANNED_TEXT = '你的账号已被站主封禁，目前无法登录。如果你认为这是误判，请通过社团内的联系方式与站主沟通。'

const email = ref('')
const password = ref('')
const submitting = ref(false)
const formError = ref('')
const fieldErrors = ref<Record<string, string>>({})

async function onSubmit(): Promise<void> {
  if (submitting.value) return
  submitting.value = true
  formError.value = ''
  fieldErrors.value = {}
  try {
    const ok = await auth.login(email.value.trim(), password.value)
    if (ok) {
      // `?next=` 是 URL 里来的，只认本站绝对路径：
      // 原先的 `startsWith('/')` 放得过 `//evil.example` 与 `/\evil.example`（协议相对地址）。
      await router.replace(safeNextPath(route.query.next, '/me'))
    } else if (auth.pendingEmailVerification) {
      // allauth 以 401 + flows[verify_email].is_pending 表示「账号还没验邮箱」
      await router.replace({ name: 'verify-email' })
    } else {
      formError.value = '邮箱或密码不正确，请重新输入。'
    }
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 409) {
        // 已经登录了，直接回「我的」
        await auth.refresh(true)
        await router.replace({ name: 'me' })
        return
      }
      if (e.status === 403 && errorCode(e) === 'account_banned') {
        formError.value = BANNED_TEXT
        return
      }
      fieldErrors.value = fieldText(e)
      formError.value = formText(e) || (e.status === 429 ? '登录尝试过于频繁，请稍后再试。' : '')
    } else {
      formError.value = '登录失败，请稍后再试。'
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AuthShell
    :art="art"
    kicker="WELCOME BACK"
    line="欢迎回来。登录后即可继续报名参团、提交角色卡和查看你的团。"
    credit="CALL OF CTHULHU"
  >
    <!-- 忘记密码面板：复用 PasswordForgotView 的 embedded 形态 -->
    <PasswordForgotView v-if="showForgot" embedded />

    <template v-else>
      <PageHead
        size="section"
        eyebrow="SIGN IN"
        title="登录"
        lead="请使用注册时填写的邮箱和密码登录。本站只支持邮箱登录，不支持使用其他网站的账号登录，也不会收集你的手机号。"
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
          required
          :error="fieldErrors.email"
        />
        <FormField
          v-model="password"
          label="密码"
          type="password"
          autocomplete="current-password"
          required
          :error="fieldErrors.password"
        />

        <div class="auth-row">
          <!-- 带上 query：`?next=` 在两个面板之间不丢 -->
          <RouterLink class="c-textlink u-tap" :to="{ query: route.query, hash: '#forgot' }">
            忘记密码
          </RouterLink>
        </div>

        <CButton type="submit" block :disabled="submitting">
          {{ submitting ? '登录中…' : '登录' }}
        </CButton>
      </form>

      <p class="u-small auth-tip">
        如果连续多次登录失败，系统会暂时限制登录，请等待几分钟后再试。登录成功后，
        这台设备会在一段时间内保持登录状态，无需每次重新输入。
      </p>

      <div class="c-foot">
        <span class="u-small">还没有账号？</span>
        <RouterLink class="c-textlink" to="/auth/signup">注册新账号 →</RouterLink>
      </div>
    </template>
  </AuthShell>
</template>

<style scoped>
/** 业务界面遵循后端权限与隐私约束。 */
.auth-row {
  display: flex;
  justify-content: flex-end;
  margin-bottom: var(--sp-3);
}

/* v2 `.only-email`：表单下面的一段小字说明 */
.auth-tip {
  display: block;
  margin: var(--sp-4) 0 0;
  line-height: 1.8;
  color: var(--ink-faint);
}
</style>
