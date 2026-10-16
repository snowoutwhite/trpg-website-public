<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, onMounted, ref, useId } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import BlurStage from '../components/BlurStage.vue'
import CButton from '../components/CButton.vue'
import CCard from '../components/CCard.vue'
import CNotice from '../components/CNotice.vue'
import FormField from '../components/FormField.vue'
import LoadState from '../components/LoadState.vue'
import {
  cardDownloadUrl,
  checkCardFile,
  fetchCardFiles,
  fetchMyCard,
  updateCard,
  uploadCardFile,
  CARD_FILE_EXTENSIONS,
  CARD_FILE_MAX_BYTES,
  type CardFileVersion,
  type CardPlay,
  type MyCard,
} from '../api/cards'
import { ApiError } from '../api/http'
import { errorText } from '../lib/api-error'
import { cardArt, fileKindText, fileSizeText } from '../lib/card-display'
import { formatDate, formatDateTime } from '../lib/datetime'
import { useAuthStore } from '../stores/auth'
import { useHomeStore } from '../stores/home'
import { useSiteStore } from '../stores/site'

/** 规则下拉里「其他（自己填）」那一项的哨兵值。 */
const RULE_OTHER = '__custom__'
const NAME_MAX = 60
const RULE_MAX = 60
/** 后端 `KEEP_FILE_VERSIONS`。 */
const KEEP_VERSIONS = 3

const route = useRoute()
const auth = useAuthStore()
const home = useHomeStore()
const site = useSiteStore()
const { authenticated } = storeToRefs(auth)
const { config } = storeToRefs(site)

const idRule = useId()
const idRuleCustom = useId()
const idNote = useId()
const idPublic = useId()

const cardId = String(route.params.id ?? '')
const card = ref<MyCard | null>(null)
const versions = ref<CardFileVersion[]>([])
const loading = ref(true)
const error = ref('')

// —— 卡面信息表单 ——
const name = ref('')
const rulePick = ref('')
const ruleCustom = ref('')
const note = ref('')
const saving = ref(false)
const saved = ref('')
const formError = ref('')
const fieldErrors = ref<Record<string, string>>({})

// —— 换文件 ——
const uploading = ref(false)
const uploadError = ref('')
const uploadOk = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

// —— 撕卡 ——
const confirmTear = ref(false)

const rulePresets = computed(() => config.value.rule_system_presets ?? [])
const ruleSystem = computed(() =>
  rulePick.value === RULE_OTHER ? ruleCustom.value.trim() : rulePick.value,
)
const accept = computed(() => CARD_FILE_EXTENSIONS.map((e) => '.' + e).join(','))
const maxMb = Math.round(CARD_FILE_MAX_BYTES / 1024 / 1024)
const current = computed<CardFileVersion | null>(() => versions.value[0] ?? null)
const art = computed(() =>
  card.value ? cardArt(home.presetByName(card.value.rule_system), card.value.rule_system, 'full') : null,
)

/** 卡面事实网格（与公开页同一组，另加「最后更新」）。 */
const facts = computed<{ k: string; v: string }[]>(() => {
  const data = card.value
  if (!data) return []
  return [
    { k: '规则', v: data.rule_system || '未填' },
    { k: '公开性', v: data.is_public ? '公开（在卡池里）' : '私密（只有自己看得到）' },
    { k: '状态', v: data.status_display },
    { k: '参团次数', v: data.play_count + ' 次' },
    { k: '建卡时间', v: formatDate(data.created_at) },
    { k: '最后更新', v: formatDate(data.updated_at) },
  ]
})

function syncForm(data: MyCard): void {
  card.value = data
  name.value = data.name
  note.value = data.note
  if (data.rule_system && rulePresets.value.includes(data.rule_system)) {
    rulePick.value = data.rule_system
    ruleCustom.value = ''
  } else if (data.rule_system) {
    rulePick.value = RULE_OTHER
    ruleCustom.value = data.rule_system
  } else {
    rulePick.value = ''
    ruleCustom.value = ''
  }
}

async function loadVersions(): Promise<void> {
  versions.value = (await fetchCardFiles(cardId)).results
}

onMounted(async () => {
  // 规则下拉要用站级预设，先等它（syncForm 按预设判断「是不是自定义规则」）
  await site.load()
  void home.load(authenticated.value)
  try {
    syncForm(await fetchMyCard(cardId))
    await loadVersions()
  } catch (e) {
    error.value = errorText(e, '这张角色卡暂时无法读取，请刷新后重试。', {
      not_found: '这张角色卡不存在，或者它不属于你。',
    })
  } finally {
    loading.value = false
  }
})

