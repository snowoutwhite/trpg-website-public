<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, onMounted, ref, useId, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import BlurStage from '../components/BlurStage.vue'
import BtnLink from '../components/BtnLink.vue'
import CButton from '../components/CButton.vue'
import CCard from '../components/CCard.vue'
import CChip from '../components/CChip.vue'
import CNotice from '../components/CNotice.vue'
import CPill from '../components/CPill.vue'
import FormField from '../components/FormField.vue'
import LoadState from '../components/LoadState.vue'
import PageHead from '../components/PageHead.vue'
import {
  CARD_FILE_EXTENSIONS,
  CARD_FILE_MAX_BYTES,
  checkCardFile,
  createCard,
  fetchMyCards,
  updateCard,
  uploadCardFile,
  type CardStatus,
  type MyCard,
} from '../api/cards'
import { ApiError } from '../api/http'
import { errorText } from '../lib/api-error'
import { cardArt, CARD_STATUS_OPTIONS } from '../lib/card-display'
import { formatDate } from '../lib/datetime'
import { safeNextPath } from '../lib/url-guard'
import { useAuthStore } from '../stores/auth'
import { useHomeStore } from '../stores/home'
import { useSiteStore } from '../stores/site'

/** 规则下拉里「其他（自己填）」那一项的哨兵值（不会与任何预设名撞车）。 */
const RULE_OTHER = '__custom__'
/** 后端 `CharacterCard.name` / `rule_system` 的 max_length。 */
const NAME_MAX = 60
const RULE_MAX = 60
/** 后端 `common/pagination.py:StandardPagination.page_size`。 */
const PAGE_SIZE = 20

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const home = useHomeStore()
const site = useSiteStore()
const { authenticated } = storeToRefs(auth)
const { config } = storeToRefs(site)

const idRule = useId()
const idRuleCustom = useId()
const idFile = useId()

/** 建完卡要回哪里（团详情的「上传新卡并交」）。空串 = 不回跳，留在本页。 */
const nextPath = computed(() => {
  const raw = route.query.next
  return typeof raw === 'string' && raw ? safeNextPath(raw, '') : ''
})

const cards = ref<MyCard[]>([])
const count = ref(0)
const hasNext = ref(false)
const page = ref(1)
const status = ref<CardStatus | ''>('')
const loading = ref(true)
const error = ref('')

// —— 建卡表单 ——
const creating = ref(false)
const submitting = ref(false)
const formError = ref('')
const formNote = ref('')
const fieldErrors = ref<Record<string, string>>({})
const name = ref('')
const rulePick = ref('')
const ruleCustom = ref('')
const isPublic = ref(false)
const file = ref<File | null>(null)
const fileError = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

// —— 行内快捷动作（公开切换 / 撕卡）——
const busyId = ref<number | null>(null)
const confirmTearId = ref<number | null>(null)
const rowError = ref('')

const rulePresets = computed(() => config.value.rule_system_presets ?? [])
const ruleSystem = computed(() =>
  rulePick.value === RULE_OTHER ? ruleCustom.value.trim() : rulePick.value,
)
const accept = computed(() => CARD_FILE_EXTENSIONS.map((e) => '.' + e).join(','))
const maxMb = Math.round(CARD_FILE_MAX_BYTES / 1024 / 1024)
const totalPages = computed(() => Math.max(1, Math.ceil(count.value / PAGE_SIZE)))

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchMyCards({ status: status.value, page: page.value })
    cards.value = data.results
    count.value = data.count
    hasNext.value = Boolean(data.next)
  } catch (e) {
    error.value = errorText(e, '角色卡列表暂时无法读取，请刷新后重试。')
    cards.value = []
    count.value = 0
    hasNext.value = false
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  void site.load()
  void home.load(authenticated.value)
  // 从团页「上传新卡并交」过来的人，落地就该看到表单
  if (nextPath.value) creating.value = true
  await load()
})

watch(status, () => {
  page.value = 1
  void load()
})

