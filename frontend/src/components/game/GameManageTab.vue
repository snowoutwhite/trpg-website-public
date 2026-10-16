<script setup lang="ts">
/**
 * 「管理」标签（v2 `game.html` 的 `#manage` 面板）。原 `/games/:id/manage` 整页并进这里。
 * **只有本团 GM 看得到这个标签**（`GameDetailView` 按 `roster.is_gm` 决定挂不挂）。
 *
 * 这里是 GM 视角的全量名单：含已退出 / 被移除的人，带交上来的卡（鉴权下载路径）与审批备注。
 * 拒绝与移除都必须写理由（后端必填），对方会收到通知。
 *
 * 结团：先勾到场名单再结。**到场名单为空结不了团**（W5 后端加的闸），所以这里一个都没勾时
 * 直接把按钮禁掉并说明原因，而不是让它 400 回来。
 *
 * 代传卡：卡归 PL 所有、默认私密，传完这条报名直接通过；列表里那条卡会标「GM 代传」
 * （后端 `card_uploaded_by_gm`）。
 */
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import CButton from '../CButton.vue'
import CNotice from '../CNotice.vue'
import CPill from '../CPill.vue'
import CEmpty from '../CEmpty.vue'
import PersonLine from './PersonLine.vue'
import {
  cancelGame,
  confirmWithdraw,
  createSession,
  deleteSession,
  expandGame,
  finishGame,
  gmUploadCard,
  removeSignup,
  reviewSignup,
  startGame,
  type GameDetail,
  type GMSignup,
} from '../../api/games'
import { checkCardFile } from '../../api/cards'
import { errorText } from '../../lib/api-error'
import { formatDateTime, fromLocalInput } from '../../lib/datetime'

/** 审批备注 / 移除理由 / 取消理由的上限。 */
const NOTE_MAX = 500

const props = defineProps<{ game: GameDetail; signups: GMSignup[] }>()
const emit = defineEmits<{ reload: [] }>()

const acting = ref('')
const actionError = ref('')
const actionOk = ref('')

/** 每行展开的输入。 */
const noteDraft = ref<Record<number, string>>({})
const reasonDraft = ref<Record<number, string>>({})
const openRow = ref<number | null>(null)

const expandTo = ref('')
const cancelReason = ref('')
const showCancel = ref(false)
const showFinish = ref(false)
const attended = ref<Record<number, boolean>>({})

const sessionIndex = ref('0')
const sessionLabel = ref('')
const sessionHeldAt = ref('')

const activeSignups = computed(() =>
  props.signups.filter((s) => ['pending', 'submitted', 'accepted', 'no_card'].includes(s.status)),
)
const acceptedSignups = computed(() => props.signups.filter((s) => s.status === 'accepted'))
const closedSignups = computed(() =>
  props.signups.filter((s) => ['rejected', 'withdrawn', 'removed'].includes(s.status)),
)
const withdrawRequests = computed(() =>
  props.signups.filter((s) => s.withdraw_requested_at && s.status !== 'withdrawn'),
)
const attendedCount = computed(() => Object.values(attended.value).filter(Boolean).length)
const isOver = computed(
  () => props.game.status === 'finished' || props.game.status === 'cancelled',
)

/** 展开结团面板时默认勾上全部成功报团的人，GM 再手动取消没到的。 */
function openFinish(): void {
  showFinish.value = !showFinish.value
  if (!showFinish.value) return
  const marks: Record<number, boolean> = {}
  for (const item of acceptedSignups.value) marks[item.id] = true
  attended.value = marks
}

async function run(key: string, fn: () => Promise<unknown>, okText: string): Promise<void> {
  if (acting.value) return
  acting.value = key
  actionError.value = ''
  actionOk.value = ''
  try {
    await fn()
    actionOk.value = okText
    emit('reload')
  } catch (e) {
    actionError.value = errorText(e, '操作失败')
  } finally {
    acting.value = ''
  }
}

function onApprove(item: GMSignup, approved: boolean): void {
  void run(
    'review-' + item.id,
    () => reviewSignup(props.game.id, item.id, approved, noteDraft.value[item.id] ?? ''),
    approved ? '已通过。' : '已拒绝，理由会发给对方。',
  )
}

