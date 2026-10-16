<script setup lang="ts">
/**
 * 账户与通知 · 身份与账号（v2 `me.html` 的昵称 / GM 身份 / 注销三块 + 头像）。
 * 全部走本站自有接口 `apps/accounts`：
 *   昵称 `POST /accounts/me/nickname/`（30 天一次，太频繁回 `nickname_change_too_soon`）
 *   头像 `POST/DELETE /accounts/me/avatar/`（后端按魔数校验、缩到 256px 转 WebP）
 *   GM   `GET/POST /accounts/me/gm-application/`
 *   注销 `POST /accounts/me/deactivate/`（匿名化保留，不物理删除；后端顺带登出）
 *
 * 注销是不可逆动作，做成**两步确认**：先点开说明，再点第二个按钮才真发请求。
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import CButton from '../CButton.vue'
import CNotice from '../CNotice.vue'
import CPill from '../CPill.vue'
import FormField from '../FormField.vue'
import {
  applyForGM,
  changeNickname,
  checkAvatarFile,
  clearAvatar,
  deactivateAccount,
  fetchGMApplication,
  uploadAvatar,
  type GMApplication,
} from '../../api/accounts'
import { errorText } from '../../lib/api-error'
import { useAuthStore } from '../../stores/auth'
import { useSiteStore } from '../../stores/site'

const router = useRouter()
const auth = useAuthStore()
const site = useSiteStore()
const { user, isGm } = storeToRefs(auth)
const { config } = storeToRefs(site)

// —— 昵称 ——
const nickname = ref('')
const nickError = ref('')
const nickOk = ref('')
const nickBusy = ref(false)

// —— 头像 ——
const avatarError = ref('')
const avatarOk = ref('')
const avatarBusy = ref(false)

// —— GM 申请 ——
const application = ref<GMApplication | null>(null)
const reason = ref('')
const gmError = ref('')
const gmOk = ref('')
const gmBusy = ref(false)

// —— 注销 ——
const confirmStage = ref(0)
const deactivateError = ref('')
const deactivating = ref(false)

onMounted(async () => {
  await site.load()
  nickname.value = user.value?.nickname ?? ''
  if (isGm.value) return
  try {
    application.value = (await fetchGMApplication()).application
  } catch {
    application.value = null
  }
})

/** 下次可改昵称的时间；已经可以改了就返回空串。 */
const nextNicknameChange = computed(() => {
  const at = user.value?.nickname_change_available_at
  if (!at) return ''
  const time = new Date(at)
  if (time.getTime() <= Date.now()) return ''
  return time.toLocaleString('zh-CN', { hour12: false })
})

const applicationStatus = computed(() => {
  const status = application.value?.status
  if (status === 'pending') return '审核中'
  if (status === 'approved') return '已通过'
  if (status === 'rejected') return '未通过'
  return ''
})

async function onSaveNickname(): Promise<void> {
  if (nickBusy.value) return
  nickError.value = ''
  nickOk.value = ''
  const value = nickname.value.trim()
  if (!value) {
    nickError.value = '昵称不能为空，请填写。'
    return
  }
  nickBusy.value = true
  try {
    await changeNickname(value)
    await auth.refresh(true)
    nickname.value = user.value?.nickname ?? value
    nickOk.value = '昵称已更新。30 天之后你才能再次修改昵称。'
  } catch (e) {
    nickError.value = errorText(e, '昵称修改失败，请稍后再试。')
  } finally {
    nickBusy.value = false
  }
}

async function onPickAvatar(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  avatarError.value = ''
  avatarOk.value = ''
  if (!file) return
  const problem = checkAvatarFile(file)
  if (problem) {
    avatarError.value = problem
    input.value = ''
    return
  }
  avatarBusy.value = true
  try {
    await uploadAvatar(file)
    await auth.refresh(true)
    avatarOk.value = '头像已更新。系统已自动把图片缩小到合适的尺寸。'
  } catch (e) {
    avatarError.value = errorText(e, '头像上传失败，请稍后再试。')
  } finally {
    avatarBusy.value = false
    input.value = ''
  }
}

