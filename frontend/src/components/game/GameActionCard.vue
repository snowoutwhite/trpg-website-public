<script setup lang="ts">
/** 首屏右侧的行动卡（v2 `game.html` 的 `.act`，四个身份分支：游客 / 未报名 PL / 已报名 PL / 本团 GM）。 */
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import CButton from '../CButton.vue'
import CNotice from '../CNotice.vue'
import CPill from '../CPill.vue'
import type { GameDetail } from '../../api/games'
import type { MyCard } from '../../api/cards'
import { formatDateTime, timeLeft } from '../../lib/datetime'

const props = defineProps<{
  game: GameDetail
  /** null = 还没判定完（auth 未就绪）；false = 游客。 */
  authenticated: boolean | null
  /** 当前登录者是不是本团 GM。 */
  isGm: boolean
  /** 自己名下还活着的卡（未过滤）。 */
  myCards: MyCard[]
  /** 正在提交（报名/交卡/退出共用一个闸）。 */
  busy: boolean
  /** 上一次动作的结果：就地显示在行动卡里，不要丢到页面下方去（首屏看不到）。 */
  noticeError: string
  noticeOk: string
  /** 登录页地址（已带 next 回跳），由调用方拼好。 */
  loginTo: string
}>()

const emit = defineEmits<{
  signup: []
  'submit-card': [cardId: number]
  withdraw: [reason: string]
  'go-tab': [key: string]
}>()

/** 「我这条还活着的报名」。 */
const mySignup = computed(() => {
  const signup = props.game.my_signup
  return signup && signup.status !== 'withdrawn' ? signup : null
})
/** 退出过、现在可以重新报名。 */
const withdrawnBefore = computed(() => props.game.my_signup?.status === 'withdrawn')
const isOver = computed(
  () => props.game.status === 'finished' || props.game.status === 'cancelled',
)
/** 交卡窗口：团还在招募/满员、且没过截止（与后端 `_assert_card_window` 同口径）。 */
const cardWindowOpen = computed(() => {
  if (!props.game.requires_card) return false
  if (props.game.status !== 'recruiting' && props.game.status !== 'closed_signup') return false
  return Date.now() <= new Date(props.game.card_deadline).getTime()
})
const usableCards = computed(() => props.myCards.filter((c) => c.is_usable_for_signup))
const cardsMissingFile = computed(() =>
  props.myCards.filter((c) => c.status === 'alive' && !c.has_file),
)

const chosenCard = ref<number | ''>('')
const swapping = ref(false)
const showWithdraw = ref(false)
const withdrawReason = ref('')

/** 报名状态一变（交完卡、被审完）就把表单收回去，不留脏态。 */
watch(
  () => mySignup.value?.status,
  () => {
    chosenCard.value = ''
    swapping.value = false
    showWithdraw.value = false
    withdrawReason.value = ''
  },
)

/** 报名还活着的四种状态：能退出、能交卡。 */
const signupAlive = computed(() =>
  ['pending', 'submitted', 'accepted', 'no_card'].includes(mySignup.value?.status ?? ''),
)
/** 后端 `submit_card` 只认这三态；`no_card`（逾期未交）交不上去，别给一个必然 400 的表单。 */
const canSubmitCard = computed(
  () =>
    cardWindowOpen.value &&
    ['pending', 'submitted', 'accepted'].includes(mySignup.value?.status ?? ''),
)
/** 交卡区要不要展开：没交过就一直展开，交过了点「换卡」才展开。 */
const cardFormOpen = computed(() => swapping.value || !mySignup.value?.card)

/** GM 视角的四格统计（v2 `.kv`）。名单细节在「管理」标签里。 */
const gmCounts = computed(() => props.game)

function onSubmitCard(): void {
  if (chosenCard.value === '') return
  emit('submit-card', Number(chosenCard.value))
}

function cancelSwap(): void {
  swapping.value = false
  chosenCard.value = ''
}
</script>