function onRemove(item: GMSignup): void {
  const reason = (reasonDraft.value[item.id] ?? '').trim()
  if (!reason) {
    actionError.value = '移除报名者时须填写理由。'
    return
  }
  void run('remove-' + item.id, () => removeSignup(props.game.id, item.id, reason), '已移出名单。')
}

function onConfirmWithdraw(item: GMSignup, approved: boolean): void {
  void run(
    'withdraw-' + item.id,
    () => confirmWithdraw(props.game.id, item.id, approved, noteDraft.value[item.id] ?? ''),
    approved ? '已确认退出。' : '已驳回退出申请。',
  )
}

function onUploadCard(item: GMSignup, event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const problem = checkCardFile(file)
  if (problem) {
    actionError.value = problem
    input.value = ''
    return
  }
  void run(
    'upload-' + item.id,
    () =>
      gmUploadCard(props.game.id, item.id, file, {
        name: item.player.nickname + ' 的卡',
        rule_system: props.game.rule_system,
        note: '由 GM 代传',
      }),
    '卡已代传（会标注「GM 代传」），这条报名直接通过。',
  ).finally(() => {
    input.value = ''
  })
}

function onExpand(): void {
  const n = Number(expandTo.value || props.game.max_players)
  if (!Number.isInteger(n) || n < 1) {
    actionError.value = '扩容后的人数须为不小于 1 的整数。'
    return
  }
  void run('expand', () => expandGame(props.game.id, n), '人数上限已改。')
}

function onStart(): void {
  void run('start', () => startGame(props.game.id), '团已开始。')
}

function onFinish(): void {
  const ids = Object.entries(attended.value)
    .filter(([, on]) => on)
    .map(([id]) => Number(id))
  if (!ids.length) {
    actionError.value = '结团前须至少勾选一位到场成员。'
    return
  }
  void run(
    'finish',
    () => finishGame(props.game.id, ids),
    '已结团，到场名单已登记，评价窗口随之打开。',
  )
  showFinish.value = false
}

function onCancel(): void {
  const reason = cancelReason.value.trim()
  if (!reason) {
    actionError.value = '取消团时须填写理由。'
    return
  }
  void run('cancel', () => cancelGame(props.game.id, reason), '团已取消。')
  showCancel.value = false
}

function onAddSession(): void {
  const index = Number(sessionIndex.value)
  if (!Number.isInteger(index) || index < 0) {
    actionError.value = '场次序号须为不小于 0 的整数。'
    return
  }
  void run(
    'session-add',
    () =>
      createSession(props.game.id, {
        index,
        label: sessionLabel.value.trim(),
        held_at: fromLocalInput(sessionHeldAt.value),
      }),
    '场次已登记。',
  )
  sessionLabel.value = ''
  sessionHeldAt.value = ''
}

function onDeleteSession(id: number): void {
  void run('session-del-' + id, () => deleteSession(props.game.id, id), '场次已删除。')
}

function toggleRow(id: number): void {
  openRow.value = openRow.value === id ? null : id
}

function toneOf(status: string): 'ok' | 'wait' | 'off' {
  if (status === 'accepted') return 'ok'
  if (status === 'pending' || status === 'submitted') return 'wait'
  return 'off'
}
</script>

