<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, ref, watch } from 'vue'
import CButton from '../CButton.vue'
import CNotice from '../CNotice.vue'
import CPill from '../CPill.vue'
import PersonLine from './PersonLine.vue'
import type { PublicUser } from '../../api/site'
import type { GivenReview, Verdict } from '../../api/reviews'

type Choice = Verdict | 'none'

const props = withDefaults(
  defineProps<{
    /** 被评者。 */
    user: PublicUser
    /** 被评者在本团里的身份文案（后端 `role_display`）。 */
    roleDisplay: string
    /** 已经提交过的那一条；没有就是还没评。 */
    existing?: GivenReview | null
    /** 正在提交。 */
    busy?: boolean
    /** 窗口关了：只读，不能改。 */
    readonly?: boolean
  }>(),
  { existing: null, busy: false, readonly: false },
)

const emit = defineEmits<{ submit: [payload: { verdict: Verdict; text: string }] }>()

const open = ref(false)
const choice = ref<Choice>('none')
const text = ref('')
/** 业务界面遵循后端权限与隐私约束。 */
const REVIEW_TEXT_MAX = 5000
const localError = ref('')

/** 打开表单时把已提交的内容填回去（改评价是在原文上改，不是重写）。 */
function toggle(): void {
  open.value = !open.value
  if (!open.value) return
  choice.value = props.existing ? props.existing.verdict : 'none'
  text.value = props.existing?.text ?? ''
  localError.value = ''
}

/** 提交成功后父组件会重拉，`existing` 一变就把表单收起来。 */
watch(
  () => props.existing?.updated_at,
  () => {
    open.value = false
  },
)

const canSubmit = computed(() => choice.value !== 'none' && text.value.trim().length > 0)

function onSubmit(): void {
  if (choice.value === 'none') {
    localError.value = '「无评价」代表不提交本条评价，请直接关闭该行。'
    return
  }
  if (!text.value.trim()) {
    localError.value = '点赞或倒赞均须填写评价内容；如不填写，请勿提交，可选择「无评价」。'
    return
  }
  localError.value = ''
  emit('submit', { verdict: choice.value, text: text.value.trim() })
}
</script>

<template>
  <div class="rf">
    <div class="rf__head">
      <PersonLine :user="user" :size="30" />
      <CPill tone="off">{{ roleDisplay }}</CPill>
      <CPill v-if="existing" :tone="existing.verdict === 'like' ? 'ok' : 'warn'">
        已评 · {{ existing.verdict_display }}
      </CPill>
      <CPill v-else tone="off">无评价</CPill>
      <span class="rf__grow" />
      <CButton v-if="!readonly" variant="text" @click="toggle">
        {{ open ? '收起' : existing ? '修改评价' : '撰写评价' }}
      </CButton>
      <span v-else class="rf__small">评价已截止</span>
    </div>

    <p v-if="existing && !open" class="rf__done">{{ existing.text }}</p>

    <form v-if="open" class="rf__form" novalidate @submit.prevent="onSubmit">
      <fieldset class="rf__verdicts">
        <legend class="rf__label">这次跑团的评级</legend>
        <label class="rf__opt">
          <input v-model="choice" type="radio" value="like" :name="'v-' + user.id" />
          <span>赞</span>
        </label>
        <label class="rf__opt">
          <input v-model="choice" type="radio" value="none" :name="'v-' + user.id" />
          <span>无评价</span>
        </label>
        <label class="rf__opt">
          <input v-model="choice" type="radio" value="dislike" :name="'v-' + user.id" />
          <span>倒赞</span>
        </label>
      </fieldset>

      <CNotice v-if="choice === 'none'" title="「无评价」也是一种评价结果">
        如果你在评价截止前没有提交评价，就记为「无评价」。「无评价」<strong class="rf__strong">既不算赞，也不算倒赞</strong>，但会计入对方的被评价次数。赞级别按赞和倒赞各自占被评价次数的比例算出，因此「无评价」会同时拉低赞所占的比例和倒赞所占的比例，使对方的赞级别更接近中间的「中性」。
        如果你想给出「无评价」，直接收起这一栏即可，不需要点击提交。
      </CNotice>
      <template v-else>
        <p v-if="choice === 'like'" class="rf__small rf__effect">
          「赞」会计入对方的赞数，有助于提升对方的赞级别。对方在本团担任 GM 时，计入其 GM 侧赞级别；以玩家身份参加时，计入其玩家侧赞级别。
        </p>
        <p v-else class="rf__small rf__effect">
          「倒赞」会计入对方的倒赞数，会拉低对方的赞级别。对方在本团担任 GM 时，计入其 GM 侧赞级别；以玩家身份参加时，计入其玩家侧赞级别。部分 GM 放团时会把赞级别设为报名条件，赞级别过低的玩家将无法报名这类团，因此请在评价内容中写明你给出倒赞的具体原因。
        </p>

        <label class="rf__label" :for="'t-' + user.id">评价内容（必填）</label>
        <textarea
          :id="'t-' + user.id"
          v-model="text"
          class="c-textarea"
          rows="4"
          :maxlength="REVIEW_TEXT_MAX"
          placeholder="请具体说明：哪些地方让你愿意再和这位成员一起跑团，或者哪些地方让你不愿意。"
        ></textarea>
        <p class="rf__small">
          评价是匿名的：对方能看到评价内容，但看不到是谁写的、什么时候写的。评价截止前可以回来修改，但提交后不能撤回。{{ text.length }} / {{ REVIEW_TEXT_MAX }} 字。
        </p>
      </template>

      <CNotice v-if="localError" tone="danger">{{ localError }}</CNotice>

      <div class="c-actions">
        <CButton v-if="choice !== 'none'" type="submit" :disabled="busy || !canSubmit">
          {{ busy ? '提交中…' : existing ? '保存修改' : '提交评价' }}
        </CButton>
        <CButton variant="ghost" @click="open = false">
          {{ choice === 'none' ? '保留为无评价' : '本次不评价' }}
        </CButton>
      </div>
    </form>
  </div>
</template>

<style scoped>
.rf {
  padding: var(--sp-3) 0;
  border-bottom: 1px solid var(--line);
}

.rf__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-3);
}

.rf__grow {
  flex: 1 1 auto;
}

.rf__done {
  margin: var(--sp-2) 0 0;
  padding-left: var(--sp-4);
  border-left: 2px solid var(--line-2);
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
  color: var(--ink-soft);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.rf__form {
  margin-top: var(--sp-3);
  padding: var(--sp-4);
  background: var(--bg-2);
  border-radius: var(--radius);
}

.rf__verdicts {
  margin: 0 0 var(--sp-3);
  padding: 0;
  border: 0;
}

.rf__label {
  display: block;
  margin-bottom: var(--sp-2);
  padding: 0;
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-wide);
  color: var(--ink-muted);
}

.rf__opt {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  min-height: 44px;
  margin-right: var(--sp-5);
  font-size: var(--fs-md);
  cursor: pointer;
}

.rf__opt input {
  width: 17px;
  height: 17px;
  accent-color: var(--brand);
}

.rf__small {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.rf__effect {
  margin: 0 0 var(--sp-3);
}

.rf__strong {
  font-weight: 400;
  color: var(--ink);
}

.rf__form :deep(.c-note) {
  margin-bottom: var(--sp-3);
}
</style>