async function patch(payload: Parameters<typeof updateCard>[1]): Promise<void> {
  if (saving.value) return
  formError.value = ''
  fieldErrors.value = {}
  saved.value = ''
  saving.value = true
  try {
    syncForm(await updateCard(cardId, payload))
    saved.value = '已保存。'
  } catch (e) {
    if (e instanceof ApiError) {
      fieldErrors.value = e.fieldErrors()
      formError.value = e.formMessage() || errorText(e, '保存失败，请稍后再试。')
    } else {
      formError.value = '保存失败，请稍后再试。'
    }
  } finally {
    saving.value = false
    confirmTear.value = false
  }
}

function onSave(): void {
  fieldErrors.value = {}
  if (!name.value.trim()) {
    fieldErrors.value = { name: '请为这张卡填写名称。' }
    return
  }
  if (rulePick.value === RULE_OTHER && !ruleCustom.value.trim()) {
    fieldErrors.value = { rule_system: '选择「其他」时须填写规则名称。' }
    return
  }
  void patch({ name: name.value.trim(), rule_system: ruleSystem.value, note: note.value })
}

function onTogglePublic(): void {
  if (!card.value) return
  void patch({ is_public: !card.value.is_public })
}

function onTear(): void {
  void patch({ status: 'torn' })
}

function onRestore(): void {
  void patch({ status: 'alive' })
}

async function onPickFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const picked = input.files?.[0]
  uploadError.value = ''
  uploadOk.value = ''
  if (!picked) return

  const problem = checkCardFile(picked)
  if (problem) {
    uploadError.value = problem
    input.value = ''
    return
  }

  uploading.value = true
  try {
    const version = await uploadCardFile(cardId, picked)
    uploadOk.value = '已经换成第 ' + version.version + ' 版：' + version.original_name
    syncForm(await fetchMyCard(cardId))
    await loadVersions()
  } catch (e) {
    uploadError.value = errorText(e, '文件上传失败，请稍后再试。')
  } finally {
    uploading.value = false
    input.value = ''
  }
}

/** 团被删掉时 games 的 provider 补不上团名（services.games_played_for），降级成一行说明。 */
function playTitle(play: CardPlay): string {
  return play.title || '此团已从本站删除'
}
</script>