<template>
  <div class="mg">
    <h2 class="u-h-section mg__h">管理</h2>
    <p class="mg__sub">
      本页只有本团 GM 能够看到。审核报名、提高人数上限、开团、结团、取消本团以及登记场次，都在本页操作。
    </p>

    <CNotice v-if="actionError" tone="danger">{{ actionError }}</CNotice>
    <CNotice v-else-if="actionOk" tone="ok">{{ actionOk }}</CNotice>

    <p class="mg__counts">
      <CPill tone="ok">占位 {{ game.occupied_seats }} / {{ game.max_players }}</CPill>
      <CPill tone="off">成功报团 {{ game.accepted_count }}</CPill>
      <CPill tone="off">{{ game.signup_mode_display }}</CPill>
      <CPill tone="off">{{ game.requires_card ? '需交卡' : '免交卡' }}</CPill>
      <CPill tone="off">{{ game.status_display }}</CPill>
    </p>

    <!-- 退出申请（截止后退出要 GM 确认） -->
    <section v-if="withdrawRequests.length" class="mg__block">
      <h3 class="u-h-card mg__h3">待确认的退出申请</h3>
      <div v-for="item in withdrawRequests" :key="'w' + item.id" class="mg__row">
        <div class="mg__rowhead">
          <PersonLine :user="item.player" :link="false" />
          <CPill :tone="toneOf(item.status)">{{ item.status_display }}</CPill>
        </div>
        <p class="mg__note">
          申请于 {{ formatDateTime(item.withdraw_requested_at) }}
          {{ item.withdraw_reason ? '· 理由：' + item.withdraw_reason : '' }}
        </p>
        <div class="c-actions">
          <CButton :disabled="!!acting" @click="onConfirmWithdraw(item, true)">同意退出</CButton>
          <CButton variant="ghost" :disabled="!!acting" @click="onConfirmWithdraw(item, false)">
            驳回
          </CButton>
        </div>
      </div>
    </section>

    <!-- 报名审核 -->
    <section class="mg__block">
      <h3 class="u-h-card mg__h3">报名审核</h3>
      <p class="mg__small">
        此处只有 GM 能看到，列出全部报名记录（包括已退出和已被移出的玩家），也可以下载玩家提交的角色卡。拒绝报名或将玩家移出名单时必须填写理由，对方会收到包含该理由的通知。
      </p>

      <CEmpty v-if="!activeSignups.length" compact title="暂时还没有人报名" text="有玩家报名后，报名信息会显示在此处。" />

      <div v-for="item in activeSignups" :key="item.id" class="mg__row">
        <div class="mg__rowhead">
          <span class="mg__no">{{ String(item.order).padStart(2, '0') }}</span>
          <PersonLine :user="item.player" :link="false" />
          <CPill :tone="toneOf(item.status)">{{ item.status_display }}</CPill>
        </div>

        <p class="mg__note">
          报名于 {{ formatDateTime(item.created_at) }}
          <template v-if="item.card">
            · 卡：<a class="u-tap" :href="item.card.download_url">{{ item.card.name }}</a>
            <span v-if="item.card_uploaded_by_gm"> （GM 代传）</span>
            <span v-if="item.card_submitted_at"> · 交于 {{ formatDateTime(item.card_submitted_at) }}</span>
          </template>
          <template v-else>· 尚未交卡</template>
        </p>
        <p v-if="item.review_note" class="mg__note">审批备注：{{ item.review_note }}</p>

        <CButton variant="text" @click="toggleRow(item.id)">
          {{ openRow === item.id ? '收起操作' : '处理这条报名' }}
        </CButton>

        <div v-if="openRow === item.id" class="mg__ops">
          <label class="mg__label" :for="'note-' + item.id">审批备注 / 拒绝理由</label>
          <textarea
            :id="'note-' + item.id"
            v-model="noteDraft[item.id]"
            class="c-textarea"
            rows="2"
            :maxlength="NOTE_MAX"
            placeholder="拒绝报名时请写清楚原因，对方会在通知中看到这段文字。"
          ></textarea>
          <p class="mg__count">{{ (noteDraft[item.id] ?? '').length }} / {{ NOTE_MAX }} 字</p>
          <div class="c-actions">
            <CButton :disabled="!!acting" @click="onApprove(item, true)">通过</CButton>
            <CButton variant="ghost" :disabled="!!acting" @click="onApprove(item, false)">
              拒绝
            </CButton>
          </div>

          <label class="mg__label" :for="'file-' + item.id">代为上传角色卡（玩家无法自行交卡时使用）</label>
          <input
            :id="'file-' + item.id"
            class="c-input"
            type="file"
            :disabled="!!acting"
            @change="onUploadCard(item, $event)"
          />
          <p class="mg__small">
            代传的角色卡归该玩家所有，默认不公开，站内会标注「GM 代传」。上传完成后，这条报名会直接通过审核。
            可以上传 PDF、Excel 表格、Word 文档、文本文件或 PNG、JPG 图片，单个文件不能超过 20 MB。
          </p>

          <label class="mg__label" :for="'reason-' + item.id">移除理由（必填）</label>
          <textarea
            :id="'reason-' + item.id"
            v-model="reasonDraft[item.id]"
            class="c-textarea"
            rows="2"
            :maxlength="NOTE_MAX"
            placeholder="移出后对方会收到通知，并且不能再次报名本团。"
          ></textarea>
          <p class="mg__count">{{ (reasonDraft[item.id] ?? '').length }} / {{ NOTE_MAX }} 字</p>
          <div class="c-actions">
            <CButton variant="danger" :disabled="!!acting" @click="onRemove(item)">移出名单</CButton>
          </div>
        </div>
      </div>

      <details v-if="closedSignups.length" class="mg__closed">
        <summary>已结案的报名（{{ closedSignups.length }} 条）</summary>
        <div v-for="item in closedSignups" :key="'c' + item.id" class="mg__row mg__row--flat">
          <div class="mg__rowhead">
            <PersonLine :user="item.player" :size="24" :link="false" />
            <CPill tone="off">{{ item.status_display }}</CPill>
          </div>
          <p v-if="item.review_note" class="mg__note">备注：{{ item.review_note }}</p>
        </div>
      </details>
    </section>

    <!-- 团的状态 -->
    <section class="mg__block">
      <h3 class="u-h-card mg__h3">团的状态</h3>

      <div class="mg__acts">
        <div class="mg__act">
          <h4 class="mg__acth">扩容</h4>
          <p class="mg__small">提高本团的人数上限。如果本团已满员，提高上限后会自动恢复为「招募中」状态，其他玩家可以继续报名。</p>
          <div class="mg__line">
            <label class="u-hidden" for="mg-expand">人数上限</label>
            <input
              id="mg-expand"
              v-model="expandTo"
              class="c-input"
              type="number"
              min="1"
              :placeholder="String(game.max_players)"
            />
            <CButton variant="ghost" :disabled="!!acting || isOver" @click="onExpand">
              修改上限
            </CButton>
          </div>
        </div>

        <div class="mg__act">
          <h4 class="mg__acth">编辑团</h4>
          <p class="mg__small">
            团介绍、开团时间、人数和报名门槛都在编辑页面中修改。开团时间、人数和门槛等条件修改后，招募列表中显示的信息会同步更新。
          </p>
          <RouterLink class="c-btn c-btn--ghost mg__btn" :to="'/games/' + game.id + '/edit'">
            前往编辑
          </RouterLink>
        </div>

        <div class="mg__act">
          <h4 class="mg__acth">开团</h4>
          <p class="mg__small">到达开团时间后，本团会自动变为「进行中」；你也可以现在手动开始。本团开始后将不再接受新的报名。</p>
          <CButton
            variant="ghost"
            class="mg__btn"
            :disabled="!!acting || (game.status !== 'recruiting' && game.status !== 'closed_signup')"
            @click="onStart"
          >
            手动开始
          </CButton>
        </div>

        <div class="mg__act">
          <h4 class="mg__acth">结团</h4>
          <p class="mg__small">
            请先勾选实际到场的成员，再确认结团。至少要勾选一名到场成员才能结团。结团后到场名单将无法修改，同时开放团后评价。
          </p>
          <CButton class="mg__btn" :disabled="isOver" @click="openFinish">
            {{ showFinish ? '暂不结团' : '结团并开放评价' }}
          </CButton>
        </div>

        <div class="mg__act">
          <h4 class="mg__acth">取消</h4>
          <p class="mg__small">取消本团时必须填写理由，所有报名者都会收到包含该理由的通知。已取消的团不会计入任何人的团次数，也不会开放团后评价。</p>
          <CButton variant="danger" class="mg__btn" :disabled="isOver" @click="showCancel = !showCancel">
            {{ showCancel ? '暂不取消' : '取消本团' }}
          </CButton>
        </div>
      </div>

      <div v-if="showFinish" class="mg__box">
        <p class="mg__label">勾选实际到场的成员</p>
        <p class="mg__small">
          只有被勾选的成员会计入团次数，并且可以撰写战报、参与团后评价。报名了但没有到场的成员请不要勾选。GM 本人无需勾选，系统会自动把 GM 记为到场。
        </p>
        <CEmpty
          v-if="!acceptedSignups.length"
          compact
          title="正式名单中暂时没有成功报团的成员"
          text="至少需要一名到场成员才能结团。请先审核通过报名，或者选择取消本团。"
        />
        <template v-else>
          <label v-for="item in acceptedSignups" :key="'a' + item.id" class="mg__check">
            <input v-model="attended[item.id]" type="checkbox" />
            <span>{{ item.player.nickname }}</span>
          </label>
          <p v-if="attendedCount === 0" class="mg__warn">
            你还没有勾选任何成员。至少需要勾选一名到场成员才能结团。
          </p>
        </template>
        <div class="c-actions">
          <CButton :disabled="!!acting || attendedCount === 0" @click="onFinish">确认结团</CButton>
        </div>
      </div>

      <div v-if="showCancel" class="mg__box">
        <label class="mg__label" for="mg-cancel">取消理由（必填，所有报名者都会在通知中看到）</label>
        <textarea
          id="mg-cancel"
          v-model="cancelReason"
          class="c-textarea"
          rows="3"
          :maxlength="NOTE_MAX"
        ></textarea>
        <p class="mg__count">{{ cancelReason.length }} / {{ NOTE_MAX }} 字</p>
        <div class="c-actions">
          <CButton variant="danger" :disabled="!!acting" @click="onCancel">确认取消</CButton>
        </div>
      </div>
    </section>

    <!-- 场次 -->
    <section class="mg__block">
      <h3 class="u-h-card mg__h3">场次登记</h3>
      <p class="mg__small">
        需要多次聚会才能跑完的长团，可以按「第 0 回」「第 1 回」等回次登记每一场，登记的场次会显示在「团介绍」中。场次仅用于记录；无论实际跑了多少场，团次数和团后评价都只按整个团计算一次。
      </p>
      <ul v-if="game.sessions.length" class="mg__sessions">
        <li v-for="s in game.sessions" :key="s.id">
          <span class="mg__sno">{{ s.display_label }}</span>
          <span class="mg__stime">{{ s.held_at ? formatDateTime(s.held_at) : '时间待定' }}</span>
          <span class="mg__grow" />
          <CButton variant="text" :disabled="!!acting" @click="onDeleteSession(s.id)">删除</CButton>
        </li>
      </ul>

      <div class="mg__grid">
        <div>
          <label class="mg__label" for="mg-sidx">序号</label>
          <input id="mg-sidx" v-model="sessionIndex" class="c-input" type="number" min="0" />
        </div>
        <div>
          <label class="mg__label" for="mg-slabel">名称（可不填）</label>
          <input
            id="mg-slabel"
            v-model="sessionLabel"
            class="c-input"
            type="text"
            maxlength="60"
            placeholder="例：第 0 回"
          />
        </div>
        <div>
          <label class="mg__label" for="mg-sheld">时间（可不填）</label>
          <input id="mg-sheld" v-model="sessionHeldAt" class="c-input" type="datetime-local" />
        </div>
      </div>
      <div class="c-actions">
        <CButton variant="ghost" :disabled="!!acting" @click="onAddSession">登记这一场</CButton>
      </div>
    </section>

    <CNotice v-if="game.mutual_review" class="mg__block" title="评价互见开关已冻结">
      本团开启了评价互见。只要已经有人报名，这项设置就不能再修改：成员报名时已经按当时的设置表示同意，
      中途修改相当于替他们改变了决定。如果需要不同的设置，只能另开一个新团。
    </CNotice>
  </div>
