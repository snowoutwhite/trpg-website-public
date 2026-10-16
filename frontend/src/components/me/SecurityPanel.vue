<script setup lang="ts">
/** 账户与通知 · 登录方式（v2 `me.html`「账户」块的邮箱 + 改密两段）。 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'
import CButton from '../CButton.vue'
import CNotice from '../CNotice.vue'
import CPill from '../CPill.vue'
import FormField from '../FormField.vue'
import {
  addEmailAddress,
  changePassword,
  fetchEmailAddresses,
  removeEmailAddress,
  resendEmailAddressVerification,
  type AllauthEmail,
} from '../../api/auth'
import { ApiError } from '../../api/http'
// formText / fieldText：allauth 的「无效密码。」「此电子邮件地址已关联到这个账号。」等
// 内置译文按 code 换成本站文案（终版表一·登录/注册/邮箱与密码）
import { errorText, fieldText, formText } from '../../lib/api-error'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const { user } = storeToRefs(auth)

// —— 改密 ——
const current = ref('')
const next1 = ref('')
const next2 = ref('')
const showPassword = ref(false)
const pwBusy = ref(false)
const pwError = ref('')
const pwFieldErrors = ref<Record<string, string>>({})
const pwOk = ref('')

const pwType = computed(() => (showPassword.value ? 'text' : 'password'))

async function onChangePassword(): Promise<void> {
  if (pwBusy.value) return
  pwError.value = ''
  pwOk.value = ''
  pwFieldErrors.value = {}
  if (!current.value || !next1.value) {
    pwError.value = '请同时填写当前密码与新密码。'
    return
  }
  if (next1.value !== next2.value) {
    pwFieldErrors.value = { new_password2: '两次输入的新密码不一致，请重新输入。' }
    return
  }
  pwBusy.value = true
  try {
    const envelope = await changePassword(current.value, next1.value)
    if (envelope.status && envelope.status >= 400) {
      pwError.value = '当前密码不正确，请重新输入。'
      return
    }
    pwOk.value = '密码已修改。你在其他设备上的登录状态可能会失效，届时需要用新密码重新登录。'
    current.value = ''
    next1.value = ''
    next2.value = ''
  } catch (e) {
    if (e instanceof ApiError) {
      pwFieldErrors.value = fieldText(e)
      pwError.value = formText(e)
    }
    if (!pwError.value && !Object.keys(pwFieldErrors.value).length) {
      pwError.value = errorText(e, '密码修改失败，请稍后再试。')
    }
  } finally {
    pwBusy.value = false
  }
}

// —— 改邮箱 ——
const addresses = ref<AllauthEmail[]>([])
const newEmail = ref('')
const mailBusy = ref(false)
const mailError = ref('')
const mailOk = ref('')
const mailLoaded = ref(false)

/** 主地址 = 当前登录邮箱。 */
const primary = computed(() => addresses.value.find((a) => a.primary) ?? null)
/** 正在验证中的新地址（非主、未验证）。允许最多一个（后端 MAX 2）。 */
const pendingEmail = computed(() => addresses.value.find((a) => !a.primary && !a.verified) ?? null)

async function loadAddresses(): Promise<void> {
  try {
    const envelope = await fetchEmailAddresses()
    addresses.value = envelope.data ?? []
    mailLoaded.value = true
  } catch {
    // 读不到就退回「只显示 /accounts/me/ 给的那个邮箱」，不阻断整块
    mailLoaded.value = false
  }
}

onMounted(loadAddresses)

async function run(fn: () => Promise<unknown>, okText: string, fallback: string): Promise<void> {
  if (mailBusy.value) return
  mailBusy.value = true
  mailError.value = ''
  mailOk.value = ''
  try {
    await fn()
    mailOk.value = okText
    await loadAddresses()
  } catch (e) {
    mailError.value =
      (e instanceof ApiError ? formText(e) : '') || errorText(e, fallback)
    if (e instanceof ApiError && !mailError.value) {
      mailError.value = Object.values(fieldText(e))[0] ?? fallback
    }
  } finally {
    mailBusy.value = false
  }
}

function onAddEmail(): void {
  const value = newEmail.value.trim()
  if (!value) {
    mailError.value = '请先填写新邮箱。'
    return
  }
  void run(
    async () => {
      await addEmailAddress(value)
      newEmail.value = ''
    },
    '验证邮件已发送到新邮箱。请点击邮件中的链接完成验证，验证后新邮箱才会生效；在此之前，请继续使用原来的邮箱登录。',
    '新邮箱添加失败，请稍后再试。',
  )
}

function onResend(email: string): void {
  void run(
    () => resendEmailAddressVerification(email),
    '验证邮件已重新发送，请注意查收。如果收件箱中没有，请检查垃圾邮件文件夹。',
    '验证邮件发送失败，请稍后再试。',
  )
}

function onDrop(email: string): void {
  void run(() => removeEmailAddress(email), '已取消本次邮箱更换，你的登录邮箱保持不变。', '取消更换失败，请稍后再试。')
}
</script>

