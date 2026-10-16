<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, ref } from 'vue'
import CButton from '../CButton.vue'
import CNotice from '../CNotice.vue'
import {
  ANNOUNCEMENT_MAX,
  createAnnouncement,
  deleteAnnouncement,
  patchAnnouncement,
} from '../../api/homeAdmin'
import { errorText, fieldText } from '../../lib/api-error'
import { formatDateTime } from '../../lib/datetime'
import { useAuthStore } from '../../stores/auth'
import { useEditStore } from '../../stores/edit'
import { useHomeStore } from '../../stores/home'

const edit = useEditStore()
const home = useHomeStore()
const auth = useAuthStore()

const title = ref('')
const body = ref('')
const publishAsk = ref(false)
const sending = ref(false)
const formError = ref('')
const fields = ref<Record<string, string>>({})
const note = ref('')

/** 正在等第二步确认的那条公告 id（删除）。 */
const deleteAsk = ref<number | null>(null)
/** 正在动的那条公告 id（按钮禁用用）。 */
const acting = ref<number | null>(null)

const canPublish = computed(() => title.value.trim() !== '' && body.value.trim() !== '')

/** 公告改动会影响首页横幅与公告历史，动完一律强刷公开读 + 重取 admin 列表。 */
async function refresh(): Promise<void> {
  await Promise.all([home.load(auth.authenticated, true), edit.reload()])
}

async function onPublish(): Promise<void> {
  if (sending.value) return
  sending.value = true
  formError.value = ''
  fields.value = {}
  note.value = ''
  try {
    await createAnnouncement({ title: title.value.trim(), body: body.value.trim() })
    title.value = ''
    body.value = ''
    publishAsk.value = false
    note.value = '已发布，并已推送给全站成员。'
    await refresh()
  } catch (e) {
    fields.value = fieldText(e)
    formError.value = errorText(e, '公告发布失败，请稍后再试。')
  } finally {
    sending.value = false
  }
}

async function onToggle(id: number, isActive: boolean): Promise<void> {
  if (acting.value !== null) return
  acting.value = id
  formError.value = ''
  note.value = ''
  try {
    await patchAnnouncement(id, { is_active: isActive })
    note.value = isActive ? '已启用。' : '已停用，这条公告不再显示在首页与公告历史里。'
    await refresh()
  } catch (e) {
    formError.value = errorText(e, '公告状态修改失败，请稍后再试。')
  } finally {
    acting.value = null
  }
}

async function onDelete(id: number): Promise<void> {
  if (acting.value !== null) return
  acting.value = id
  formError.value = ''
  note.value = ''
  try {
    await deleteAnnouncement(id)
    deleteAsk.value = null
    note.value = '已撤回，这条公告与它推出去的通知都已删除。'
    await refresh()
  } catch (e) {
    formError.value = errorText(e, '公告撤回失败，请稍后再试。')
  } finally {
    acting.value = null
  }
}
</script>