</template>

<style scoped>
.mg {
  max-width: 920px;
}

.mg__h {
  margin: 0 0 var(--sp-2);
}

.mg__sub {
  max-width: 62ch;
  margin: 0 0 var(--sp-4);
  font-size: var(--fs-sm);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.mg__counts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin: 0 0 var(--sp-5);
}

.mg__block {
  margin-top: var(--sp-6);
}

.mg__h3 {
  margin: 0 0 var(--sp-1);
}

.mg__small {
  margin: 0 0 var(--sp-2);
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.mg__row {
  padding: var(--sp-3) 0;
  border-bottom: 1px solid var(--line);
}

.mg__row--flat {
  border-bottom: 1px solid var(--bg-2);
}

.mg__rowhead {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-3);
}

.mg__no {
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps);
  color: var(--ink-faint);
}

.mg__note {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  color: var(--ink-muted);
  overflow-wrap: anywhere;
}

.mg__ops {
  margin-top: var(--sp-3);
  padding: var(--sp-4);
  background: var(--bg-2);
  border-radius: var(--radius);
}

.mg__label {
  display: block;
  margin: var(--sp-4) 0 var(--sp-1);
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-wide);
  color: var(--ink-muted);
}

.mg__ops .mg__label:first-child {
  margin-top: 0;
}