<template>
  <div class="mcd u-rise">
    <RouterLink class="c-back" to="/me/cards">
      <AppIcon name="back" :size="16" />
      我的角色卡
    </RouterLink>

    <LoadState :loading="loading" :error="error">
      <template v-if="card">
        <CCard as="article" flush class="mcd-card">
          <BlurStage
            class="mcd-hero"
            :image="art?.image ?? null"
            :rule="card.rule_system"
            size="full"
            tone="dark"
            :foreground="false"
          >
            <p class="u-kicker mcd-hero__kicker">My character sheet</p>
            <h1 class="u-h-section mcd-hero__title">{{ card.name }}</h1>
            <p class="mcd-hero__tags">
              <span v-if="card.rule_system" class="c-tag c-tag--dark">{{ card.rule_system }}</span>
              <span class="c-tag c-tag--dark">{{ card.status_display }}</span>
              <span class="c-tag c-tag--dark">{{ card.is_public ? '公开' : '私密' }}</span>
              <span class="c-tag c-tag--dark">参团 {{ card.play_count }} 次</span>
            </p>
          </BlurStage>

          <div class="mcd-body">
            <dl class="facts">
              <div v-for="fact in facts" :key="fact.k" class="facts__cell">
                <dt class="u-kicker">{{ fact.k }}</dt>
                <dd>{{ fact.v }}</dd>
              </div>
            </dl>
            <RouterLink v-if="card.is_public" class="c-textlink mcd-peek" :to="'/cards/' + card.id">
              查看其他人看到的这张卡 →
            </RouterLink>
          </div>
        </CCard>

        <CNotice v-if="formError" tone="danger" dismissible @dismiss="formError = ''">
          {{ formError }}
        </CNotice>
        <CNotice v-else-if="saved" tone="ok" dismissible @dismiss="saved = ''">{{ saved }}</CNotice>

        <div class="mcd-cols">
          <div class="mcd-col">
            <!-- ============ 当前文件 + 换文件 ============ -->
            <section class="c-sec">
              <div class="c-sec__head">
                <h2 class="c-sec__title">卡的文件</h2>
                <span class="u-small">只保留最近 {{ KEEP_VERSIONS }} 版</span>
              </div>

              <CNotice v-if="uploadError" tone="danger" dismissible @dismiss="uploadError = ''">
                {{ uploadError }}
              </CNotice>
              <CNotice v-else-if="uploadOk" tone="ok" dismissible @dismiss="uploadOk = ''">
                {{ uploadOk }}
              </CNotice>

              <div v-if="current" class="nowfile">
                <p class="u-kicker">当前文件</p>
                <p class="nowfile__name">{{ current.original_name }}</p>
                <p class="c-meta nowfile__meta">
                  <span>v{{ current.version }}</span>
                  <span>{{ fileKindText(current.original_name) }}</span>
                  <span>{{ fileSizeText(current.size) }}</span>
                  <span>上传于 {{ formatDateTime(current.created_at) }}</span>
                  <span v-if="current.uploaded_by_gm" class="c-tag c-tag--gm">GM 代传</span>
                </p>
                <div class="c-actions nowfile__act">
                  <a class="c-btn" :href="cardDownloadUrl(card.id, current.version)">
                    <AppIcon name="download" :size="18" />
                    下载当前文件
                  </a>
                  <CButton
                    variant="ghost"
                    :disabled="uploading"
                    @click="fileInput?.click()"
                  >
                    {{ uploading ? '上传中…' : '换一个文件' }}
                  </CButton>
                </div>
              </div>
              <div v-else class="nowfile nowfile--empty">
                <p class="u-kicker">还没有文件</p>
                <p class="u-small nowfile__note">
                  这张卡还没有文件，因此暂时无法用于交卡，也没有可以下载的内容。只有状态为「尚存」并且已上传文件的角色卡才能用于交卡。
                </p>
                <div class="c-actions nowfile__act">
                  <CButton :disabled="uploading" @click="fileInput?.click()">
                    {{ uploading ? '上传中…' : '上传第一版文件' }}
                  </CButton>
                </div>
              </div>

              <!-- 真正的控件是上面那两个按钮（click() 代打开文件框），这个 input 只是它们的载体：
                   `u-hidden` 让它退成 1px，所以同时摘出无障碍树与 Tab 序，免得留一个看不见的焦点点 -->
              <input
                ref="fileInput"
                class="u-hidden"
                type="file"
                tabindex="-1"
                aria-hidden="true"
                :accept="accept"
                @change="onPickFile"
              />

              <p class="c-field__hint mcd-hint">
                支持 {{ CARD_FILE_EXTENSIONS.join(' / ') }}，单个文件不超过 {{ maxMb }} MB。
                更换文件不会改变这张卡本身，这张卡参加过的团的记录会继续保留。
                上传第 {{ KEEP_VERSIONS + 1 }} 版时，最旧的一版会连文件一起删除。
              </p>

              <h3 class="mcd-sub">最近的版本</h3>
              <div class="rows">
                <div v-for="version in versions" :key="version.id" class="row">
                  <span class="row__t">
                    <b>v{{ version.version }}</b>
                    <span v-if="version.version === current?.version" class="c-tag">最新</span>
                    <span v-if="version.uploaded_by_gm" class="c-tag c-tag--gm">GM 代传</span>
                    <span class="row__file">{{ version.original_name }}</span>
                  </span>
                  <span class="row__d u-small">
                    {{ formatDateTime(version.created_at) }} ·
                    {{ fileKindText(version.original_name) }} · {{ fileSizeText(version.size) }}
                    <a class="row__dl" :href="cardDownloadUrl(card.id, version.version)">下载</a>
                  </span>
                </div>
                <p v-if="!versions.length" class="rows__none u-small">这张卡暂时没有上传过文件。</p>
              </div>
            </section>

            <!-- ============ 参团记录 ============ -->
            <section class="c-sec">
              <div class="c-sec__head">
                <h2 class="c-sec__title">参团记录</h2>
                <span class="u-small">共 {{ card.play_count }} 次</span>
              </div>
              <div class="rows">
                <div v-for="play in card.games_played" :key="play.game_id" class="row">
                  <span class="row__t">
                    <RouterLink v-if="play.title" :to="'/games/' + play.game_id">
                      {{ play.title }}
                    </RouterLink>
                    <span v-else class="u-muted">{{ playTitle(play) }}</span>
                  </span>
                  <span class="row__d u-small">
                    结团 {{ formatDateTime(play.finished_at || play.played_at) }}
                  </span>
                </div>
                <p v-if="!card.games_played.length" class="rows__none u-small">
                  这张卡暂时没有参加过团。用这张卡参加的团成功结团后，会在此处记录一次，参团次数也会增加 1 次。
                </p>
              </div>
            </section>
          </div>

          <div class="mcd-col">
            <!-- ============ 公开性 ============ -->
            <section class="c-sec">
              <div class="c-sec__head">
                <h2 class="c-sec__title">公开性</h2>
              </div>
              <label class="c-check" :for="idPublic">
                <input
                  :id="idPublic"
                  type="checkbox"
                  :checked="card.is_public"
                  :disabled="saving"
                  @change="onTogglePublic"
                />
                <span>
                  放进角色卡池。公开后，所有人都能看到这张卡的名称、规则、参团次数和参加过的团，登录成员还可以下载它的文件；改回私密后，这张卡会立即从角色卡池中移除。
                </span>
              </label>
            </section>

            <!-- ============ 撕卡 ============ -->
            <section class="c-sec">
              <div class="c-sec__head">
                <h2 class="c-sec__title">撕卡</h2>
              </div>
              <p class="u-small mcd-tear">
                撕卡表示这个角色已经退场。<b>撕卡不是删除</b>：这张卡仍然保留，如果它是公开的，其他人仍然可以下载；参团次数和参团记录也都会保留。撕卡后唯一的变化是 <b>这张卡不能再用于报名任何团</b>（报名时只能选择状态为「尚存」的卡）。你可以随时把它恢复为「尚存」；如果想用这个角色开始新的经历，也可以新建一张卡。
              </p>
              <div class="c-actions">
                <template v-if="card.status === 'alive'">
                  <CButton
                    v-if="!confirmTear"
                    variant="danger"
                    :disabled="saving"
                    @click="confirmTear = true"
                  >
                    撕掉这张卡
                  </CButton>
                  <template v-else>
                    <CButton variant="danger" :disabled="saving" @click="onTear">确认撕卡</CButton>
                    <CButton variant="ghost" @click="confirmTear = false">取消</CButton>
                  </template>
                </template>
                <CButton v-else variant="ghost" :disabled="saving" @click="onRestore">
                  恢复为尚存
                </CButton>
              </div>
            </section>

            <!-- ============ 卡面信息 ============ -->
            <section class="c-sec">
              <div class="c-sec__head">
                <h2 class="c-sec__title">卡面信息</h2>
              </div>
              <form novalidate @submit.prevent="onSave">
                <FormField
                  v-model="name"
                  no="01"
                  label="角色卡名称"
                  required
                  :maxlength="NAME_MAX"
                  :error="fieldErrors.name"
                />

                <div class="c-field">
                  <div class="c-field__head">
                    <span class="c-field__no">02</span>
                    <label class="c-field__label" :for="idRule">对应规则</label>
                  </div>
                  <select :id="idRule" v-model="rulePick" class="c-select">
                    <option value="">暂不填写</option>
                    <option v-for="preset in rulePresets" :key="preset" :value="preset">
                      {{ preset }}
                    </option>
                    <option :value="RULE_OTHER">其他（自行填写）</option>
                  </select>
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
                    :aria-invalid="fieldErrors.rule_system ? 'true' : undefined"
                    :aria-describedby="fieldErrors.rule_system ? idRuleCustom + '-err' : undefined"
                  />
                  <p v-if="fieldErrors.rule_system" :id="idRuleCustom + '-err'" class="c-field__error">
                    {{ fieldErrors.rule_system }}
                  </p>
                </div>

                <div class="c-field">
                  <div class="c-field__head">
                    <span class="c-field__no">03</span>
                    <label class="c-field__label" :for="idNote">备注</label>
                  </div>
                  <textarea :id="idNote" v-model="note" class="c-textarea" />
                  <p class="c-field__hint">备注只有你自己能看到，角色卡池和公开页面都不会显示。</p>
                </div>

                <div class="c-actions">
                  <CButton type="submit" :disabled="saving">
                    {{ saving ? '保存中…' : '保存卡面信息' }}
                  </CButton>
                </div>
              </form>
            </section>
          </div>
        </div>
      </template>
    </LoadState>
  </div>