function goPage(next: number): void {
  if (next === page.value || next < 1) return
  page.value = next
  void load()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function onPickFile(event: Event): void {
  const input = event.target as HTMLInputElement
  const picked = input.files?.[0] ?? null
  fileError.value = ''
  if (!picked) {
    file.value = null
    return
  }
  // 前端先校验一道，省一次失败往返；服务端仍会读魔数复核（validators.py）
  const problem = checkCardFile(picked)
  if (problem) {
    fileError.value = problem
    file.value = null
    input.value = ''
    return
  }
  file.value = picked
}

function resetForm(): void {
  name.value = ''
  rulePick.value = ''
  ruleCustom.value = ''
  isPublic.value = false
  file.value = null
  fileError.value = ''
  fieldErrors.value = {}
  formError.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

function toggleForm(): void {
  creating.value = !creating.value
  if (!creating.value) resetForm()
}

async function onCreate(): Promise<void> {
  if (submitting.value) return
  formError.value = ''
  formNote.value = ''
  fieldErrors.value = {}
  const errors: Record<string, string> = {}
  if (!name.value.trim()) errors.name = '请为这张卡填写名称。'
  if (rulePick.value === RULE_OTHER && !ruleCustom.value.trim()) {
    errors.rule_system = '选择「其他」时须填写规则名称。'
  }
  if (nextPath.value && !file.value) {
    fileError.value = '用于交卡的角色卡须先有文件，这张卡目前为空。'
  }
  if (Object.keys(errors).length || fileError.value) {
    fieldErrors.value = errors
    return
  }

  submitting.value = true
  let created: MyCard
  try {
    created = await createCard({
      name: name.value.trim(),
      rule_system: ruleSystem.value,
      is_public: isPublic.value,
    })
  } catch (e) {
    if (e instanceof ApiError) {
      fieldErrors.value = e.fieldErrors()
      formError.value = e.formMessage() || errorText(e, '创建失败，请稍后再试。')
    } else {
      formError.value = '创建失败，请稍后再试。'
    }
    submitting.value = false
    return
  }

  // 第二步：文件。失败了卡还在，必须单独说清楚，不能报成「建卡失败」。
  if (file.value) {
    try {
      await uploadCardFile(created.id, file.value)
    } catch (e) {
      submitting.value = false
      creating.value = false
      resetForm()
      await load()
      formError.value =
        '「' +
        created.name +
        '」已创建，但文件上传失败（' +
        errorText(e, '文件上传失败，请稍后再试。') +
        '）。请进入该卡重新上传。'
      return
    }
  }

  submitting.value = false
  if (nextPath.value) {
    await router.push(nextPath.value)
    return
  }
  creating.value = false
  const madeName = created.name
  const hadFile = file.value !== null
  resetForm()
  await load()
  formNote.value =
    '「' + madeName + '」已创建。' + (hadFile ? '' : '请记得为它上传文件，否则这张卡无法用于交卡。')
}

/** 行内快捷动作：公开切换与撕卡都是同一个 PATCH，失败只在行上报，不动列表其余部分。 */
async function patchCard(card: MyCard, payload: Parameters<typeof updateCard>[1]): Promise<void> {
  if (busyId.value !== null) return
  busyId.value = card.id
  rowError.value = ''
  try {
    const updated = await updateCard(card.id, payload)
    const index = cards.value.findIndex((c) => c.id === card.id)
    if (index >= 0) cards.value[index] = updated
    // 状态筛选开着时，改完可能就不该留在这一页了，重拉一次
    if (status.value && payload.status) await load()
  } catch (e) {
    rowError.value = errorText(e, '本次修改没有保存成功，请稍后再试。')
  } finally {
    busyId.value = null
    confirmTearId.value = null
  }
}

function togglePublic(card: MyCard): void {
  void patchCard(card, { is_public: !card.is_public })
}

function tear(card: MyCard): void {
  void patchCard(card, { status: 'torn' })
}

function restore(card: MyCard): void {
  void patchCard(card, { status: 'alive' })
}

function art(card: MyCard) {
  return cardArt(home.presetByName(card.rule_system), card.rule_system, 'thumb')
}
</script>

<template>
  <div class="mc u-rise">
    <RouterLink class="c-back" to="/me">
      <AppIcon name="back" :size="16" />
      我的
    </RouterLink>

    <PageHead
      eyebrow="My cards · 我的角色卡"
      title="我的角色卡"
      lead="你可以在本页新建角色卡、更换卡的文件、设置公开或私密，以及撕卡。公开的卡会出现在角色卡池中，登录成员可以下载它的文件；私密的卡只有你自己能看到。"
    >
      <template #aside>
        <CButton :variant="creating ? 'ghost' : 'primary'" @click="toggleForm">
          {{ creating ? '收起' : '上传新卡' }}
        </CButton>
      </template>
    </PageHead>

    <CNotice v-if="nextPath" tone="brand" title="建完这张卡会回到刚才的团">
      你是从团页面的「上传新卡并交」进入本页的。请填写卡名并选择文件完成建卡，建卡后页面会自动返回刚才的团，以便继续交卡。
    </CNotice>

    <CNotice v-if="formNote" tone="ok" dismissible @dismiss="formNote = ''">{{ formNote }}</CNotice>
    <CNotice v-if="formError && !creating" tone="warn" dismissible @dismiss="formError = ''">
      {{ formError }}
    </CNotice>

    <!-- ============ 建卡表单（v2 漏画的一段，原位展开） ============ -->
    <CCard v-if="creating" as="section" class="mkform">
      <h2 class="c-sec__title mkform__title">建一张新卡</h2>
      <form novalidate @submit.prevent="onCreate">
        <CNotice v-if="formError" tone="danger">{{ formError }}</CNotice>

        <FormField
          v-model="name"
          no="01"
          label="角色卡名称"
          required
          :maxlength="NAME_MAX"
          placeholder="例：沈青梧"
          :hint="NAME_MAX + ' 字以内。这个名字会显示在卡池和交卡列表里。'"
          :error="fieldErrors.name"
        />

        <div class="c-field">
          <div class="c-field__head">
            <span class="c-field__no">02</span>
            <label class="c-field__label" :for="idRule">对应规则</label>
          </div>
          <select :id="idRule" v-model="rulePick" class="c-select">
            <option value="">暂不填写</option>
            <option v-for="preset in rulePresets" :key="preset" :value="preset">{{ preset }}</option>
            <option :value="RULE_OTHER">其他（自行填写）</option>
          </select>
          <p class="c-field__hint">
            下拉列表中是站主设置的常用规则。如果你的规则不在列表中，请选择「其他」并自行填写规则名称。
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
            :maxlength="RULE_MAX"
            placeholder="例：GURPS / 自制规则"
            :aria-invalid="fieldErrors.rule_system ? 'true' : undefined"
            :aria-describedby="
              fieldErrors.rule_system ? idRuleCustom + '-err' : idRuleCustom + '-hint'
            "
          />
          <p :id="idRuleCustom + '-hint'" class="c-field__hint">
            自行填写的规则没有专属的卡面图片，卡面会使用默认图片。在角色卡池中，这张卡会归入「其他」筛选项。
          </p>
          <p v-if="fieldErrors.rule_system" :id="idRuleCustom + '-err'" class="c-field__error">
            {{ fieldErrors.rule_system }}
          </p>
        </div>

        <div class="c-field">
          <div class="c-field__head">
            <span class="c-field__no">03</span>
            <label class="c-field__label" :for="idFile">角色卡文件</label>
            <span v-if="nextPath" class="mkform__req">必填</span>
          </div>
          <input
            :id="idFile"
            ref="fileInput"
            class="c-input mkform__file"
            type="file"
            :accept="accept"
            :aria-invalid="fileError ? 'true' : undefined"
            :aria-describedby="fileError ? idFile + '-err' : idFile + '-hint'"
            @change="onPickFile"
          />
          <p :id="idFile + '-hint'" class="c-field__hint">
            支持 {{ CARD_FILE_EXTENSIONS.join(' / ') }}，单个文件不超过 {{ maxMb }} MB。
            你也可以暂不上传，之后在这张卡的管理页面中补传；但没有文件的角色卡无法用于交卡。
          </p>
          <p v-if="fileError" :id="idFile + '-err'" class="c-field__error">{{ fileError }}</p>
        </div>

        <div class="c-field">
          <div class="c-field__head">
            <span class="c-field__no">04</span>
            <span class="c-field__label">公开性</span>
          </div>
          <label class="c-check">
            <input v-model="isPublic" type="checkbox" />
            <span>
              放进角色卡池（公开）。公开后，所有人都能看到这张卡的名称、规则、参团次数和参加过的团，登录成员还可以下载它的文件。你随时可以改回私密。
            </span>
          </label>
        </div>

        <div class="c-actions">
          <CButton type="submit" :disabled="submitting">
            {{ submitting ? '建卡中…' : nextPath ? '建卡并回去交卡' : '建卡' }}
          </CButton>
          <CButton variant="ghost" :disabled="submitting" @click="toggleForm">取消</CButton>
        </div>
      </form>
    </CCard>

    <p class="mc__note c-note">
      每张卡只保留最近 3 个文件版本，上传第 4 版时最旧的一版会被删除。更换文件不会改变这张卡本身，这张卡的参团记录会继续保留。撕卡之后，这张卡仍然可以下载，但不能再用于报名。
    </p>

    <div class="c-chips" role="group" aria-label="按状态筛选">
      <CChip
        v-for="option in CARD_STATUS_OPTIONS"
        :key="option.value || 'all'"
        :active="status === option.value"
        @click="status = option.value"
      >
        {{ option.label }}
      </CChip>
    </div>

    <CNotice v-if="rowError" tone="danger" dismissible @dismiss="rowError = ''">
      {{ rowError }}
    </CNotice>

    <LoadState
      :loading="loading"
      :error="error"
      :empty="!cards.length"
      empty-title="你暂时没有角色卡"
      empty-text="请先新建一张角色卡并上传卡的文件，之后就可以用它报名需要交卡的团。"
    >
      <template #empty-actions>
        <CButton v-if="!creating" @click="toggleForm">建一张卡</CButton>
      </template>

      <div class="rows">
        <article v-for="card in cards" :key="card.id" class="row">
          <BlurStage
            class="row__thumb"
            :image="art(card).image"
            :rule="card.rule_system"
            size="thumb"
            :inset="6"
            alt=""
          />

          <div class="row__main">
            <h3 class="row__title">
              <RouterLink :to="'/me/cards/' + card.id">{{ card.name }}</RouterLink>
              <CPill :tone="card.is_public ? 'ok' : 'off'">
                {{ card.is_public ? '公开' : '私密' }}
              </CPill>
              <CPill :tone="card.status === 'torn' ? 'off' : 'ok'">{{ card.status_display }}</CPill>
            </h3>
            <p class="c-meta row__meta">
              <span>{{ card.rule_system || '未填规则' }}</span>
              <span>参团 {{ card.play_count }} 次</span>
              <span>{{ card.has_file ? '已有文件' : '尚未上传文件' }}</span>
              <span>建于 {{ formatDate(card.created_at) }}</span>
            </p>
            <p v-if="!card.has_file" class="row__sub u-small">
              这张卡还没有文件，因此暂时无法用于交卡，也没有可以下载的内容。
            </p>
            <p v-else-if="card.status === 'torn'" class="row__sub u-small">
              这张卡已撕卡：它仍然可以下载，但不能再用于报名。
            </p>
          </div>

          <div class="row__act">
            <template v-if="confirmTearId === card.id">
              <CButton variant="danger" :disabled="busyId !== null" @click="tear(card)">
                确认撕卡
              </CButton>
              <CButton variant="text" @click="confirmTearId = null">取消</CButton>
            </template>
            <template v-else>
              <BtnLink variant="ghost" :to="'/me/cards/' + card.id">管理</BtnLink>
              <CButton variant="text" :disabled="busyId !== null" @click="togglePublic(card)">
                {{ card.is_public ? '设为私密' : '设为公开' }}
              </CButton>
              <CButton
                v-if="card.status === 'alive'"
                variant="text"
                :disabled="busyId !== null"
                @click="confirmTearId = card.id"
              >
                撕卡
              </CButton>
              <CButton
                v-else
                variant="text"
                :disabled="busyId !== null"
                @click="restore(card)"
              >
                恢复为尚存
              </CButton>
            </template>
          </div>
        </article>
      </div>

      <nav v-if="totalPages > 1" class="pager" aria-label="分页">
        <button class="pager__btn" type="button" :disabled="page <= 1" @click="goPage(page - 1)">
          上一页
        </button>
        <span class="pager__at u-small">第 {{ page }} / {{ totalPages }} 页 · 共 {{ count }} 张</span>
        <button class="pager__btn" type="button" :disabled="!hasNext" @click="goPage(page + 1)">
          下一页
        </button>
      </nav>
    </LoadState>

    <div class="mc__foot">
      <span class="u-small">公开的卡会出现在角色卡池里，私密的卡不会。</span>
      <RouterLink class="c-textlink" to="/cards">去看角色卡池 →</RouterLink>
    </div>
  </div>
</template>

<style scoped>
.mkform {
  margin-bottom: var(--sp-5);
}

.mkform__title {
  margin: 0 0 var(--sp-4);
  padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--line);
}

/* 必填徽标：与 FormField 里那枚一致（v2 login/signup 的 .req 线框徽标） */
.mkform__req {
  padding: 1px 5px;
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps);
  line-height: 1.6;
  color: var(--brand-ink);
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
}

