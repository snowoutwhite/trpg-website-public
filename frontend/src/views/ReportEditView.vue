<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import CButton from '../components/CButton.vue'
import CChip from '../components/CChip.vue'
import CNotice from '../components/CNotice.vue'
import FormField from '../components/FormField.vue'
import LoadState from '../components/LoadState.vue'
import MarkdownView from '../components/MarkdownView.vue'
import PageHead from '../components/PageHead.vue'
import {
  checkImportFile,
  deleteAttachment,
  fetchReport,
  importDocument,
  fetchReports,
  submitReport,
  updateReport,
  uploadAttachment,
  BODY_MAX_LENGTH,
  MAX_ATTACHMENTS,
  TITLE_MAX_LENGTH,
  VISIBILITY_OPTIONS,
  type DocumentImportResult,
  type ReportDetail,
  type ReportVisibility,
} from '../api/reports'
import { checkCardFile, CARD_FILE_EXTENSIONS } from '../api/cards'
import { fetchGame, type GameDetail } from '../api/games'
import { ApiError } from '../api/http'
import { errorText } from '../lib/api-error'
import { formatDate } from '../lib/datetime'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { user } = storeToRefs(auth)

const gameId = String(route.params.id ?? '')
/** 整份团详情：进页要用 `status` / `gm` / `my_signup` 先判「能不能写」，摘要型不够。 */
const game = ref<GameDetail | null>(null)

/** 业务界面遵循后端权限与隐私约束。 */
const blockedReason = computed<string>(() => {
  if (report.value) return ''
  const g = game.value
  const me = user.value
  if (!g || !me) return ''
  if (g.status === 'cancelled') return '此团已取消，不能撰写战报。'
  if (g.status !== 'finished') return '此团还没有结团，暂时不能撰写战报，请在结团后再来。'
  const isGm = g.gm.id === me.id
  const attended = g.my_signup?.status === 'accepted' && g.my_signup.attended === true
  if (!isGm && !attended) return '只有在本团被标记为到场的成员才能撰写战报，本团 GM 视为到场。'
  return ''
})
const report = ref<ReportDetail | null>(null)
const loading = ref(true)
const error = ref('')

const title = ref('')
const body = ref('')
const visibility = ref<ReportVisibility>('public')
/** 窄屏下的「写 / 预览」切换；≥1200 两栏并排，这个值不起作用。 */
const tab = ref<'write' | 'preview'>('write')

const saving = ref(false)
const savedNote = ref('')
const formError = ref('')
const fieldErrors = ref<Record<string, string>>({})

const uploading = ref(false)
const uploadError = ref('')
const dragOver = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const bodyInput = ref<HTMLTextAreaElement | null>(null)

/** 从文档导入：转换中 / 等用户选替换还是追加 / 导入后的提示。 */
const importing = ref(false)
const importError = ref('')
const importInput = ref<HTMLInputElement | null>(null)
const pendingImport = ref<DocumentImportResult | null>(null)
const importNotes = ref<string[]>([])
const importDone = ref(false)

/** 还没保存过时选的文件：先攒着，保存成功后再按顺序传。 */
const staged = ref<File[]>([])

const accept = computed(() => CARD_FILE_EXTENSIONS.map((e) => '.' + e).join(','))
const attachments = computed(() => report.value?.attachments ?? [])
const attachmentCount = computed(() => attachments.value.length + staged.value.length)
const attachmentsLeft = computed(() => MAX_ATTACHMENTS - attachmentCount.value)

