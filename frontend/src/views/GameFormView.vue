<script setup lang="ts">
/** 放团 `/games/new` 与改团 `/games/:id/edit`（同一张表，按有没有 `:id` 切换）。 */
import { computed, onMounted, ref, useId, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import BtnLink from '../components/BtnLink.vue'
import CButton from '../components/CButton.vue'
import CCard from '../components/CCard.vue'
import CChip from '../components/CChip.vue'
import CNotice from '../components/CNotice.vue'
import FormField from '../components/FormField.vue'
import LoadState from '../components/LoadState.vue'
import PageHead from '../components/PageHead.vue'
import { ApiError } from '../api/http'
import { errorText } from '../lib/api-error'
import {
  createGame,
  fetchGame,
  fetchGames,
  fetchRoster,
  fetchTags,
  LEVEL_OPTIONS,
  updateGame,
  type GameListItem,
  type GameMode,
  type GameTag,
  type GameWrite,
  type SignupMode,
} from '../api/games'
import { formatDateTime, fromLocalInput, toLocalInput } from '../lib/datetime'
import { useSiteStore } from '../stores/site'
import { useAuthStore } from '../stores/auth'

/** 规则下拉里「其他（自己填）」那一项的值；只活在表单里，不会提交给后端。 */
const RULE_OTHER = '__custom__'
/** 后端 `Game.title` 的 `max_length`（`apps/games/models.py:123`）。 */
const TITLE_MAX = 80
/** 后端 `TAG_MAX_LENGTH`（`apps/games/serializers.py:33`）。 */
const TAG_MAX = 30
/** 公告正文与开团需求的上限：后端 `GameWriteSerializer` 的 `announcement` / `requirements` */
const LONG_TEXT_MAX = 20000

const route = useRoute()
const router = useRouter()
const site = useSiteStore()
const auth = useAuthStore()
const { config } = storeToRefs(site)
const { user, isGm, authenticated } = storeToRefs(auth)

const editingId = computed(() => (route.params.id ? String(route.params.id) : ''))
const isEditing = computed(() => Boolean(editingId.value))

const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const formError = ref('')
const fieldErrors = ref<Record<string, string>>({})

// —— 表单字段 ——
const title = ref('')
const announcement = ref('')
const requirements = ref('')
/** 规则下拉的选中值：预设名，或 `RULE_OTHER`。 */
const rulePick = ref('')
/** 选了「其他」时自己填的规则名。 */
const ruleCustom = ref('')
const startAt = ref('')
const mode = ref<GameMode>('offline')
const location = ref('')
const tagList = ref<string[]>([])
const tagInput = ref('')
const minPlayers = ref('3')
const maxPlayers = ref('5')
const signupMode = ref<SignupMode>('first_come')
/** 留空或 0 = 不设这道门槛（与 v2 稿口径一致，提交时转成 null）。 */
const minPlayCount = ref('')
/** 空串 = 不设这道门槛。 */
const minLevel = ref('')
const requiresCard = ref(true)
const cardDeadline = ref('')
const mutualReview = ref(false)
const campaignPrev = ref<number | ''>('')
const restrictToPrev = ref(false)

const presetTags = ref<GameTag[]>([])
const myGames = ref<GameListItem[]>([])
/** 改团时：本团已经有人报过名了吗（评价互见开关的冻结判据）。 */
const mutualFrozen = ref(false)
/** 名单没拉到时不敢断言冻没冻，开关照常可点，后端会用 `mutual_review_frozen` 兜住。 */
const mutualFreezeKnown = ref(false)

const rulePresets = computed(() => config.value.rule_system_presets ?? [])
/** 真正提交的规则名。 */
const ruleSystem = computed(() =>
  rulePick.value === RULE_OTHER ? ruleCustom.value.trim() : rulePick.value,
)
/** 截止时间留空就跟开团时间走（与后端默认一致）。 */
const effectiveDeadline = computed(() => cardDeadline.value || startAt.value)
/** 交卡截止没被手动动过时，跟着开团时间走（v2 稿的 `deadlineTouched`）。 */
const deadlineTouched = ref(false)

const SIGNUP_MODES: { value: SignupMode; label: string; hint: string }[] = [
  // label 照抄后端 `SIGNUP_MODE_CHOICES`（apps/games/models.py:42），与团卡上的
  // `signup_mode_display` 一字不差；表单里拿不到实例，只能用这份常量。
  {
    value: 'first_come',
    label: '先到先得',
    hint: '只要人数没有达到上限，玩家就可以直接报名；如果本团需要交卡，玩家提交角色卡后即为成功报团。',
  },
  {
    value: 'pool_review',
    label: 'PL 池 + 人工审核',
    hint: '所有报名会先进入候选名单，由你逐一决定通过或拒绝。拒绝报名或将玩家移出名单时，都必须填写理由。',
  },
]

const signupHint = computed(
  () => SIGNUP_MODES.find((m) => m.value === signupMode.value)?.hint ?? '',
)

// 自定义字段（textarea / select / chip 组）自己管 id，label 与错误才串得起来
const idAnnouncement = useId()
const idRequirements = useId()
const idRule = useId()
const idRuleCustom = useId()
const idTagInput = useId()
const idLocation = useId()
const idSignup = useId()
const idPlayCount = useId()
const idLevel = useId()
const idDeadline = useId()
const idPrev = useId()

onMounted(async () => {
  await Promise.all([site.load(), auth.refresh()])
  try {
    // 只摆**站级预设**标签（战役 / 西征）。全站标签是自由创建的，全列出来会随时间越积越长，
    // 还会把一次性的测试标签摆在每个 GM 面前；其余标签走下面那格自己填（重名会合并到同一个标签）。
    presetTags.value = (await fetchTags()).results.filter((t) => t.is_preset)
  } catch {
    presetTags.value = [] // 标签清单拉不到就只能自己填，不挡表单
  }
  if (user.value) {
    try {
      // 战役续团的候选：自己开过的团（后端还会再校验一次归属）
      myGames.value = (await fetchGames({ gm: user.value.id, page_size: 100 })).results
    } catch {
      myGames.value = []
    }
  }
  if (isEditing.value) {
    try {
      const game = await fetchGame(editingId.value)
      title.value = game.title
      announcement.value = game.announcement
      requirements.value = game.requirements
      if (game.rule_system && rulePresets.value.includes(game.rule_system)) {
        rulePick.value = game.rule_system
      } else if (game.rule_system) {
        rulePick.value = RULE_OTHER
        ruleCustom.value = game.rule_system
      }
      startAt.value = toLocalInput(game.start_at)
      mode.value = game.mode
      location.value = game.location
      tagList.value = [...game.tags]
      minPlayers.value = String(game.min_players)
      maxPlayers.value = String(game.max_players)
      signupMode.value = game.signup_mode
      minPlayCount.value = game.min_play_count === null ? '' : String(game.min_play_count)
      minLevel.value = game.min_level
      requiresCard.value = game.requires_card
      cardDeadline.value = toLocalInput(game.card_deadline)
      deadlineTouched.value = true // 已存在的截止时间不该被开团时间覆盖
      mutualReview.value = game.mutual_review
      campaignPrev.value = game.campaign_prev?.id ?? ''
      restrictToPrev.value = game.restrict_to_prev_members
      await loadFreeze()
    } catch (e) {
      loadError.value = errorText(e, '本团的公告暂时无法读取，请刷新后重试。')
    }
  }
  loading.value = false
})

/**
 * 冻结判据要的是「有没有任何一条报名」，而列表/详情只给 `occupied_seats`
 * （不含已退出/被拒的人），拿它当判据会漏判。GM 名单接口给的是全量报名，正好对得上。
 */
async function loadFreeze(): Promise<void> {
  try {
    const roster = await fetchRoster(editingId.value)
    mutualFrozen.value = roster.is_gm && roster.results.length > 0
    mutualFreezeKnown.value = roster.is_gm
  } catch {
    mutualFrozen.value = false
    mutualFreezeKnown.value = false
  }
}

// 截止时间没被动过就跟着开团时间走（v2 game-new.html 的同名行为）
watch(startAt, (value) => {
  if (!deadlineTouched.value) cardDeadline.value = value
})

function addTag(name: string): void {
  const cleaned = name.trim()
  if (!cleaned) return
  if (cleaned.length > TAG_MAX) {
    formError.value = '单个标签最多 ' + TAG_MAX + ' 个字。'
    return
  }
  if (tagList.value.includes(cleaned)) {
    tagInput.value = ''
    return
  }
  if (tagList.value.length >= 10) {
    formError.value = '一个团最多 10 个标签。'
    return
  }
  tagList.value.push(cleaned)
  tagInput.value = ''
}

function dropTag(name: string): void {
  tagList.value = tagList.value.filter((item) => item !== name)
}

function toggleTag(name: string): void {
  if (tagList.value.includes(name)) dropTag(name)
  else addTag(name)
}

/** 前端先校验一道，省一次失败往返；后端 services 仍会再校验同样的规则。 */
function validate(): boolean {
  const errors: Record<string, string> = {}
  if (!title.value.trim()) errors.title = '标题不能为空。'
  if (rulePick.value === RULE_OTHER && !ruleCustom.value.trim()) {
    errors.rule_system = '选择「其他」时须填写规则名称。'
  }
  if (!startAt.value) errors.start_at = '请填写预计开团时间。'
  const min = Number(minPlayers.value)
  const max = Number(maxPlayers.value)
  if (!Number.isInteger(min) || min < 1) errors.min_players = '最少人数至少 1'
  if (!Number.isInteger(max) || max < 1) errors.max_players = '最多人数至少 1'
  if (Number.isInteger(min) && Number.isInteger(max) && min > max) {
    errors.max_players = '最多人数不能小于最少人数。'
  }
  if (startAt.value && effectiveDeadline.value) {
    if (new Date(effectiveDeadline.value).getTime() > new Date(startAt.value).getTime()) {
      errors.card_deadline = '交卡截止不得晚于开团时间。'
    }
  }
  if (minPlayCount.value !== '') {
    const n = Number(minPlayCount.value)
    if (!Number.isInteger(n) || n < 0) errors.min_play_count = '须填写不小于 0 的整数。'
  }
  fieldErrors.value = errors
  return Object.keys(errors).length === 0
}

/** 后端整体错误码里有几个其实指向某个字段，落到字段上更好改。 */
const CODE_TO_FIELD: Record<string, string> = {
  invalid_player_range: 'max_players',
  card_deadline_after_start: 'card_deadline',
}

function applyApiError(e: unknown): void {
  if (!(e instanceof ApiError)) {
    formError.value = '保存失败，请稍后再试。'
    return
  }
  const fields = e.fieldErrors()
  for (const item of e.errors) {
    const target = CODE_TO_FIELD[item.code]
    if (target && !fields[target]) fields[target] = item.message
  }
  fieldErrors.value = fields
  const general = e.formMessage()
  formError.value =
    general || (Object.keys(fields).length ? '表单中有若干项需要修改。' : errorText(e, '保存失败，请稍后再试。'))
}

/** 表单里**有红字落点**的字段：出错时那一格自己会显示。 */
const PLACED_FIELDS = new Set([
  'title',
  'rule_system',
  'tags',
  'announcement',
  'requirements',
  'campaign_prev',
  'start_at',
  'mode',
  'location',
  'min_players',
  'max_players',
  'signup_mode',
  'min_play_count',
  'min_level',
  'card_deadline',
])

/** 没有落点的那几个字段的中文名（界面上没有可指的控件，至少要说清是哪一项）。 */
const FIELD_LABELS: Record<string, string> = {
  requires_card: '需要交角色卡',
  mutual_review: '评价互见',
  restrict_to_prev_members: '只让前一个团的成员报名',
}

const strayErrors = computed(() =>
  Object.entries(fieldErrors.value)
    .filter(([key]) => !PLACED_FIELDS.has(key))
    .map(([key, message]) => (FIELD_LABELS[key] ?? key) + '：' + message),
)

function buildPayload(): GameWrite {
  return {
    title: title.value.trim(),
    announcement: announcement.value,
    rule_system: ruleSystem.value,
    start_at: fromLocalInput(startAt.value),
    mode: mode.value,
    location: location.value.trim(),
    requirements: requirements.value,
    tags: tagList.value,
    min_players: Number(minPlayers.value),
    max_players: Number(maxPlayers.value),
    signup_mode: signupMode.value,
    min_play_count: minPlayCount.value === '' ? null : Number(minPlayCount.value) || null,
    min_level: minLevel.value,
    requires_card: requiresCard.value,
    card_deadline: fromLocalInput(effectiveDeadline.value),
    mutual_review: mutualReview.value,
    campaign_prev: campaignPrev.value === '' ? null : Number(campaignPrev.value),
    restrict_to_prev_members: campaignPrev.value === '' ? false : restrictToPrev.value,
  }
}

async function onSubmit(): Promise<void> {
  if (saving.value) return
  formError.value = ''
  if (!validate()) return
  saving.value = true
  try {
    const payload = buildPayload()
    const game = isEditing.value
      ? await updateGame(editingId.value, payload)
      : await createGame(payload)
    await router.push('/games/' + game.id)
  } catch (e) {
    applyApiError(e)
  } finally {
    saving.value = false
  }
}

// —— 右栏「发布前核对」——
const gateSummary = computed(() => {
  const parts: string[] = []
  const n = Number(minPlayCount.value)
  if (minPlayCount.value !== '' && Number.isInteger(n) && n > 0) parts.push('团次数 ≥ ' + n)
  const level = LEVEL_OPTIONS.find((l) => l.value === minLevel.value)
  if (level) parts.push(level.label + '及以上')
  return parts.length ? parts.join(' · ') : '无门槛'
})

const summary = computed<{ k: string; v: string }[]>(() => {
  const rows: { k: string; v: string }[] = [
    { k: '团名', v: title.value.trim() || '未填写' },
    { k: '规则', v: ruleSystem.value || '未填写' },
    { k: '标签', v: tagList.value.join(' · ') || '没有标签' },
    { k: '开团', v: startAt.value ? formatDateTime(fromLocalInput(startAt.value)) : '未填写' },
    {
      k: '形式',
      v: mode.value === 'offline' ? '线下 · ' + (location.value.trim() || '地点未填') : '线上',
    },
    { k: '人数', v: (minPlayers.value || '?') + ' – ' + (maxPlayers.value || '?') + ' 人' },
    { k: '报名', v: SIGNUP_MODES.find((m) => m.value === signupMode.value)?.label ?? '' },
    { k: '门槛', v: gateSummary.value },
    {
      k: '角色卡',
      v: requiresCard.value
        ? '需交卡 · 截止 ' +
          (effectiveDeadline.value ? formatDateTime(fromLocalInput(effectiveDeadline.value)) : '未填写')
        : '不需要',
    },
    {
      k: '评价互见',
      v: mutualReview.value ? '开启（有人报名后即冻结）' : '关闭（默认）',
    },
  ]
  if (campaignPrev.value !== '') {
    const prev = myGames.value.find((g) => g.id === Number(campaignPrev.value))
    rows.splice(3, 0, {
      k: '前一个团',
      v: (prev?.title ?? '已选') + (restrictToPrev.value ? ' · 只限前团成员' : ''),
    })
  }
  return rows
})

const backTo = computed(() => (isEditing.value ? '/games/' + editingId.value : '/recruit'))
</script>

<template>
  <div class="gf u-rise">
    <RouterLink class="c-back" :to="backTo">
      <AppIcon name="back" :size="16" />
      {{ isEditing ? '返回团详情' : '返回招募列表' }}
    </RouterLink>

    <PageHead
      :eyebrow="isEditing ? 'Edit a game · 改团' : 'Host a game · 放团'"
      :title="isEditing ? '改团' : '放团'"
      :lead="
        isEditing
          ? '保存后修改立即生效。开团时间、人数和报名门槛修改后，招募列表中显示的信息会同步更新；已经报名的玩家也会按修改后的条件继续参团。'
          : '请把开团时间、规则和参团要求写清楚，方便玩家判断自己是否适合报名。发布之后，团的公告可以随时修改。'
      "
    />

    <LoadState :loading="loading" :error="loadError">
      <!-- ============ 非 GM：v2 的说明块（表单不渲染） ============ -->
      <CCard v-if="!isGm" class="locked">
        <h2 class="locked__title u-h-card">放团需要 GM 身份</h2>
        <p class="locked__text">
          只有拥有 GM 身份的账号才能使用本页面。本站没有单独的「GM 账号」：GM 是普通账号可以获得的一种身份，
          获得后你仍然使用原来的账号，只是会多出一张 GM 卡，并可以使用放团功能。
        </p>
        <ol class="locked__steps">
          <li>注册账号并验证邮箱，先以玩家身份报名参团；</li>
          <li>
            以玩家身份参加的团累计结团 {{ config.gm_auto_promote_threshold }} 次后，会自动获得 GM
            身份（所需次数由站主设置）；
          </li>
          <li>如果希望尽快获得 GM 身份，可以在账号设置中提交申请，并说明你打算开什么样的团。</li>
        </ol>
        <p class="u-small locked__note">
          如果你已经拥有 GM 身份却仍然看到这段提示，可能是登录状态没有及时更新，请刷新页面或重新登录后再试。
        </p>
        <div class="c-btn-row">
          <BtnLink v-if="authenticated === false" to="/auth/signup">注册账号 →</BtnLink>
          <BtnLink v-else to="/me/account">前往申请 GM 身份 →</BtnLink>
          <RouterLink class="c-textlink" to="/recruit">浏览正在招募的团 →</RouterLink>
          <RouterLink class="c-textlink" to="/guide">阅读新人指南 →</RouterLink>
        </div>
      </CCard>

      <!-- ============ GM：放团 / 改团表单 ============ -->
      <form v-else class="layout" novalidate @submit.prevent="onSubmit">
        <div class="layout__main">
          <CNotice v-if="formError || strayErrors.length" tone="danger" class="gf__err">
            {{ formError || '表单中有几项内容需要修改，请查看下方标出的提示。' }}
            <!-- 没有字段落点的错误就摊在这里，一条一行 -->
            <ul v-if="strayErrors.length" class="gf__errlist">
              <li v-for="msg in strayErrors" :key="msg">{{ msg }}</li>
            </ul>
          </CNotice>

          <!-- 01 基本 -->
          <section class="fs">
            <div class="fs__head">
              <p class="u-kicker">01</p>
              <h2 class="fs__title u-h-card">基本信息</h2>
              <p class="u-small fs__note">
                团名会显示在招募列表和每位报名者收到的通知中，请尽量写得具体。规则系统是全站用来分类筛选团的依据，
                如果选错，其他玩家按规则筛选时将找不到你的团。
              </p>
            </div>

            <FormField
              v-model="title"
              label="团名"
              required
              :maxlength="TITLE_MAX"
              placeholder="例如：雾港来信 · 番外：档案室的三小时"
              :hint="TITLE_MAX + ' 字以内。'"
              :error="fieldErrors.title"
            />

            <div class="c-field">
              <div class="c-field__head">
                <label class="c-field__label" :for="idRule">规则系统</label>
              </div>
              <select :id="idRule" v-model="rulePick" class="c-select">
                <option value="">暂不选择</option>
                <option v-for="name in rulePresets" :key="name" :value="name">{{ name }}</option>
                <option :value="RULE_OTHER">其他（手动填写）</option>
              </select>
              <p class="c-field__hint">
                列表中是站主预先设置的规则系统。如果你使用的规则不在列表中，请选择「其他」并手动填写规则名称。
              </p>
            </div>

            <div v-if="rulePick === RULE_OTHER" class="c-field">
              <div class="c-field__head">
                <label class="c-field__label" :for="idRuleCustom">自定义规则名</label>
              </div>
              <input
                :id="idRuleCustom"
                v-model="ruleCustom"
                class="c-input"
                type="text"
                maxlength="30"
                placeholder="例如：GURPS / 无限恐怖 / 自制规则"
                :aria-invalid="fieldErrors.rule_system ? 'true' : undefined"
                :aria-describedby="
                  fieldErrors.rule_system ? idRuleCustom + '-err' : idRuleCustom + '-hint'
                "
              />
              <p :id="idRuleCustom + '-hint'" class="c-field__hint">
                手动填写的规则没有站主设置的专属背景图，招募卡片和团详情页会使用默认背景图。在招募页按规则筛选时，本团会归入「其他」一类。
              </p>
              <p v-if="fieldErrors.rule_system" :id="idRuleCustom + '-err'" class="c-field__error">
                {{ fieldErrors.rule_system }}
              </p>
            </div>

            <div class="c-field">
              <div class="c-field__head">
                <span class="c-field__label">标签</span>
              </div>
              <div v-if="presetTags.length" class="c-chips" role="group" aria-label="选择标签">
                <CChip
                  v-for="item in presetTags"
                  :key="item.id"
                  :active="tagList.includes(item.name)"
                  @click="toggleTag(item.name)"
                >
                  {{ item.name }}
                </CChip>
              </div>
              <div class="tagadd">
                <label class="u-hidden" :for="idTagInput">自定义标签</label>
                <input
                  :id="idTagInput"
                  v-model="tagInput"
                  class="c-input"
                  type="text"
                  :maxlength="TAG_MAX"
                  placeholder="输入一个新标签，例如「新人友好」"
                  :aria-invalid="fieldErrors.tags ? 'true' : undefined"
                  :aria-describedby="idTagInput + '-hint'"
                  @keydown.enter.prevent="addTag(tagInput)"
                />
                <CButton variant="ghost" @click="addTag(tagInput)">添加标签</CButton>
              </div>
              <div v-if="tagList.length" class="chosen">
                <button
                  v-for="name in tagList"
                  :key="name"
                  class="c-tag chosen__item"
                  type="button"
                  :aria-label="'移除标签 ' + name"
                  @click="dropTag(name)"
                >
                  {{ name }} ×
                </button>
              </div>
              <p :id="idTagInput + '-hint'" class="c-field__hint">
                输入标签后按回车键，或点击「添加标签」即可添加。每个团最多 10 个标签，每个标签不超过 {{ TAG_MAX }} 个字。
                标签在全站通用，与已有标签同名时会自动归为同一个标签。
              </p>
              <p v-if="fieldErrors.tags" class="c-field__error">{{ fieldErrors.tags }}</p>
            </div>

            <!-- 战役续团：v2 稿把它藏在「选了战役标签」之后，这里常驻显示 ——
                 后端并不要求战役标签，藏起来等于把一个真字段变成猜谜（改团时尤其）。 -->
            <div class="sub">
              <p class="u-kicker sub__k">战役续团</p>
              <div class="c-field">
                <div class="c-field__head">
                  <label class="c-field__label" :for="idPrev">接续哪一个团</label>
                </div>
                <select :id="idPrev" v-model="campaignPrev" class="c-select">
                  <option value="">不接续任何团（独立的单团，或战役的第一个团）</option>
                  <option v-for="item in myGames" :key="item.id" :value="item.id">
                    {{ item.title }}
                  </option>
                </select>
                <p class="c-field__hint">只能接续你本人主持过的团。</p>
                <p v-if="fieldErrors.campaign_prev" class="c-field__error">
                  {{ fieldErrors.campaign_prev }}
                </p>
              </div>
              <label v-if="campaignPrev !== ''" class="switch">
                <input v-model="restrictToPrev" type="checkbox" />
                <span>
                  <b>只允许上一个团的成员报名</b>
                  <span class="u-small">
                    开启后，不在上一个团正式名单中的玩家将无法报名本团；关闭时，所有符合报名门槛的玩家都可以报名。
                  </span>
                </span>
              </label>
            </div>
          </section>

          <!-- 02 公告正文 -->
          <section class="fs">
            <div class="fs__head">
              <p class="u-kicker">02</p>
              <h2 class="fs__title u-h-card">公告正文</h2>
              <p class="u-small fs__note">
                玩家决定是否报名时，主要依据这段公告和下方的参团需求。建议写清楚：故事背景、玩家需要准备什么、
                使用的规则版本、预计时长，以及可能让人不适的内容提醒。
              </p>
            </div>
            <div class="c-field">
              <div class="c-field__head">
                <label class="c-field__label" :for="idAnnouncement">正文</label>
              </div>
              <textarea
                :id="idAnnouncement"
                v-model="announcement"
                class="c-textarea"
                rows="12"
                :maxlength="LONG_TEXT_MAX"
                placeholder="可以使用简单格式：行首写 ## 加空格表示小标题，- 加空格表示列表，用 **两个星号** 包住文字表示加粗，行首写 &gt; 表示引用。"
                :aria-invalid="fieldErrors.announcement ? 'true' : undefined"
                :aria-describedby="
                  fieldErrors.announcement ? idAnnouncement + '-err' : idAnnouncement + '-hint'
                "
              ></textarea>
              <p :id="idAnnouncement + '-hint'" class="c-field__hint">
                发布后，这段公告会显示在团详情页中。修改公告后无需重新审核，保存即可生效。
                最多 {{ LONG_TEXT_MAX }} 字（当前已写 {{ announcement.length }} 字）。
              </p>
              <p v-if="fieldErrors.announcement" :id="idAnnouncement + '-err'" class="c-field__error">
                {{ fieldErrors.announcement }}
              </p>
            </div>
          </section>

          <!-- 业务信息 -->
          <section class="fs">
            <div class="fs__head">
              <p class="u-kicker">03</p>
              <h2 class="fs__title u-h-card">开团需求</h2>
              <p class="u-small fs__note">
                请在这里列出玩家报名前需要自行确认的具体要求。与上面的故事背景分开填写，方便玩家快速看完。
              </p>
            </div>
            <div class="c-field">
              <div class="c-field__head">
                <label class="c-field__label" :for="idRequirements">需求</label>
              </div>
              <textarea
                :id="idRequirements"
                v-model="requirements"
                class="c-textarea"
                rows="5"
                :maxlength="LONG_TEXT_MAX"
                placeholder="例如：能全程参加 4 小时，不中途离席；能接受恐怖与血腥描写；线下参团请自带骰子；开团前读完公告中的背景设定。"
                :aria-invalid="fieldErrors.requirements ? 'true' : undefined"
                :aria-describedby="
                  fieldErrors.requirements ? idRequirements + '-err' : idRequirements + '-hint'
                "
              ></textarea>
              <p :id="idRequirements + '-hint'" class="c-field__hint">
                这段内容会单独显示在团详情页中。下方设置的报名门槛（团次数、赞级别）由系统自动检查，
                而写在这里的要求需要玩家自行对照确认，系统不会检查。最多 {{ LONG_TEXT_MAX }} 字。
              </p>
              <p v-if="fieldErrors.requirements" :id="idRequirements + '-err'" class="c-field__error">
                {{ fieldErrors.requirements }}
              </p>
            </div>
          </section>

          <!-- 04 时间与形式 -->
          <section class="fs">
            <div class="fs__head">
              <p class="u-kicker">04</p>
              <h2 class="fs__title u-h-card">时间与形式</h2>
              <p class="u-small fs__note">
                开团时间是本站各项时间安排的依据：交卡提醒、开团提醒和自动结团，都根据开团时间计算。
              </p>
            </div>
            <FormField
              v-model="startAt"
              label="预计开团时间"
              type="datetime-local"
              required
              hint="请精确到分钟。到达开团时间后，本团会自动变为「进行中」。"
              :error="fieldErrors.start_at"
            />
            <div class="c-field">
              <div class="c-field__head">
                <span class="c-field__label">线上 / 线下</span>
              </div>
              <div class="c-chips" role="group" aria-label="线上或线下">
                <CChip :active="mode === 'online'" @click="mode = 'online'">线上</CChip>
                <CChip :active="mode === 'offline'" @click="mode = 'offline'">线下</CChip>
              </div>
              <p v-if="fieldErrors.mode" class="c-field__error">{{ fieldErrors.mode }}</p>
            </div>
            <div class="c-field">
              <div class="c-field__head">
                <label class="c-field__label" :for="idLocation">
                  {{ mode === 'offline' ? '地点' : '平台 / 频道' }}
                </label>
              </div>
              <input
                :id="idLocation"
                v-model="location"
                class="c-input"
                type="text"
                maxlength="120"
                :placeholder="
                  mode === 'offline'
                    ? '例如：文创园 3 号楼 2 层 · 活动室 B'
                    : '例如：Discord「雾港」语音房 / 腾讯会议'
                "
                :aria-describedby="idLocation + '-hint'"
              />
              <p :id="idLocation + '-hint'" class="c-field__hint">
                {{
                  mode === 'offline'
                    ? '这里填写的内容所有人都能看到，请不要填写私人住址或门牌号。具体位置请在开团前私下告知正式名单中的成员。'
                    : '这里填写的内容所有人都能看到，请不要在此填写房间密码等不宜公开的信息。'
                }}
              </p>
              <p v-if="fieldErrors.location" class="c-field__error">{{ fieldErrors.location }}</p>
            </div>
          </section>

          <!-- 05 人数与报名方式 -->
          <section class="fs">
            <div class="fs__head">
              <p class="u-kicker">05</p>
              <h2 class="fs__title u-h-card">人数与报名方式</h2>
              <p class="u-small fs__note">
                已占位人数包括状态为「待交卡」「已交卡待审」和「成功报团」的玩家。占位人数达到上限后会自动停止接受报名，
                本站不设候补名单。如果想接收更多玩家，需要在团详情的「管理」标签中提高人数上限。
              </p>
            </div>
            <div class="pair">
              <FormField
                v-model="minPlayers"
                label="人数下限"
                type="number"
                required
                hint="报名人数不足下限时，由你决定是否照常开团，系统不会自动取消本团。"
                :error="fieldErrors.min_players"
              />
              <FormField
                v-model="maxPlayers"
                label="人数上限"
                type="number"
                required
                hint="占位人数达到上限后，自动停止接受报名。"
                :error="fieldErrors.max_players"
              />
            </div>
            <div class="c-field">
              <div class="c-field__head">
                <span :id="idSignup" class="c-field__label">报名模式</span>
              </div>
              <div class="c-chips" role="group" :aria-labelledby="idSignup">
                <CChip
                  v-for="item in SIGNUP_MODES"
                  :key="item.value"
                  :active="signupMode === item.value"
                  @click="signupMode = item.value"
                >
                  {{ item.label }}
                </CChip>
              </div>
              <p class="c-field__hint">{{ signupHint }}</p>
              <p v-if="fieldErrors.signup_mode" class="c-field__error">
                {{ fieldErrors.signup_mode }}
              </p>
            </div>
          </section>

          <!-- 06 报名门槛 -->
          <section class="fs">
            <div class="fs__head">
              <p class="u-kicker">06</p>
              <h2 class="fs__title u-h-card">报名门槛</h2>
              <p class="u-small fs__note">
                以下两个门槛互相独立，可以只设置其中一个，也可以都不设置。系统会根据报名者玩家卡上显示的数据判断是否达到门槛。
              </p>
            </div>
            <div class="pair">
              <div class="c-field">
                <div class="c-field__head">
                  <label class="c-field__label" :for="idPlayCount">最少团次数</label>
                </div>
                <input
                  :id="idPlayCount"
                  v-model="minPlayCount"
                  class="c-input"
                  type="number"
                  min="0"
                  :aria-invalid="fieldErrors.min_play_count ? 'true' : undefined"
                  :aria-describedby="
                    fieldErrors.min_play_count ? idPlayCount + '-err' : idPlayCount + '-hint'
                  "
                />
                <p :id="idPlayCount + '-hint'" class="c-field__hint">
                  指报名者以玩家身份参加并已结团的团数。填写 0 或留空，表示不设置这项门槛。
                </p>
                <p v-if="fieldErrors.min_play_count" :id="idPlayCount + '-err'" class="c-field__error">
                  {{ fieldErrors.min_play_count }}
                </p>
              </div>
              <div class="c-field">
                <div class="c-field__head">
                  <label class="c-field__label" :for="idLevel">最低赞级别</label>
                </div>
                <select
                  :id="idLevel"
                  v-model="minLevel"
                  class="c-select"
                  :disabled="!config.like_feature_enabled"
                  :aria-describedby="idLevel + '-hint'"
                >
                  <option value="">不设置此项门槛</option>
                  <option v-for="item in LEVEL_OPTIONS" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </option>
                </select>
                <p :id="idLevel + '-hint'" class="c-field__hint">
                  {{
                    config.like_feature_enabled
                      ? '请慎重设置此项门槛；如果没有明确的理由，建议保持「不设置此项门槛」。选择某一档，表示只有玩家侧赞级别达到这一档或更高的玩家才能报名。设置后，以下两类玩家都将无法报名本团：一是赞级别低于这一档的玩家；二是被评价次数（含「无评价」）还不满 ' +
                        config.like_level_publish_threshold +
                        ' 次、赞级别尚未公布的玩家，这包括几乎所有刚加入本站的玩家和不常参团的玩家。赞级别只反映过去同团成员给出的匿名评价，评价数量不多时容易受个别评价影响，不一定代表这位玩家的真实表现。此项门槛只在玩家报名时检查，已经报名的玩家不受影响。'
                      : '站主目前关闭了赞功能，因此赞级别门槛暂时不会生效。'
                  }}
                </p>
                <p v-if="fieldErrors.min_level" class="c-field__error">
                  {{ fieldErrors.min_level }}
                </p>
              </div>
            </div>
          </section>

          <!-- 07 角色卡 -->
          <section class="fs">
            <div class="fs__head">
              <p class="u-kicker">07</p>
              <h2 class="fs__title u-h-card">角色卡</h2>
              <p class="u-small fs__note">
                如果本团需要交卡，报名者须在交卡截止时间前提交角色卡。没有按时交卡的报名会被标记为「未交卡」，
                之后由你决定是否仍让其参团，或将其移出名单。
              </p>
            </div>
            <label class="switch">
              <input v-model="requiresCard" type="checkbox" />
              <span>
                <b>需要交角色卡</b>
                <span class="u-small">
                  角色卡由玩家自己提交，你也可以代为上传（代传的角色卡仍归该玩家所有，默认不公开）。
                  玩家提交的角色卡只有本团 GM 可以下载。
                </span>
              </span>
            </label>
            <div v-if="requiresCard" class="c-field">
              <div class="c-field__head">
                <label class="c-field__label" :for="idDeadline">交卡截止</label>
              </div>
              <input
                :id="idDeadline"
                v-model="cardDeadline"
                class="c-input"
                type="datetime-local"
                :aria-invalid="fieldErrors.card_deadline ? 'true' : undefined"
                :aria-describedby="
                  fieldErrors.card_deadline ? idDeadline + '-err' : idDeadline + '-hint'
                "
                @input="deadlineTouched = true"
              />
              <p :id="idDeadline + '-hint'" class="c-field__hint">
                留空表示交卡截止时间与开团时间相同。截止时间可以早于开团时间，<strong>但不能晚于开团时间</strong>。
                这个时间同时决定玩家如何退出：截止前玩家可以直接退出，截止后退出需要由你确认。
              </p>
              <p v-if="fieldErrors.card_deadline" :id="idDeadline + '-err'" class="c-field__error">
                {{ fieldErrors.card_deadline }}
              </p>
            </div>
            <p v-else class="c-field__hint">本团不要求提交角色卡，玩家报名通过后即为成功报团。</p>
          </section>

          <!-- 08 评价互见 -->
          <section class="fs">
            <div class="fs__head">
              <p class="u-kicker">08</p>
              <h2 class="fs__title u-h-card">评价互见</h2>
              <p class="u-small fs__note">
                结团后，同团成员之间会互相进行一次匿名评价。默认情况下，每条评价的内容只有被评价的人自己能看到。
              </p>
            </div>
            <label class="switch" :class="{ 'switch--off': mutualFrozen }">
              <input v-model="mutualReview" type="checkbox" :disabled="mutualFrozen" />
              <span>
                <b>开启评价互见：同团成员可以看到彼此收到的评价</b>
                <span class="u-small">
                  开启后，本团成员可以看到其他成员收到的评价内容（仍然不会显示是谁写的）。
                  在人数较少的团里，成员有可能通过排除法推测出评价人。开启此项即表示本团接受这一点。
                </span>
              </span>
            </label>
            <CNotice v-if="mutualFrozen" tone="warn" title="评价互见设置已无法修改">
              本团已经有人报名。报名者在报名时已经按当时的设置表示同意，中途修改相当于替他们改变了决定，
              因此这项设置不能再修改。
            </CNotice>
            <CNotice v-else-if="isEditing && !mutualFreezeKnown" tone="warn">
              系统暂时无法确认本团是否已有人报名。如果已经有人报名，保存时这项修改不会生效，页面会给出提示。
            </CNotice>
            <CNotice v-else tone="brand">
              本团收到第一条报名后，这项设置将无法再修改。请在发布前考虑清楚；发布后、有人报名之前仍然可以修改。
            </CNotice>
          </section>

          <div class="actions">
            <CButton type="submit" :disabled="saving">
              {{ saving ? '保存中…' : isEditing ? '保存修改' : '发布招募 →' }}
            </CButton>
            <RouterLink class="c-btn c-btn--ghost" :to="backTo">取消</RouterLink>
            <span class="u-small actions__note">
              本站不提供草稿功能：{{ isEditing ? '保存' : '发布' }}后，本团会立即显示在招募列表中。
              如果内容还没写完、暂时不想公开，请不要提交。
            </span>
          </div>
        </div>

        <!-- 右栏：发布前核对 -->
        <aside class="side" aria-label="发布前核对">
          <CCard class="side__card">
            <h2 class="side__title u-h-card">{{ isEditing ? '保存前核对' : '发布前核对' }}</h2>
            <dl class="side__list">
              <div v-for="row in summary" :key="row.k">
                <dt class="u-kicker">{{ row.k }}</dt>
                <dd>{{ row.v }}</dd>
              </div>
            </dl>
          </CCard>
          <p class="u-small side__note">
            发布后，本团会立即显示在招募列表和首页的「正在招募」栏目中。开团时间前 24 小时，
            系统会向还没有交卡的报名者发送交卡提醒，并向成功报团的成员发送开团提醒。如果开团时间过后你一直没有结团，
            系统会按照本站设定的期限自动为你结团。
          </p>
        </aside>
      </form>
    </LoadState>
  </div>
</template>

<style scoped>
/* ==========================================================================
   非 GM 的说明块（v2 game-new.html .locked .box）
   ========================================================================== */

.locked {
  max-width: 720px;
  border-left: 2px solid var(--brand);
}

.locked__title {
  margin: 0 0 var(--sp-3);
}

.locked__text {
  margin: 0 0 var(--sp-3);
  font-size: var(--fs-md);
  line-height: var(--lh-body);
  color: var(--ink-soft);
}

.locked__steps {
  margin: 0 0 var(--sp-4);
  padding-left: var(--sp-5);
  font-size: var(--fs-md);
  line-height: 2;
  color: var(--ink-soft);
}

.locked__note {
  margin: 0 0 var(--sp-4);
}

/* ==========================================================================
   表单：左主体 + 右核对卡（v2 .form-layout，≥1200 才分栏）
   ========================================================================== */

.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-6);
  align-items: start;
}