/* 文件选择器：套上输入框的外形，但内容高度由浏览器决定，所以不锁死行高 */
.mkform__file {
  padding: var(--sp-2) var(--sp-3);
  line-height: 28px;
}

.mc__note {
  margin: var(--sp-5) 0 var(--sp-4);
}

/* ==========================================================================
   角色卡行（v2 me.html .rows .row：缩略图 + 正文 + 动作列）
   ========================================================================== */

.rows {
  border-top: 1px solid var(--line);
}

.row {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  align-items: start;
  gap: var(--sp-2) var(--sp-4);
  padding: var(--sp-4) 0;
  border-bottom: 1px solid var(--line);
}

.row__thumb {
  width: 72px;
  height: 54px;
  border-radius: var(--radius);
  background: var(--thumb-bg);
}

.row__main {
  min-width: 0;
}

.row__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  font-size: var(--fs-lg);
  line-height: var(--lh-card);
}

/** 本站按全局标准一律加） */
.row__title a {
  display: inline-block;
  min-height: 40px;
  padding: var(--sp-2) 0;
  line-height: 24px;
  color: var(--ink);
  text-decoration: none;
  overflow-wrap: anywhere;
}

.row__title a:hover {
  text-decoration: underline;
  text-underline-offset: 4px;
}

.row__meta {
  margin-top: var(--sp-2);
  /** 业务界面遵循后端权限与隐私约束。 */
  overflow-wrap: anywhere;
}

.row__sub {
  margin: var(--sp-2) 0 0;
  line-height: var(--lh-body);
}

.row__act {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-3);
}

/* ==========================================================================
   分页与页脚行
   ========================================================================== */

.pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2) var(--sp-3);
  margin-top: var(--sp-5);
}

.pager__btn {
  min-width: 44px;
  min-height: 44px;
  padding: 0 var(--sp-3);
  display: inline-grid;
  place-items: center;
  font-size: var(--fs-sm);
  color: var(--ink-soft);
  background: var(--white);
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
}

.pager__btn:disabled {
  color: var(--ink-faint);
  cursor: not-allowed;
}

.mc__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-5);
  margin-top: var(--sp-6);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--line);
}

@media (min-width: 768px) {
  .row {
    grid-template-columns: 88px minmax(0, 620px) auto;
    justify-content: start;
    column-gap: var(--sp-6);
    align-items: center;
  }

  .row__thumb {
    width: 88px;
    height: 66px;
  }

  .row__act {
    grid-column: auto;
    justify-content: flex-end;
  }
}
</style>