onMounted(async () => {
  await auth.refresh()
  try {
    game.value = await fetchGame(gameId)
  } catch {
    game.value = null
  }
  try {
    if (user.value) {
      const mine = await fetchReports({ game: gameId, author: user.value.id })
      const existing = mine.results.find((item) => item.author.id === user.value?.id)
      if (existing) {
        const detail = await fetchReport(existing.id)
        report.value = detail
        title.value = detail.title
        body.value = detail.body_markdown
        visibility.value = detail.visibility
      }
    }
  } catch (e) {
    error.value = errorText(e, '你在本团的战报暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
})

/** 在光标处插入/包裹一段文本，不破坏已有内容。 */
function apply(kind: 'wrap' | 'line' | 'insert', a: string, b = ''): void {
  const el = bodyInput.value
  const text = body.value
  const start = el?.selectionStart ?? text.length
  const end = el?.selectionEnd ?? text.length
  const selected = text.slice(start, end)

  let replacement: string
  if (kind === 'wrap') {
    replacement = a + (selected || '文字') + (b || a)
  } else if (kind === 'line') {
    const target = selected || '内容'
    replacement = target
      .split('\n')
      .map((line) => a + line)
      .join('\n')
  } else {
    replacement = a
  }

  const head = text.slice(0, start)
  const tail = text.slice(end)
  // 行级标记要保证自己独占一行
  const prefix = kind !== 'wrap' && head && !head.endsWith('\n') ? '\n' : ''
  body.value = head + prefix + replacement + tail

  const caret = head.length + prefix.length + replacement.length
  void nextTick(() => {
    el?.focus()
    el?.setSelectionRange(caret, caret)
  })
}

const TOOLS: { label: string; run: () => void }[] = [
  { label: '分节', run: () => apply('line', '## ') },
  { label: '粗体', run: () => apply('wrap', '**') },
  { label: '斜体', run: () => apply('wrap', '*') },
  { label: '引用', run: () => apply('line', '> ') },
  { label: '列表', run: () => apply('line', '- ') },
  { label: '链接', run: () => apply('insert', '[链接文字](https://)') },
  { label: '分隔线', run: () => apply('insert', '\n---\n') },
]

async function onPickImport(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  importError.value = ''
  importNotes.value = []
  importDone.value = false
  pendingImport.value = null
  if (!file) return
  const problem = checkImportFile(file)
  if (problem) {
    importError.value = problem
    return
  }
  importing.value = true
  try {
    const result = await importDocument(gameId, file)
    if (body.value.trim()) {
      pendingImport.value = result
    } else {
      applyImport(result, 'replace')
    }
  } catch (e) {
    importError.value = errorText(e, '文档导入失败，请稍后再试。')
  } finally {
    importing.value = false
  }
}

/** 把转换结果放进正文：替换，或接在现有正文末尾（中间空一行）。 */
function applyImport(result: DocumentImportResult, mode: 'replace' | 'append'): void {
  pendingImport.value = null
  let next =
    mode === 'append'
      ? body.value.replace(/\s+$/, '') + '\n\n' + result.body_markdown
      : result.body_markdown
  let cut = result.truncated
  if (next.length > BODY_MAX_LENGTH) {
    next = next.slice(0, BODY_MAX_LENGTH)
    cut = true
  }
  body.value = next
  const notes = result.warnings.slice()
  if (cut) {
    notes.push(
      '正文最多 ' +
        BODY_MAX_LENGTH.toLocaleString('en-US') +
        ' 个字符，超出的部分没有导入。请检查正文结尾是否完整，必要时把剩余内容拆到附件中。',
    )
  }
  importNotes.value = notes
  importDone.value = true
}

/** 保存成功后把暂存的附件补传上去；有失败就把话说清楚，但不阻断「已经存好了」这件事。 */
async function flushStaged(target: ReportDetail): Promise<ReportDetail> {
  if (!staged.value.length) return target
  uploading.value = true
  const failed: string[] = []
  const queue = staged.value.slice()
  staged.value = []
  for (const file of queue) {
    try {
      await uploadAttachment(target.id, file)
    } catch (e) {
      failed.push(file.name + '（' + errorText(e, '上传失败') + '）')
    }
  }
  uploading.value = false
  if (failed.length) uploadError.value = '以下附件上传失败：' + failed.join('；')
  try {
    return await fetchReport(target.id)
  } catch {
    return target
  }
}

async function onSave(): Promise<void> {
  if (saving.value) return
  formError.value = ''
  fieldErrors.value = {}
  savedNote.value = ''
  const payload = {
    title: title.value.trim(),
    body_markdown: body.value,
    visibility: visibility.value,
  }
  if (!payload.title) {
    fieldErrors.value = { title: '战报标题不能为空' }
    return
  }
  saving.value = true
  try {
    const saved = report.value
      ? await updateReport(report.value.id, payload)
      : await submitReport(gameId, payload)
    report.value = await flushStaged(saved)
    savedNote.value = '已保存。'
    // 保存后跳正文页（v2 口径）；附件有失败时留在本页，先把话说完
    if (!uploadError.value) {
      await router.push('/reports/' + saved.id)
    }
  } catch (e) {
    if (e instanceof ApiError) {
      fieldErrors.value = e.fieldErrors()
      formError.value = e.formMessage() || errorText(e, '保存失败，请稍后再试。')
    } else {
      formError.value = '保存失败，请稍后再试。'
    }
  } finally {
    saving.value = false
  }
}

/** 选文件与拖放走同一条路：校验 → 有战报就直接传，没有就暂存。 */
async function takeFiles(list: FileList | null): Promise<void> {
  uploadError.value = ''
  if (!list || !list.length) return
  for (const file of Array.from(list)) {
    if (attachmentsLeft.value <= 0) {
      uploadError.value = '一份战报最多 ' + MAX_ATTACHMENTS + ' 个附件。'
      return
    }
    const problem = checkCardFile(file)
    if (problem) {
      uploadError.value = problem
      return
    }
    if (!report.value) {
      staged.value = staged.value.concat(file)
      continue
    }
    uploading.value = true
    try {
      await uploadAttachment(report.value.id, file)
      report.value = await fetchReport(report.value.id)
    } catch (e) {
      uploadError.value = errorText(e, '文件上传失败，请稍后再试。')
    } finally {
      uploading.value = false
    }
  }
}

async function onPickFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = input.files
  await takeFiles(files)
  input.value = ''
}

async function onDrop(event: DragEvent): Promise<void> {
  dragOver.value = false
  await takeFiles(event.dataTransfer?.files ?? null)
}

async function onRemoveAttachment(attachmentId: number): Promise<void> {
  if (!report.value) return
  uploadError.value = ''
  try {
    await deleteAttachment(report.value.id, attachmentId)
    report.value = await fetchReport(report.value.id)
  } catch (e) {
    uploadError.value = errorText(e, '附件删除失败，请稍后再试。')
  }
}

function removeStaged(index: number): void {
  staged.value = staged.value.filter((_, i) => i !== index)
}

function sizeText(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

const cancelTo = computed(() =>
  report.value ? '/reports/' + report.value.id : '/games/' + gameId + '#reports',
)
</script>

<template>
  <div class="edit u-rise l-narrow">
    <LoadState :loading="loading" :error="error">
      <PageHead
        eyebrow="Write your report · 写战报"
        :title="report ? '修改我的战报' : '撰写战报'"
        lead="请把你在本团的经历记录下来。保存后，正文会按照你写下的原样保存。"
      />

      <!-- ===== 三条规矩（v2 .notes） ===== -->
      <div class="notes">
        <div class="notes__row">
          <AppIcon class="notes__icon" name="file" :size="16" />
          <p class="notes__txt">
            每人在每个团只能写一篇战报，再次保存会替换原来的内容。
            <small>
              需要补充内容时，回到本页修改即可，不会新增第二篇。每篇战报固定属于一个团，写好后不能改到其他团。
            </small>
          </p>
        </div>
        <div class="notes__row">
          <AppIcon class="notes__icon" name="person" :size="16" />
          <p class="notes__txt">
            只有在本团被标记为到场的成员才能撰写战报，本团 GM 自动视为到场。
            <small>
              已退出、被移出名单或报名被拒绝的玩家不算本团成员，既不能撰写本团战报，也不能阅读设为「仅同团可见」的战报。
            </small>
          </p>
        </div>
        <div class="notes__row">
          <AppIcon class="notes__icon" name="flag" :size="16" />
          <p class="notes__txt">
            第一次提交某个团的战报时，你会获得一次积分。
            <small>同一个团的战报只在第一次提交时计分，之后修改不会重复计分。本站暂时没有查看积分的页面。</small>
          </p>
        </div>
      </div>

      <!-- 业务信息 -->
      <CNotice v-if="blockedReason" tone="warn" title="你暂时不能撰写此团的战报">
        {{ blockedReason }}
        <template #actions>
          <RouterLink class="c-textlink" :to="'/games/' + gameId + '#reports'">返回团页面 →</RouterLink>
        </template>
      </CNotice>

      <CNotice v-if="formError" tone="danger">{{ formError }}</CNotice>
      <CNotice v-else-if="savedNote" tone="ok">
        {{ savedNote }}
        <template v-if="report" #actions>
          <RouterLink class="c-textlink" :to="'/reports/' + report.id">查看已发布的战报 →</RouterLink>
        </template>
      </CNotice>

      <form v-if="!blockedReason" novalidate @submit.prevent="onSave">
        <!-- ===== 所属团（只读） ===== -->
        <div class="block">
          <span class="u-kicker block__k">所属团</span>
          <div class="lock">
            <span v-if="game?.rule_system" class="c-tag">{{ game.rule_system }}</span>
            <span class="lock__title">{{ game ? game.title : '第 ' + gameId + ' 号团' }}</span>
            <span v-if="game?.finished_at" class="u-small">
              {{ formatDate(game.finished_at) }} 结团
            </span>
            <span v-else-if="game" class="u-small">{{ game.status_display }}</span>
            <RouterLink class="c-textlink lock__link" :to="'/games/' + gameId + '#reports'">
              返回团页面 →
            </RouterLink>
          </div>
          <p class="c-field__hint">
            每篇战报固定属于一个团，这里不能更改。如果选错了团，请回到正确的团页面，再点击「撰写我的战报」。
          </p>
        </div>

        <!-- ===== 标题 ===== -->
        <div class="block">
          <FormField
            v-model="title"
            no="01"
            label="标题"
            required
            :maxlength="TITLE_MAX_LENGTH"
            :error="fieldErrors.title"
            :hint="title.length + ' / ' + TITLE_MAX_LENGTH + ' 字'"
            placeholder="例如：雾港疑影 · 第三场"
          />
        </div>

        <!-- ===== 可见范围 ===== -->
        <div class="block">
          <span class="u-kicker block__k">可见范围</span>
          <div class="picks">
            <label
              v-for="option in VISIBILITY_OPTIONS"
              :key="option.value"
              class="pick"
              :class="{ 'pick--on': visibility === option.value }"
            >
              <input
                v-model="visibility"
                class="pick__radio"
                type="radio"
                name="visibility"
                :value="option.value"
              />
              <span class="pick__txt">
                <strong>{{ option.label }}</strong>
                <small>{{ option.hint }}</small>
              </span>
            </label>
          </div>
          <p class="c-field__hint">
            「精选」不能在这里设置，只有站主可以标记。只有被站主精选的公开战报，未登录的访客才能阅读。
          </p>
        </div>

        <!-- ===== 正文 ===== -->
        <div class="block">
          <span class="u-kicker block__k">正文</span>

          <div class="tools">
            <CChip v-for="tool in TOOLS" :key="tool.label" @click="tool.run">
              {{ tool.label }}
            </CChip>
            <span class="tools__gap" />
            <CChip class="tools__switch" :active="tab === 'write'" @click="tab = 'write'">编辑</CChip>
            <CChip class="tools__switch" :active="tab === 'preview'" @click="tab = 'preview'">
              预览
            </CChip>
          </div>

          <div class="import">
            <CButton variant="ghost" :disabled="importing" @click="importInput?.click()">
              {{ importing ? '正在读取文档…' : '从文档导入' }}
            </CButton>
            <span class="u-small import__hint">
              可以选择一份 Word 文档（.docx）或纯文本文件（.txt），文字会转换后填入下方的编辑框，不会作为附件上传。文档中的图片不会导入。
            </span>
            <!-- 同附件那个 input：真正的控件是上面的按钮，这里只是载体 -->
            <input
              ref="importInput"
              class="u-hidden"
              type="file"
              tabindex="-1"
              aria-hidden="true"
              accept=".docx,.txt"
              @change="onPickImport"
            />
          </div>

          <CNotice v-if="importError" tone="danger">{{ importError }}</CNotice>
          <CNotice v-if="pendingImport" tone="warn" title="正文中已经有内容">
            文档已经读取完成。你可以用文档内容替换当前正文，也可以把文档内容接在当前正文的末尾。
            <template #actions>
              <CButton @click="applyImport(pendingImport, 'replace')">替换现有正文</CButton>
              <CButton variant="ghost" @click="applyImport(pendingImport, 'append')">追加到末尾</CButton>
              <CButton variant="text" @click="pendingImport = null">放弃导入</CButton>
            </template>
          </CNotice>
          <CNotice
            v-if="importDone"
            :tone="importNotes.length ? 'warn' : 'ok'"
            :title="importNotes.length ? '文档内容已填入正文，请注意以下几点' : '文档内容已填入正文'"
            dismissible
            @dismiss="importDone = false"
          >
            <template v-if="!importNotes.length">请在预览中核对格式，确认无误后再保存战报。</template>
            <ul v-else class="import__notes">
              <li v-for="note in importNotes" :key="note">{{ note }}</li>
            </ul>
          </CNotice>

          <div class="editor">
            <div class="pane" :class="{ 'pane--off': tab !== 'write' }">
              <div class="pane__head">
                <span>编辑</span>
                <span>{{ body.length }} 字</span>
              </div>
              <textarea
                ref="bodyInput"
                v-model="body"
                class="pane__area"
                spellcheck="false"
                aria-label="战报正文"
                :maxlength="BODY_MAX_LENGTH"
                placeholder="例如：从那天晚上的第一次检定开始写起……"
              />
            </div>
            <div class="pane" :class="{ 'pane--off': tab !== 'preview' }">
              <div class="pane__head">
                <span>预览</span>
                <span>仅供参考，与发布后的实际效果可能略有不同</span>
              </div>
              <div class="pane__preview" aria-live="polite">
                <MarkdownView v-if="body.trim()" :source="body" />
                <p v-else class="u-small">在编辑区写下内容后，预览会同步显示在此处。</p>
              </div>
            </div>
          </div>

          <p class="c-field__hint">
            可以使用简单格式：行首写 <code>##</code> 加空格表示小标题，行首写 <code>&gt;</code> 表示引用，行首写 <code>-</code> 加空格表示列表，
            <code>[链接文字](网址)</code> 表示链接。为了安全，正文中可能有害的内容在显示时会被自动去除。正文最多
            {{ BODY_MAX_LENGTH.toLocaleString('en-US') }} 个字符。
          </p>
        </div>

        <!-- ===== 附件 ===== -->
        <div class="block">
          <span class="u-kicker block__k">附件</span>

          <CNotice v-if="uploadError" tone="danger">{{ uploadError }}</CNotice>

          <div
            class="drop"
            :class="{ 'drop--over': dragOver }"
            @dragenter.prevent="dragOver = true"
            @dragover.prevent="dragOver = true"
            @dragleave.prevent="dragOver = false"
            @drop.prevent="onDrop"
          >
            <AppIcon class="drop__icon" name="plus" :size="22" />
            <CButton
              variant="ghost"
              :disabled="uploading || attachmentsLeft <= 0"
              @click="fileInput?.click()"
            >
              {{ uploading ? '上传中…' : '选择文件' }}
            </CButton>
            <span class="u-small drop__hint">
              也可以把文件拖到此处。支持的格式：{{ CARD_FILE_EXTENSIONS.join(' / ') }}，每个文件不超过 20 MB，
              每篇战报最多 {{ MAX_ATTACHMENTS }} 个附件（已添加 {{ attachmentCount }} 个）。其他人需要登录后才能下载附件。
            </span>
            <!-- 真正的控件是上面的「选择文件」按钮（click() 代打开文件框），这个 input 只是载体：
                 `u-hidden` 让它退成 1px，所以同时摘出无障碍树与 Tab 序（同 MyCardDetailView） -->
            <input
              ref="fileInput"
              class="u-hidden"
              type="file"
              multiple
              tabindex="-1"
              aria-hidden="true"
              :accept="accept"
              @change="onPickFile"
            />
          </div>

          <ul v-if="attachmentCount" class="files">
            <li v-for="file in attachments" :key="file.id" class="file">
              <span class="file__grow">
                <span class="file__name">{{ file.original_name }}</span>
                <span class="file__size">{{ sizeText(file.size) }}</span>
              </span>
              <CButton variant="text" @click="onRemoveAttachment(file.id)">移除</CButton>
            </li>
            <li v-for="(file, index) in staged" :key="'s' + index" class="file">
              <span class="file__grow">
                <span class="file__name">{{ file.name }}</span>
                <span class="file__size">{{ sizeText(file.size) }} · 保存战报时上传</span>
              </span>
              <CButton variant="text" @click="removeStaged(index)">移除</CButton>
            </li>
          </ul>
          <p v-else class="u-small">暂时没有添加附件。</p>

          <p class="c-field__hint">
            目前<strong>不支持</strong>把附件图片插入正文中显示：所有附件只会列在战报正文末尾的附件列表里。
          </p>
        </div>

        <div class="foot">
          <span class="u-small">
            {{
              report
                ? '保存后，你在本团的战报会替换为当前内容。'
                : '保存后会打开战报页面，之后你仍可以从那里回来继续修改。'
            }}
          </span>
          <div class="foot__acts">
            <RouterLink class="c-textlink" :to="cancelTo">取消</RouterLink>
            <CButton type="submit" :disabled="saving || uploading">
              {{ saving ? '保存中…' : report ? '保存修改' : '保存战报' }}
            </CButton>
          </div>
        </div>
      </form>
    </LoadState>
  </div>
</template>

<style scoped>
/* 双栏编辑器向版心两侧各借这么宽。阅读版式该是 800，编辑器不是：
   不借的话 1200 上每栏只剩 390px。各断点的余量都够（1200 上单侧余量 128px）。 */
.edit {
  --editor-bleed: 100px;
}

/* ==========================================================================
   三条规矩（v2 .notes）
   ========================================================================== */

.notes {
  display: grid;
  margin: var(--sp-5) 0 var(--sp-6);
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.notes__row {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--line);
}

.notes__row:last-child {
  border-bottom: 0;
}

.notes__icon {
  flex: none;
  margin-top: 2px;
  color: var(--brand-ink);
}

.notes__txt {
  margin: 0;
  font-size: var(--fs-md);
  line-height: var(--lh-read);
}

.notes__txt small {
  display: block;
  margin-top: 3px;
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-muted);
}

/* ==========================================================================
   表单分块
   ========================================================================== */

.block {
  margin-bottom: var(--sp-6);
}

.block__k {
  display: block;
  margin-bottom: var(--sp-3);
}

/* 所属团（只读） */
.lock {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  background: var(--bg-2);
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
}

.lock__title {
  font-size: var(--fs-lg);
}

.lock__link {
  margin-left: auto;
}

/* 可见范围 */
.picks {
  display: grid;
  gap: var(--sp-3);
}

.pick {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
  min-height: 44px;
  padding: var(--sp-3) var(--sp-4);
  background: var(--white);
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
  cursor: pointer;
}

.pick--on {
  border-color: var(--brand);
  box-shadow: inset 0 0 0 1px var(--brand);
}

.pick__radio {
  flex: none;
  width: 16px;
  height: 16px;
  margin: 3px 0 0;
  accent-color: var(--brand);
}

.pick__txt strong {
  display: block;
  font-size: var(--fs-base);
  font-weight: 400;
}

.pick__txt small {
  display: block;
  margin-top: 4px;
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  color: var(--ink-muted);
}

/* ==========================================================================
   编辑器（窄屏切换 / ≥1200 双栏）
   ========================================================================== */

.tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
}