<template>
  <aside class="act" aria-label="报名">
    <!-- 动作结果就地显示：报名/交卡/退出的按钮都在这张卡里，提示跑到页面下方等于没有提示 -->
    <CNotice v-if="noticeError" tone="danger">{{ noticeError }}</CNotice>
    <CNotice v-else-if="noticeOk" tone="ok">{{ noticeOk }}</CNotice>

    <!-- —— 游客 —— -->
    <template v-if="authenticated !== true">
      <h2 class="act__title">报名需要登录</h2>
      <p class="act__lede">
        团介绍、开团时间和报名门槛对所有访客公开；报名者身份、成员名单、团相册和评价互见内容只有登录后才能查看。报名同样需要先登录。
      </p>
      <RouterLink class="c-btn c-btn--block act__btn" :to="loginTo">登录后报名</RouterLink>
      <RouterLink class="c-textlink act__link" to="/auth/signup">还没有账号？前往注册 →</RouterLink>
      <hr class="act__hr" />
      <p class="act__small">
        <template v-if="game.requires_card">
          本团要求提交角色卡，交卡截止时间为 {{ formatDateTime(game.card_deadline) }}。报名后如果在截止时间前没有提交角色卡，将视为放弃席位。
        </template>
        <template v-else>本团不要求提交角色卡，报名通过后即为成功报团。</template>
      </p>
    </template>

    <!-- —— 本团 GM —— -->
    <template v-else-if="isGm">
      <h2 class="act__title">你是本团 GM</h2>
      <p class="act__lede">审核报名、处理退出申请等操作，请在本页的「管理」标签中进行。</p>
      <!-- 业务信息 -->
      <dl class="act__kv">
        <dt>成功报团</dt>
        <dd>{{ gmCounts.accepted_count }} 人</dd>
      </dl>
      <CButton block class="act__btn" @click="emit('go-tab', 'manage')">进入管理</CButton>
      <RouterLink class="c-textlink act__link" :to="'/games/' + game.id + '/edit'">
        编辑团介绍 →
      </RouterLink>
      <hr class="act__hr" />
      <p class="act__small">
        评价互见{{ game.mutual_review ? '已开启' : '未开启' }}。本团收到第一条报名后，这项设置就不能再修改；如果需要不同的设置，只能另开一个新团。
      </p>
    </template>

    <!-- —— 已报名的 PL —— -->
    <template v-else-if="mySignup">
      <h2 class="act__title">你已报名</h2>
      <p class="act__lede">
        报名顺序第 {{ mySignup.order }} 位。
        <CPill :tone="mySignup.status === 'accepted' ? 'ok' : 'wait'">
          {{ mySignup.status_display }}
        </CPill>
      </p>

      <CNotice v-if="mySignup.review_note" tone="warn" title="GM 备注">
        {{ mySignup.review_note }}
      </CNotice>
      <CNotice v-if="mySignup.withdraw_requested_at" tone="warn" title="退出申请已提交">
        你于 {{ formatDateTime(mySignup.withdraw_requested_at) }} 提交了退出申请，目前正在等待 GM 确认。在 GM 确认之前，你仍然是本团成员。
      </CNotice>

      <!-- 交卡 -->
      <template v-if="game.requires_card">
        <div class="act__block">
          <p v-if="mySignup.card" class="act__small act__done">
            已交：<RouterLink class="u-tap" :to="'/cards/' + mySignup.card.id">
              {{ mySignup.card.name }}
            </RouterLink>
            <span v-if="mySignup.card_uploaded_by_gm" class="u-muted">（GM 代传）</span>
            <span v-if="mySignup.card_submitted_at" class="u-muted">
              · {{ formatDateTime(mySignup.card_submitted_at) }}
            </span>
          </p>

          <template v-if="canSubmitCard">
            <p v-if="!mySignup.card" class="act__small">
              你还需要提交一张角色卡，报名才算完成。交卡截止时间为 {{ formatDateTime(game.card_deadline) }}（{{
                timeLeft(game.card_deadline)
              }}）。
            </p>

            <CButton
              v-if="mySignup.card && !swapping"
              variant="ghost"
              block
              class="act__btn"
              @click="swapping = true"
            >
              更换角色卡
            </CButton>

            <template v-if="cardFormOpen">
              <template v-if="usableCards.length">
                <label class="act__label" for="act-card">从你的角色卡中选择一张</label>
                <select id="act-card" v-model="chosenCard" class="c-select">
                  <option value="">请选择</option>
                  <option v-for="card in usableCards" :key="card.id" :value="card.id">
                    {{ card.name }}{{ card.rule_system ? '（' + card.rule_system + '）' : '' }}
                  </option>
                </select>
                <CButton
                  block
                  class="act__btn"
                  :disabled="busy || chosenCard === ''"
                  @click="onSubmitCard"
                >
                  {{ busy ? '提交中…' : mySignup.card ? '改交这张卡' : '提交这张卡' }}
                </CButton>
                <CButton
                  v-if="swapping"
                  variant="text"
                  block
                  @click="cancelSwap"
                >
                  取消更换
                </CButton>
              </template>
              <p v-else class="act__small">
                <template v-if="cardsMissingFile.length">
                  你名下的角色卡都还没有上传卡片文件，提交后 GM 将无法打开查看。请先进入角色卡页面上传文件，然后再回到本页交卡。
                </template>
                <template v-else>
                  你名下暂时没有可以用于报名的角色卡（已撕卡的角色卡不能使用）。请先创建一张角色卡，然后再回到本页交卡。
                </template>
              </p>
              <!-- 业务信息 -->
              <RouterLink class="c-textlink act__link" :to="{ path: '/me/cards', query: { next: '/games/' + game.id } }">
                {{ cardsMissingFile.length ? '前往为角色卡上传文件' : '上传新角色卡后回来提交' }} →
              </RouterLink>
              <p v-if="usableCards.length && cardsMissingFile.length" class="act__small u-muted">
                你另有 {{ cardsMissingFile.length }} 张角色卡还没有上传文件，因此没有出现在上面的选择列表中。
              </p>
            </template>
          </template>

          <p v-else class="act__small">
            <template v-if="isOver">本团当前状态为「{{ game.status_display }}」，已经不能再提交或更换角色卡。</template>
            <template v-else>
              交卡已于 {{ formatDateTime(game.card_deadline) }} 截止，现在不能再提交或更换角色卡。
            </template>
          </p>
        </div>
      </template>
      <p v-else class="act__small act__block">本团不要求提交角色卡，报名通过后即为成功报团。</p>

      <!-- 退出 -->
      <template v-if="signupAlive && !isOver && !mySignup.withdraw_requested_at">
        <hr class="act__hr" />
        <CButton
          v-if="!showWithdraw"
          variant="ghost"
          block
          class="act__btn"
          @click="showWithdraw = true"
        >
          退出本团
        </CButton>
        <div v-else class="act__withdraw">
          <p class="act__small">
            在交卡截止时间（{{ formatDateTime(game.card_deadline) }}）之前，你可以直接退出本团；截止之后再退出，会先提交一条退出申请，需要 GM 确认后才会生效。
          </p>
          <label class="act__label" for="act-withdraw">退出理由（可不填）</label>
          <textarea
            id="act-withdraw"
            v-model="withdrawReason"
            class="c-textarea"
            rows="2"
            maxlength="500"
            placeholder="可以向 GM 简单说明退出的原因"
          ></textarea>
          <CButton
            variant="danger"
            block
            class="act__btn"
            :disabled="busy"
            @click="emit('withdraw', withdrawReason)"
          >
            {{ busy ? '处理中…' : '确认退出' }}
          </CButton>
          <CButton variant="text" block @click="showWithdraw = false">暂不退出</CButton>
        </div>
      </template>
    </template>

    <!-- —— 还没报名的 PL —— -->
    <template v-else>
      <h2 class="act__title">{{ withdrawnBefore ? '重新报名' : '报名' }}</h2>
      <p v-if="withdrawnBefore" class="act__small">
        你之前退出过本团。如果本团仍有空余位置，你可以再次报名。
      </p>
      <!-- 业务信息 -->
      <p class="act__lede">{{ game.signup_mode_display }}：{{
        game.signup_mode === 'pool_review'
          ? '所有报名会先进入候选名单，再由 GM 从中挑选成员，报名的先后顺序不影响结果。'
          : '按报名的先后顺序确认成员。需要交卡的团在交卡后即为成功报团，不需要交卡的团报名后即为成功报团；人数达到上限后停止接受报名。'
      }}</p>

      <dl class="act__kv">
        <dt>占位</dt>
        <dd>{{ game.occupied_seats }} / {{ game.max_players }} 人</dd>
        <template v-if="game.min_play_count !== null">
          <dt>团次数门槛</dt>
          <dd>≥ {{ game.min_play_count }}</dd>
        </template>
        <template v-if="game.min_level">
          <dt>赞级别门槛</dt>
          <dd>{{ game.min_level_display }} 及以上</dd>
        </template>
      </dl>

      <CButton block class="act__btn" :disabled="busy || !game.can_signup" @click="emit('signup')">
        {{ busy ? '提交中…' : '报名' }}
      </CButton>
      <p v-if="!game.can_signup" class="act__small">
        {{
          game.status !== 'recruiting'
            ? '本团当前状态为「' + game.status_display + '」，暂时不接受报名。'
            : game.is_full
              ? '本团人数已满。如果 GM 之后提高人数上限，你可以再回来报名。'
              : '你暂时不能报名本团：可能是你还没有达到本团的报名门槛，或者你已经是本团成员。'
        }}
      </p>

      <hr class="act__hr" />
      <p class="act__small">
        <template v-if="game.requires_card">
          <strong class="act__strong">本团要求提交角色卡，截止时间为 {{ formatDateTime(game.card_deadline) }}。</strong>
          截止时间由 GM 设定，最晚不会晚于开团时间。报名后，请在本页选择一张你的角色卡提交。
        </template>
        <template v-else>本团不要求提交角色卡，报名通过后即为成功报团。</template>
      </p>
    </template>
  </aside>