/* 字数提示：后端三个理由字段都卡 500 字，写之前就看得到余量 */
.mg__count {
  margin: var(--sp-1) 0 0;
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-wide);
  color: var(--ink-faint);
  text-align: right;
}

.mg__closed {
  margin-top: var(--sp-4);
  font-size: var(--fs-sm);
}

.mg__closed summary {
  display: flex;
  align-items: center;
  min-height: 44px;
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-muted);
  cursor: pointer;
}

.mg__acts {
  display: grid;
  gap: var(--sp-4);
  margin-top: var(--sp-3);
}

/** 业务界面遵循后端权限与隐私约束。 */
@media (min-width: 768px) {
  .mg__acts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.mg__act {
  padding: var(--sp-4);
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.mg__acth {
  margin: 0 0 var(--sp-1);
  font-size: var(--fs-md);
  font-weight: 400;
}

.mg__btn {
  margin-top: var(--sp-2);
}

/** 业务界面遵循后端权限与隐私约束。 */
.mg__btn:disabled,
.mg__box .c-btn:not(.c-btn--text):disabled {
  opacity: 1;
  color: var(--ink-faint);
  background: var(--bg-2);
  border-color: var(--line);
}

.mg__line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
}

.mg__line .c-input {
  flex: 1 1 7em;
}

.mg__box {
  margin-top: var(--sp-4);
  padding: var(--sp-4);
  background: var(--white);
  border: 1px dashed var(--line-2);
  border-radius: var(--radius);
}

.mg__check {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  min-height: 44px;
  font-size: var(--fs-md);
  cursor: pointer;
}

.mg__check input {
  width: 17px;
  height: 17px;
  accent-color: var(--brand);
}

.mg__warn {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-xs);
  color: var(--danger);
}