.tools__gap {
  flex: 1 1 auto;
}

.editor {
  display: grid;
  gap: var(--sp-3);
}

.pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--white);
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
}

/* 窄屏：只显示当前那一栏 */
.pane--off {
  display: none;
}

.pane__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--line);
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps);
  color: var(--ink-muted);
}

.pane__area {
  flex: 1 1 auto;
  min-height: 300px;
  padding: var(--sp-4);
  color: var(--ink);
  background: transparent;
  border: 0;
  border-radius: 0;
  resize: vertical;
  font-family: var(--font-mono);
  font-size: var(--fs-base);
  line-height: 1.85;
}

.pane__area:focus {
  outline: 2px solid var(--brand);
  outline-offset: -2px;
}

.pane__preview {
  min-height: 240px;
  max-height: 460px;
  overflow: auto;
  padding: var(--sp-4);
  color: var(--read-ink);
}

/* 从文档导入：按钮 + 说明，窄屏自动折成两行 */
.import {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-3);
  margin-bottom: var(--sp-3);
}

.import__hint {
  flex: 1 1 16em;
  min-width: 0;
}

.import__notes {
  margin: 0;
  padding-left: var(--sp-5);
}

/* ==========================================================================
   附件
   ========================================================================== */

.drop {
  display: grid;
  place-items: center;
  gap: var(--sp-3);
  padding: var(--sp-6) var(--sp-4);
  text-align: center;
  background: var(--white);
  border: 1px dashed var(--line-2);
  border-radius: var(--radius);
}