</template>

<style scoped>
.mcd-card {
  margin-top: var(--sp-4);
}

.mcd-hero {
  padding: var(--sp-6) var(--sp-4) var(--sp-5);
  color: var(--on-dark);
  text-shadow: var(--text-shadow-dark);
}

.mcd-hero__kicker {
  margin: 0;
  color: var(--on-dark-kicker);
}

.mcd-hero__title {
  margin: var(--sp-2) 0 var(--sp-3);
  overflow-wrap: anywhere;
}

.mcd-hero__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1);
  margin: 0;
}

/** 业务界面遵循后端权限与隐私约束。 */
.mcd-hero__tags .c-tag {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mcd-body {
  padding: var(--sp-5) var(--sp-4);
}

.facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  margin: 0;
  background: var(--line);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}

.facts__cell {
  padding: var(--sp-3) var(--sp-4);
  background: var(--white);
}

/* 奇数格时最后一格通栏：`.facts` 用 1px 缝当分隔线（底色是 --line），
   留一个空位会在版面上露出一块灰方块（1440 复看发现） */
.facts__cell:last-child:nth-child(odd) {
  grid-column: 1 / -1;
}

.facts__cell dt {
  margin: 0 0 var(--sp-2);
}

.facts__cell dd {
  margin: 0;
  font-size: var(--fs-base);
  line-height: var(--lh-card);
  color: var(--ink);
  overflow-wrap: anywhere;
}