.mg__sessions {
  margin: var(--sp-2) 0 var(--sp-4);
  padding: 0;
  list-style: none;
}

.mg__sessions li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-4);
  min-height: 44px;
  padding: var(--sp-1) 0;
  border-bottom: 1px solid var(--line);
  font-size: var(--fs-md);
}

.mg__stime {
  color: var(--ink-muted);
}

.mg__grow {
  flex: 1 1 auto;
}

.mg__grid {
  display: grid;
  gap: var(--sp-2);
}

@media (min-width: 768px) {
  .mg__grid {
    grid-template-columns: 7em minmax(0, 1fr) minmax(0, 1fr);
    gap: var(--sp-4);
    align-items: end;
  }
}

@media (min-width: 1200px) {
  /** 业务界面遵循后端权限与隐私约束。 */
  .mg__row:not(.mg__row--flat) {
    display: grid;
    grid-template-columns: minmax(0, auto) minmax(0, 1fr) auto;
    column-gap: var(--sp-4);
    align-items: center;
  }

  .mg__row:not(.mg__row--flat) > .mg__rowhead {
    grid-column: 1;
    grid-row: 1;
  }

  .mg__row:not(.mg__row--flat) > .mg__note {
    grid-column: 2;
  }

  .mg__row:not(.mg__row--flat) > .mg__note:first-of-type {
    grid-row: 1;
    margin-top: 0;
  }

  .mg__row:not(.mg__row--flat) > .c-btn {
    grid-column: 3;
    grid-row: 1;
    justify-self: end;
  }

  .mg__row:not(.mg__row--flat) > .mg__ops {
    grid-column: 1 / -1;
  }

  /* 宽屏上说明文字放宽到 72ch（62ch 在 1440 以上显得过窄） */
  .mg__sub {
    max-width: 72ch;
  }
}
</style>