async function onClearAvatar(): Promise<void> {
  if (avatarBusy.value) return
  avatarBusy.value = true
  avatarError.value = ''
  avatarOk.value = ''
  try {
    await clearAvatar()
    await auth.refresh(true)
    avatarOk.value = '头像已清除。现在会用你昵称的第一个字代替头像显示。'
  } catch (e) {
    avatarError.value = errorText(e, '头像清除失败，请稍后再试。')
  } finally {
    avatarBusy.value = false
  }
}

async function onApplyGM(): Promise<void> {
  if (gmBusy.value) return
  gmError.value = ''
  gmOk.value = ''
  if (!reason.value.trim()) {
    gmError.value = '请填写申请理由，供站主审核参考。'
    return
  }
  gmBusy.value = true
  try {
    application.value = await applyForGM(reason.value.trim())
    reason.value = ''
    gmOk.value = '申请已提交，正在等待站主审核。审核结果会通过站内通知告诉你。'
  } catch (e) {
    gmError.value = errorText(e, '申请提交失败，请稍后再试。')
  } finally {
    gmBusy.value = false
  }
}

async function onDeactivate(): Promise<void> {
  if (deactivating.value) return
  deactivating.value = true
  deactivateError.value = ''
  try {
    await deactivateAccount()
    await auth.logout()
    await router.replace({ name: 'home' })
  } catch (e) {
    deactivateError.value = errorText(e, '账号注销失败，请稍后再试。')
  } finally {
    deactivating.value = false
  }
}
</script>