</template>

<style scoped>
/* v2 `.act`：压在首屏图上的一张白卡 */
.act {
  padding: var(--sp-5);
  color: var(--ink);
  background: var(--white);
  border-radius: var(--radius);
  box-shadow: var(--shadow-1);
}

.act__title {
  margin: 0 0 var(--sp-1);
  font-size: var(--fs-xl);
  font-weight: 400;
  line-height: var(--lh-card);
}

.act__lede {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.act__btn {
  margin-top: var(--sp-4);
}

.act__link {
  display: inline-flex;
  align-items: center;
  min-height: 40px;
  margin-top: var(--sp-2);
  font-size: var(--fs-xs);
}

.act__hr {
  margin: var(--sp-4) 0;
  border: 0;
  border-top: 1px solid var(--line);
}

.act__small {
  margin: var(--sp-3) 0 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.act__strong {
  font-weight: 400;
  color: var(--ink);
}

.act__done {
  color: var(--ink);
}

.act__block {
  margin-top: var(--sp-4);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--line);
}

.act__label {
  display: block;
  margin: var(--sp-4) 0 var(--sp-1);
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-wide);
  color: var(--ink-muted);
}

.act__kv {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--sp-2) var(--sp-4);
  margin: var(--sp-4) 0 0;
  font-size: var(--fs-sm);
}

.act__kv dt {
  color: var(--ink-muted);
}

.act__kv dd {
  margin: 0;
}

.act__withdraw {
  margin-top: var(--sp-2);
}

.act :deep(.c-note) {
  margin-top: var(--sp-4);
}
</style>