.drop--over {
  border-color: var(--brand);
  background: var(--bg-3);
}

.drop__icon {
  color: var(--ink-muted);
}

.drop__hint {
  max-width: 44em;
}

.files {
  display: grid;
  gap: var(--sp-2);
  margin: var(--sp-3) 0 0;
  padding: 0;
  list-style: none;
}

.file {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.file__grow {
  flex: 1 1 12em;
  min-width: 0;
}

.file__name {
  display: block;
  font-size: var(--fs-md);
  word-break: break-all;
}

.file__size {
  display: block;
  margin-top: 2px;
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-muted);
}

/* ==========================================================================
   页脚动作条
   ========================================================================== */

.foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3) var(--sp-5);
  margin-top: var(--sp-6);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--line);
}

.foot__acts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-4);
}

/* ==========================================================================
   ≥1200：左写右预览并排（v2 双栏编辑器；阅读版式是 800，编辑器向两侧各借一点）
   ========================================================================== */

@media (min-width: 1200px) {
  .editor {
    grid-template-columns: 1fr 1fr;
    gap: var(--sp-4);
    width: calc(100% + 2 * var(--editor-bleed));
    margin-left: calc(-1 * var(--editor-bleed));
    margin-right: calc(-1 * var(--editor-bleed));
  }

  .pane--off {
    display: flex;
  }

  .pane__area {
    min-height: 430px;
  }

  .pane__preview {
    min-height: 430px;
  }

  /* 两栏都在时，「写 / 预览」切换没有意义 */
  .tools__switch {
    display: none;
  }
}
</style>