<template>
  <section aria-labelledby="identity-head">
    <div class="head">
      <h2 id="identity-head" class="u-h-card">身份与账号</h2>
      <span class="u-small">昵称、头像、GM 身份、注销</span>
    </div>

    <!-- —— 昵称 —— -->
    <div class="block">
      <h3 class="u-kicker block__title">昵称</h3>
      <CNotice v-if="nickError" tone="danger">{{ nickError }}</CNotice>
      <CNotice v-else-if="nickOk" tone="ok">{{ nickOk }}</CNotice>
      <CNotice v-else-if="nextNicknameChange" tone="warn">
        昵称每 30 天只能修改一次。你下一次可以修改昵称的时间是：{{ nextNicknameChange }}
      </CNotice>

      <form novalidate @submit.prevent="onSaveNickname">
        <FormField
          v-model="nickname"
          label="站内昵称"
          required
          :maxlength="24"
          hint="昵称在全站唯一，最长 24 个字，每 30 天只能修改一次。其他成员只能看到你的昵称，看不到你的邮箱。"
        />
        <div class="c-actions">
          <CButton type="submit" :disabled="nickBusy">
            {{ nickBusy ? '保存中…' : '保存昵称' }}
          </CButton>
        </div>
      </form>
    </div>

    <!-- —— 头像 —— -->
    <div class="block">
      <h3 class="u-kicker block__title">头像</h3>
      <CNotice v-if="avatarError" tone="danger">{{ avatarError }}</CNotice>
      <CNotice v-else-if="avatarOk" tone="ok">{{ avatarOk }}</CNotice>

      <div id="avatar-row" class="avatar-row">
        <img v-if="user?.avatar" class="avatar" :src="user.avatar" alt="" />
        <span v-else class="avatar avatar--blank" aria-hidden="true">
          {{ (user?.nickname ?? '').slice(0, 1) || '·' }}
        </span>
        <div class="avatar-row__actions">
          <label class="c-btn c-btn--ghost file">
            {{ avatarBusy ? '处理中…' : '更换头像' }}
            <input
              class="file__input"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              :disabled="avatarBusy"
              @change="onPickAvatar"
            />
          </label>
          <CButton v-if="user?.avatar" variant="text" :disabled="avatarBusy" @click="onClearAvatar">
            清除头像
          </CButton>
        </div>
      </div>
      <p class="u-small note">支持 JPG、PNG 等常见格式的图片，文件大小不超过 2 MB。上传后，系统会自动把图片缩小到合适的尺寸。</p>
    </div>

    <!-- —— GM 身份 —— -->
    <div class="block">
      <h3 class="u-kicker block__title">GM 身份</h3>

      <CNotice v-if="isGm" title="你已经是 GM">
        你可以发布新团，并管理自己所主持的团的报名和相册。拥有 GM 身份不会影响你的玩家身份，你仍然可以作为玩家报名其他人主持的团。
        <template #actions>
          <RouterLink class="c-textlink" to="/games/new">放一个新团 →</RouterLink>
        </template>
      </CNotice>

      <template v-else>
        <CNotice v-if="gmError" tone="danger">{{ gmError }}</CNotice>
        <CNotice v-else-if="gmOk" tone="ok">{{ gmOk }}</CNotice>

        <p class="line">
          <span class="u-small">
            你作为玩家参加的团累计达到 {{ config.gm_auto_promote_threshold }} 次后，系统会自动授予你 GM 身份，无需申请。如果你想在此之前开团，请在下方填写申请理由并提交，由站主审批。
          </span>
        </p>

        <p v-if="application" class="line">
          <CPill :tone="application.status === 'approved' ? 'ok' : application.status === 'rejected' ? 'off' : 'wait'">
            申请{{ applicationStatus }}
          </CPill>
          <span v-if="application.review_note" class="u-small">站主备注：{{ application.review_note }}</span>
        </p>

        <form v-if="application?.status !== 'pending'" class="gm-form" novalidate @submit.prevent="onApplyGM">
          <div class="c-field">
            <div class="c-field__head">
              <label class="c-field__label" for="gm-reason">申请理由</label>
            </div>
            <textarea
              id="gm-reason"
              v-model="reason"
              class="c-textarea"
              rows="4"
              maxlength="2000"
              placeholder="说明你打算开什么规则的团、有没有带团经验、大致的开团频率。"
            ></textarea>
            <p class="c-field__hint">站主审批后，结果会通过站内通知告诉你。</p>
          </div>
          <div class="c-actions">
            <CButton type="submit" :disabled="gmBusy">
              {{ gmBusy ? '提交中…' : '提交申请' }}
            </CButton>
          </div>
        </form>
      </template>
    </div>

    <!-- —— 危险区 —— -->
    <div class="block danger">
      <h3 class="u-kicker block__title">危险区：注销账号</h3>
      <CNotice v-if="deactivateError" tone="danger">{{ deactivateError }}</CNotice>

      <p class="u-small note">
        注销后，你的昵称会被<strong>匿名化</strong>，其他人将无法再看到你原来的昵称。账号记录会保留在站内，不会被彻底删除；你写过的战报和评价按本站规则处理；你参加过的团仍会保留在其他成员的记录中。注销操作无法撤销。
      </p>

      <div v-if="confirmStage === 0" class="c-actions">
        <CButton variant="text" @click="confirmStage = 1">我要注销账号</CButton>
      </div>

      <template v-else>
        <CNotice tone="danger" title="再确认一次">
          点击下方的「确认注销」按钮后，账号会立即注销：你会被退出登录，昵称会被匿名化，之后将无法再使用这个账号登录。
        </CNotice>
        <div class="c-actions">
          <CButton variant="danger" :disabled="deactivating" @click="onDeactivate">
            {{ deactivating ? '处理中…' : '确认注销' }}
          </CButton>
          <CButton variant="text" @click="confirmStage = 0">取消，不注销</CButton>
        </div>
      </template>
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
  margin: 0 0 var(--sp-3);
}

.note {
  margin: var(--sp-3) 0 0;
  line-height: var(--lh-body);
  color: var(--ink-muted);
}

.avatar-row {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
}

.avatar {
  flex: none;
  width: 64px;
  height: 64px;
  object-fit: cover;
  border-radius: var(--radius-pill);
  background: var(--avatar-bg);
}

.avatar--blank {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--fs-2xl);
  color: var(--on-brand);
}

.avatar-row__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3);
}

.file {
  position: relative;
  overflow: hidden;
  cursor: pointer;
}

.file__input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.gm-form {
  margin-top: var(--sp-3);
}

.danger {
  padding-top: var(--sp-5);
  border-top: 1px solid var(--danger-line);
}
</style>