<template>
  <section class="ap" aria-label="站长公告（编辑）">
    <h2 class="ap__h">站长公告</h2>
    <p class="ap__sub">
      公告发布后立刻推送给全站成员，与底部的「保存」无关。这里只发「此刻」，没有定时发布。
    </p>

    <CNotice v-if="formError" tone="danger">{{ formError }}</CNotice>
    <CNotice v-else-if="note" tone="ok">{{ note }}</CNotice>

    <form class="ap__form" novalidate @submit.prevent="publishAsk = true">
      <label class="ap__label" for="ap-title">标题</label>
      <input
        id="ap-title"
        v-model="title"
        class="c-input"
        data-edit
        type="text"
        :maxlength="ANNOUNCEMENT_MAX.title"
        :aria-invalid="fields.title ? 'true' : undefined"
        placeholder="例：十月线下场地换到活动室 B"
      />
      <p v-if="title.length > ANNOUNCEMENT_MAX.title * 0.8" class="ap__count">
        {{ title.length }} / {{ ANNOUNCEMENT_MAX.title }} 字
      </p>
      <p v-if="fields.title" class="ap__err">{{ fields.title }}</p>

      <label class="ap__label" for="ap-body">正文</label>
      <textarea
        id="ap-body"
        v-model="body"
        class="c-textarea"
        data-edit
        rows="4"
        :maxlength="ANNOUNCEMENT_MAX.body"
        :aria-invalid="fields.body ? 'true' : undefined"
        placeholder="正文只收纯文本，需要换行就直接敲回车。"
      ></textarea>
      <p v-if="body.length > ANNOUNCEMENT_MAX.body * 0.8" class="ap__count">
        {{ body.length }} / {{ ANNOUNCEMENT_MAX.body }} 字
      </p>
      <p v-if="fields.body" class="ap__err">{{ fields.body }}</p>

      <div v-if="publishAsk" class="ap__ask">
        <span>这条公告会立刻发布，并给全站成员各推一条通知。确认发布？</span>
        <CButton class="ap__btn" :disabled="sending" @click="onPublish">
          {{ sending ? '正在发布…' : '确认发布' }}
        </CButton>
        <CButton class="ap__btn" variant="ghost" @click="publishAsk = false">取消</CButton>
      </div>
      <div v-else class="c-actions">
        <CButton class="ap__btn" type="submit" :disabled="!canPublish || sending">
          发布并推送
        </CButton>
      </div>
    </form>

    <h3 class="ap__h3">最近的公告</h3>
    <p v-if="!edit.announcements.length" class="ap__empty">还没有发过公告。</p>
    <ul v-else class="ap__list">
      <li v-for="row in edit.announcements" :key="row.id" class="ap__row">
        <div class="ap__rowhead">
          <strong class="ap__rowtitle">{{ row.title }}</strong>
          <span class="ap__tag" :class="row.is_active ? 'ap__tag--on' : 'ap__tag--off'">
            {{ row.is_active ? '生效中' : '已停用' }}
          </span>
        </div>
        <p class="ap__meta">
          {{ formatDateTime(row.published_at) }} ·
          {{
            row.notified_at
              ? '已推送给 ' + row.notified_count + ' 人（' + formatDateTime(row.notified_at) + '）'
              : '还没推送过'
          }}
        </p>
        <p class="ap__body">{{ row.body }}</p>

        <div v-if="deleteAsk === row.id" class="ap__ask">
          <span>
            撤回会把这条公告删掉，已经推给全站成员的那条通知也会一起消失。确认撤回？
          </span>
          <CButton class="ap__btn" variant="danger" :disabled="acting !== null" @click="onDelete(row.id)">
            确认撤回
          </CButton>
          <CButton class="ap__btn" variant="ghost" @click="deleteAsk = null">再想想</CButton>
        </div>
        <div v-else class="c-actions">
          <CButton
            class="ap__btn"
            variant="ghost"
            :disabled="acting !== null"
            @click="onToggle(row.id, !row.is_active)"
          >
            {{ row.is_active ? '停用' : '启用' }}
          </CButton>
          <CButton class="ap__btn" variant="danger" @click="deleteAsk = row.id">删除</CButton>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.ap {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-4);
  background: var(--white);
  border: 1px dashed var(--brand-ink);
  border-radius: var(--radius-lg);
}

.ap__h {
  margin: 0;
  font-size: var(--fs-xl);
  line-height: var(--lh-card);
  color: var(--ink);
}

.ap__h3 {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-sm);
  letter-spacing: var(--ls-wide);
  color: var(--ink-soft);
}

.ap__sub,
.ap__meta,
.ap__count,
.ap__empty {
  margin: 0;
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps-sm);
  line-height: 1.6;
  color: var(--ink-muted);
}

.ap__form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.ap__label {
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-soft);
}

.ap__err {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--danger);
}

.ap__ask {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2);
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--ink);
  background: var(--bg-2);
  border-radius: var(--radius);
}

.ap__btn {
  min-height: 44px;
}

.ap__list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.ap__row {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-3);
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.ap__rowhead {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
}

.ap__rowtitle {
  font-size: var(--fs-base);
  color: var(--ink);
}

.ap__tag {
  padding: 1px var(--sp-2);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps);
  border-radius: var(--radius-pill);
}

/** 业务界面遵循后端权限与隐私约束。 */
.ap__tag--on {
  color: var(--on-brand);
  background: var(--ok);
  border: 1px solid var(--ok);
}

.ap__tag--off {
  color: var(--ink-muted);
  background: var(--bg-2);
  border: 1px solid var(--line);
}

.ap__body {
  margin: 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  color: var(--ink-soft);
  white-space: pre-wrap;
}
</style>