.layout__main {
  min-width: 0;
}

.gf__err {
  margin-bottom: var(--sp-5);
}

.gf__errlist {
  margin: var(--sp-2) 0 0;
  padding-left: var(--sp-4);
  line-height: var(--lh-read);
}

.fs {
  padding: var(--sp-6) 0;
  border-top: 1px solid var(--line);
}

.fs:first-of-type {
  padding-top: 0;
  border-top: 0;
}

.fs__head {
  margin-bottom: var(--sp-5);
}

.fs__title {
  margin: var(--sp-2) 0 var(--sp-2);
}

.fs__note {
  margin: 0;
  max-width: 60ch;
  line-height: var(--lh-body);
}

.pair {
  display: grid;
  gap: var(--sp-3);
}

.tagadd {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  align-items: center;
}

/** 业务界面遵循后端权限与隐私约束。 */
.tagadd .c-input {
  flex: 1 1 100%;
}

@media (min-width: 768px) {
  .tagadd .c-input {
    flex: 1 1 14em;
  }
}

.chosen {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
}

.chosen__item {
  display: inline-flex;
  align-items: center;
  min-height: 40px;
  cursor: pointer;
}

/* v2 .sub-block：嵌在一段里的次级设置块 */
.sub {
  margin-top: var(--sp-4);
  padding: var(--sp-4);
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-left: 2px solid var(--line-2);
  border-radius: var(--radius);
}