.mcd-peek {
  display: inline-block;
  margin-top: var(--sp-3);
}

.mcd-cols {
  display: grid;
  gap: 0;
}

.mcd-col {
  min-width: 0;
}

/* ==========================================================================
   当前文件
   ========================================================================== */

.nowfile {
  padding: var(--sp-4);
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.nowfile--empty {
  border-style: dashed;
  border-color: var(--line-2);
}

.nowfile__name {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-lg);
  line-height: var(--lh-card);
  overflow-wrap: anywhere;
}

.nowfile__meta {
  margin-top: var(--sp-2);
}

.nowfile__note {
  margin: var(--sp-2) 0 0;
  line-height: var(--lh-body);
}

.nowfile__act {
  margin-top: var(--sp-4);
}

.mcd-hint {
  margin-top: var(--sp-3);
}

.mcd-sub {
  margin: var(--sp-5) 0 var(--sp-2);
  font-size: var(--fs-lg);
  line-height: var(--lh-card);
}

/* ==========================================================================
   版本 / 参团记录的行（v2 cards.html .mini-rows）
   ========================================================================== */

.rows {
  border-top: 1px solid var(--line);
}

.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-1) var(--sp-4);
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--line);
}

.row__t {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  min-width: 0;
  font-size: var(--fs-base);
}

.row__t b {
  font-weight: 400;
}

.row__t a {
  display: inline-block;
  min-height: 40px;
  padding: var(--sp-2) 0;
  line-height: 24px;
  color: var(--brand-ink);
  text-decoration: none;
  overflow-wrap: anywhere;
}

.row__t a:hover {
  text-decoration: underline;
  text-underline-offset: 4px;
}

.row__file {
  min-width: 0;
  font-size: var(--fs-xs);
  color: var(--ink-muted);
  overflow-wrap: anywhere;
}

.row__d {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
}

.row__dl {
  display: inline-block;
  min-height: 40px;
  padding: var(--sp-2) 0;
  line-height: 24px;
  color: var(--brand-ink);
  text-decoration: none;
}

.row__dl:hover {
  text-decoration: underline;
  text-underline-offset: 4px;
}

.rows__none {
  margin: 0;
  padding: var(--sp-4) 0;
  border-bottom: 1px solid var(--line);
}

.mcd-tear {
  margin: 0;
  line-height: var(--lh-body);
}

.mcd-tear b {
  font-weight: 400;
  color: var(--ink);
}

@media (min-width: 768px) {
  .mcd-hero {
    padding: var(--sp-7) var(--sp-6) var(--sp-6);
  }

  .mcd-body {
    padding: var(--sp-6);
  }

  .nowfile {
    padding: var(--sp-5);
  }
}

/* 宽屏：文件与参团记录在左，公开性 / 撕卡 / 卡面信息在右 */
@media (min-width: 1200px) {
  .mcd-cols {
    grid-template-columns: minmax(0, 1fr) 360px;
    column-gap: var(--sp-7);
    align-items: start;
  }
}
</style>