<template>
  <section aria-labelledby="security-head">
    <div class="head">
      <h2 id="security-head" class="u-h-card">登录方式</h2>
      <span class="u-small">邮箱与密码</span>
    </div>

    <!-- —— 邮箱 —— -->
    <div class="block">
      <h3 class="u-kicker block__title">登录邮箱</h3>

      <CNotice v-if="mailError" tone="danger">{{ mailError }}</CNotice>
      <CNotice v-else-if="mailOk" tone="ok">{{ mailOk }}</CNotice>

      <p class="line">
        <strong class="line__value">{{ primary?.email || user?.email || '—' }}</strong>
        <CPill v-if="primary ? primary.verified : user?.email_verified" tone="ok">已验证</CPill>
        <CPill v-else tone="warn">待验证</CPill>
      </p>
      <p class="u-small note">
        邮箱用于登录，也是你忘记密码时找回密码的唯一方式。其他成员看不到你的邮箱，你的个人空间和评价中都不会显示邮箱。
      </p>

      <div v-if="pendingEmail" class="pending">
        <p class="line">
          <span class="u-kicker">正在更换为</span>
          <strong class="line__value">{{ pendingEmail.email }}</strong>
          <CPill tone="wait">等待验证</CPill>
        </p>
        <div class="c-actions">
          <CButton variant="ghost" :disabled="mailBusy" @click="onResend(pendingEmail.email)">重新发送验证邮件</CButton>
          <CButton variant="text" :disabled="mailBusy" @click="onDrop(pendingEmail.email)">取消本次更换</CButton>
        </div>
      </div>

      <form v-else-if="mailLoaded" class="form" novalidate @submit.prevent="onAddEmail">
        <FormField
          v-model="newEmail"
          label="换成新的邮箱"
          type="email"
          autocomplete="email"
          inputmode="email"
          hint="提交后，系统会向新邮箱发送一封验证邮件。你点击邮件中的验证链接之后，新邮箱才会成为你的登录邮箱；在此之前，请继续使用原来的邮箱登录。"
        />
        <div class="c-actions">
          <CButton type="submit" variant="ghost" :disabled="mailBusy">
            {{ mailBusy ? '提交中…' : '向新邮箱发送验证邮件' }}
          </CButton>
        </div>
      </form>

      <p v-else class="u-small note">邮箱信息暂时无法读取，请刷新页面后重试。</p>
    </div>

    <!-- —— 改密 —— -->
    <div class="block">
      <h3 class="u-kicker block__title">修改密码</h3>

      <CNotice v-if="pwError" tone="danger">{{ pwError }}</CNotice>
      <CNotice v-else-if="pwOk" tone="ok">{{ pwOk }}</CNotice>

      <form class="form" novalidate @submit.prevent="onChangePassword">
        <FormField
          v-model="current"
          label="当前密码"
          :type="pwType"
          autocomplete="current-password"
          required
          :error="pwFieldErrors.current_password"
        >
          <template #trailing>
            <button class="peek" type="button" @click="showPassword = !showPassword">
              {{ showPassword ? '隐藏密码' : '显示密码' }}
            </button>
          </template>
        </FormField>

        <FormField
          v-model="next1"
          label="新密码"
          :type="pwType"
          autocomplete="new-password"
          required
          hint="密码至少 8 位。本站只要求密码长度，不强制要求包含大小写字母或符号。"
          :error="pwFieldErrors.new_password"
        />

        <FormField
          v-model="next2"
          label="再次输入新密码"
          :type="pwType"
          autocomplete="new-password"
          required
          :error="pwFieldErrors.new_password2"
        />

        <div class="c-actions">
          <CButton type="submit" :disabled="pwBusy">
            {{ pwBusy ? '提交中…' : '修改密码' }}
          </CButton>
          <RouterLink class="c-textlink" to="/auth/password/forgot">忘记当前密码 →</RouterLink>
        </div>
      </form>
    </div>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-bottom: var(--sp-4);
}

.head h2 {
  margin: 0;
}

.block {
  max-width: 560px;
  margin-bottom: var(--sp-7);
}

.block__title {
  margin: 0 0 var(--sp-3);
  color: var(--ink-soft);
}

.line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
}

.line__value {
  font-size: var(--fs-base);
  font-weight: 400;
  overflow-wrap: anywhere;
}

.note {
  margin: var(--sp-2) 0 var(--sp-4);
  line-height: var(--lh-body);
  color: var(--ink-muted);
}

.pending {
  padding: var(--sp-4);
  background: var(--bg-2);
  border-left: 2px solid var(--line-2);
  border-radius: 0 var(--radius) var(--radius) 0;
}

.peek {
  justify-self: end;
  min-height: 40px;
  padding: 0;
  font: inherit;
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-wide);
  color: var(--brand-ink);
  background: none;
  border: 0;
  cursor: pointer;
}

.peek:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}
</style>