.sub__k {
  margin: 0 0 var(--sp-3);
}

.sub .c-field:last-child {
  margin-bottom: 0;
}

/* v2 .switch：整块可点的开关行 */
.switch {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
  margin-bottom: var(--sp-4);
  padding: var(--sp-4);
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  cursor: pointer;
}

.switch input {
  flex: none;
  width: 18px;
  height: 18px;
  margin: 2px 0 0;
  accent-color: var(--brand);
}

.switch b {
  display: block;
  margin-bottom: var(--sp-1);
  font-weight: 400;
  font-size: var(--fs-md);
  color: var(--ink);
}

.switch .u-small {
  display: block;
  line-height: var(--lh-body);
}

.switch--off {
  background: var(--bg-2);
  cursor: not-allowed;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3) var(--sp-5);
  margin-top: var(--sp-4);
  padding-top: var(--sp-5);
  border-top: 1px solid var(--line);
}

.actions__note {
  flex: 1 1 18em;
  line-height: var(--lh-body);
}

/* ==========================================================================
   右栏核对卡
   ========================================================================== */

.side {
  display: grid;
  gap: var(--sp-4);
  min-width: 0;
}

.side__title {
  margin: 0 0 var(--sp-4);
}

.side__list {
  display: grid;
  gap: var(--sp-3);
  margin: 0;
}

.side__list dt {
  margin-bottom: var(--sp-1);
}

.side__list dd {
  margin: 0;
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
  color: var(--ink-soft);
  word-break: break-word;
}

.side__note {
  margin: 0;
  line-height: var(--lh-body);
}

@media (min-width: 768px) {
  .pair {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0 var(--sp-5);
  }
}

@media (min-width: 1200px) {
  .layout {
    grid-template-columns: minmax(0, 1fr) 320px;
    gap: var(--sp-8);
  }

  .side {
    position: sticky;
    top: calc(var(--header-h) + var(--sp-5));
  }
}
</style>
