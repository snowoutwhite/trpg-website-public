<script setup lang="ts">
/** 「相册」标签（v2 `game.html` 的 `#photos` 面板）。原 `/games/:id/photos` 整页并进这里。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import CButton from '../CButton.vue'
import CNotice from '../CNotice.vue'
import CPill from '../CPill.vue'
import LoadState from '../LoadState.vue'
import LazyImg from '../LazyImg.vue'
import PersonLine from './PersonLine.vue'
import {
  approvePhoto,
  checkPhotoFile,
  deletePhoto,
  fetchGamePhotos,
  rejectPhoto,
  reportPhoto,
  uploadPhoto,
  PHOTO_EXTENSIONS,
  PHOTO_MAX_PER_GAME,
  PHOTO_QUOTA_STATUSES,
  PHOTO_REPORT_REASONS,
  type Photo,
  type PhotoReportReason,
} from '../../api/gallery'
import { setPhotoFeatured } from '../../api/homeAdmin'
import type { GameDetail } from '../../api/games'
import type { SiteConfig } from '../../api/site'
import { errorText } from '../../lib/api-error'
import { formatDateTime } from '../../lib/datetime'

const props = defineProps<{
  game: GameDetail
  authenticated: boolean | null
  isGm: boolean
  isStaff: boolean
  config: SiteConfig
  loginTo: string
}>()

const emit = defineEmits<{ count: [n: number] }>()

const photos = ref<Photo[]>([])
const page = ref(1)
const hasNext = ref(false)
const loading = ref(true)
const error = ref('')

const caption = ref('')
const uploading = ref(false)
const uploadNote = ref('')
const uploadError = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
/** 多选上传的进度：已处理 / 总数。 */
const progress = ref({ done: 0, total: 0 })

const openIndex = ref(-1)
const current = computed(() => (openIndex.value >= 0 ? photos.value[openIndex.value] : null))
/** 灯箱容器（`tabindex=-1`）：打开时焦点进去，Tab 才会落在对话框里而不是背后的页面。 */
const viewerEl = ref<HTMLElement | null>(null)
/** 打开灯箱前的焦点（那张缩略图的按钮），关闭时还回去。 */
let lastFocused: HTMLElement | null = null

const reportOpen = ref(false)
const reportReason = ref<PhotoReportReason>('in_photo')
const reportText = ref('')
const reportSending = ref(false)
const viewerError = ref('')
const viewerOk = ref('')
const confirmDelete = ref(false)
const acting = ref(false)

const accept = computed(() => PHOTO_EXTENSIONS.map((e) => '.' + e).join(','))
const used = computed(
  () => photos.value.filter((p) => PHOTO_QUOTA_STATUSES.includes(p.status)).length,
)
const remaining = computed(() => Math.max(0, PHOTO_MAX_PER_GAME - used.value))

/** 上传窗口 = 结团时间 + 站级天数（与后端 `upload_window_deadline` 同口径）。 */
const deadline = computed(() => {
  if (!props.game.finished_at) return null
  const days = props.config.gallery_upload_window_days ?? 30
  return new Date(new Date(props.game.finished_at).getTime() + days * 86400_000)
})
const windowOpen = computed(() => {
  if (props.game.status !== 'finished' || !deadline.value) return false
  return Date.now() <= deadline.value.getTime()
})
const canUpload = computed(() => props.isGm && windowOpen.value && remaining.value > 0)

const MODE_TEXT: Record<string, string> = {
  public_first: '本站的照片审核方式为「默认公开」：照片上传后立即显示在相册中，如果有人举报，由站主处理。',
  review_first: '本站的照片审核方式为「公开前审核」：照片上传后需要站主审核通过，才会显示在相册中。',
  report_only: '本站的照片审核方式为「举报后下架」：照片上传后立即显示，任何登录成员都可以对照片提出下架申请。',
}
const modeText = computed(
  () => MODE_TEXT[props.config.gallery_moderation_mode ?? ''] ?? MODE_TEXT.public_first,
)

const STATUS_LABELS: Record<string, string> = {
  pending_review: '待审核',
  taken_down: '已下架',
  rejected: '已驳回',
}

async function load(reset = true): Promise<void> {
  if (props.authenticated !== true) {
    loading.value = false
    return
  }
  loading.value = reset
  error.value = ''
  try {
    // 每团上限 50 张，一次 100 条足够一屏拉完；被驳回的不占配额，所以仍留翻页。
    const data = await fetchGamePhotos(props.game.id, { page: page.value, page_size: 100 })
    photos.value = reset ? data.results : [...photos.value, ...data.results]
    hasNext.value = Boolean(data.next)
    emit('count', photos.value.length)
  } catch (e) {
    error.value = errorText(e, '相册暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
}

/** 灯箱的键盘操作：Esc 关、← → 切（没开灯箱时不拦按键）。 */
function onKey(event: KeyboardEvent): void {
  if (openIndex.value < 0) return
  if (event.key === 'Escape') closePhoto()
  else if (event.key === 'ArrowLeft') step(-1)
  else if (event.key === 'ArrowRight') step(1)
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  void load()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

function loadMore(): void {
  page.value += 1
  void load(false)
}

async function onPickFiles(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length) return

  uploadError.value = ''
  uploadNote.value = ''
  if (files.length > remaining.value) {
    uploadError.value = `本团还能传 ${remaining.value} 张，你选了 ${files.length} 张`
    return
  }

  uploading.value = true
  progress.value = { done: 0, total: files.length }
  let ok = 0
  const failures: string[] = []
  for (const file of files) {
    const problem = checkPhotoFile(file)
    if (problem) {
      failures.push(`${file.name}：${problem}`)
      progress.value = { done: progress.value.done + 1, total: files.length }
      continue
    }
    try {
      await uploadPhoto(props.game.id, file, caption.value.trim())
      ok += 1
    } catch (e) {
      // 相册这一处后端 2026-09-23 拆成独立的 `photo_not_game_gm`，文案已进全站 CODE_TEXT，
      // 原先对 `not_game_gm` 的单独覆盖随之删掉（终版表六·相册）。
      failures.push(`${file.name}：${errorText(e, '上传失败')}`)
    }
    progress.value = { done: progress.value.done + 1, total: files.length }
  }
  uploading.value = false
  caption.value = ''
  if (ok) {
    uploadNote.value = `已上传 ${ok} 张。`
    page.value = 1
    await load()
  }
  if (failures.length) uploadError.value = failures.join('；')
}

function openPhoto(index: number): void {
  // 只在「从页面进灯箱」那一次记原焦点；左右切换时 openPhoto 也会被调到，别把它覆盖成灯箱里的按钮
  if (openIndex.value < 0 && typeof document !== 'undefined') {
    lastFocused = document.activeElement as HTMLElement | null
  }
  openIndex.value = index
  reportOpen.value = false
  reportText.value = ''
  reportReason.value = 'in_photo'
  viewerError.value = ''
  viewerOk.value = ''
  confirmDelete.value = false
  void nextTick(() => viewerEl.value?.focus({ preventScroll: true }))
}

function closePhoto(): void {
  openIndex.value = -1
  // 焦点还给点开的那张缩略图：不还的话焦点掉回 <body>，下一次 Tab 从页首重新开始
  const back = lastFocused
  lastFocused = null
  void nextTick(() => back?.focus?.({ preventScroll: true }))
}

/**
 * `aria-modal` 的另一半：Tab 在灯箱内循环，不逃到背后的页面去
 * （写法照 `HomeView.vue` 的 `trapFocus`，同一套判断）。
 */
function trapFocus(event: KeyboardEvent): void {
  if (event.key !== 'Tab') return
  const root = event.currentTarget as HTMLElement | null
  if (!root) return
  const focusables = Array.from(
    root.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((el) => el.offsetParent !== null)
  if (focusables.length === 0) return
  const first = focusables[0]!
  const last = focusables[focusables.length - 1]!
  const active = document.activeElement
  if (event.shiftKey && (active === first || !root.contains(active))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (active === last || !root.contains(active))) {
    event.preventDefault()
    first.focus()
  }
}

function step(delta: number): void {
  if (openIndex.value < 0) return
  const next = openIndex.value + delta
  if (next < 0 || next >= photos.value.length) return
  openPhoto(next)
}

async function onReport(): Promise<void> {
  if (!current.value || reportSending.value) return
  reportSending.value = true
  viewerError.value = ''
  try {
    await reportPhoto(current.value.id, {
      reason: reportReason.value,
      reason_text: reportText.value.trim(),
    })
    viewerOk.value = '已经提交，站主会看到这条诉求。处理结果在「我的 · 我的举报」里。'
    reportOpen.value = false
    await load()
  } catch (e) {
    viewerError.value = errorText(e, '提交失败，请稍后再试。')
  } finally {
    reportSending.value = false
  }
}

async function run(fn: () => Promise<unknown>, okText: string): Promise<void> {
  if (acting.value) return
  acting.value = true
  viewerError.value = ''
  viewerOk.value = ''
  try {
    await fn()
    viewerOk.value = okText
    page.value = 1
    await load()
  } catch (e) {
    viewerError.value = errorText(e, '操作失败')
  } finally {
    acting.value = false
  }
}

function onDelete(): void {
  const photo = current.value
  if (!photo) return
  void run(() => deletePhoto(photo.id), '已删除。').then(() => {
    confirmDelete.value = false
    closePhoto()
  })
}

function onApprove(): void {
  const photo = current.value
  if (!photo) return
  void run(() => approvePhoto(photo.id), '已通过，照片已公开。')
}

/** 业务界面遵循后端权限与隐私约束。 */
function onFeature(featured: boolean): void {
  const photo = current.value
  if (!photo) return
  void run(
    () => setPhotoFeatured(photo.id, featured),
    featured ? '已设为首页精选。' : '已取消首页精选。',
  )
}

function onReject(): void {
  const photo = current.value
  if (!photo) return
  void run(() => rejectPhoto(photo.id, reportText.value.trim()), '已驳回。')
}

function sizeText(bytes: number): string {
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}
</script>

<template>
  <div class="gp">
    <h2 class="u-h-section gp__h">相册</h2>
    <p class="gp__sub">
      这里展示本团线下活动的照片。登录后才能查看相册，照片会按照本站设定的审核方式发布。上传时，系统会自动去掉照片里的拍摄位置等隐藏信息。
    </p>

    <!-- 游客：不请求接口（后端对游客显式 401） -->
    <CNotice v-if="authenticated !== true" title="登录后才能查看相册">
      相册中的照片拍到了真实的人。为了保护他们，本站不向未登录的访客展示这些照片，也不提供可以绕过登录直接打开照片的链接。
      <template #actions>
        <RouterLink class="c-btn c-btn--ghost" :to="loginTo">登录查看</RouterLink>
      </template>
    </CNotice>

    <template v-else>
      <p class="gp__mode">
        {{ modeText }} 如果某张照片里有你，而你希望它被撤下，请点开这张照片，点击「举报 / 我在图中，申请下架」提交申请，不需要先联系 GM。
      </p>

      <!-- 上传：只有本团 GM -->
      <section v-if="isGm" class="gp__upload">
        <div class="gp__uphead">
          <h3 class="u-h-card gp__h3">上传照片</h3>
          <span class="u-small">还可上传 {{ remaining }} 张（每团最多 {{ PHOTO_MAX_PER_GAME }} 张）</span>
        </div>

        <CNotice v-if="uploadError" tone="danger">{{ uploadError }}</CNotice>
        <CNotice v-else-if="uploadNote" tone="ok">{{ uploadNote }}</CNotice>

        <CNotice v-if="!windowOpen" tone="warn">
          <template v-if="game.status !== 'finished'">
            本团结团后才能上传照片（本团当前状态：{{ game.status_display }}）。
          </template>
          <template v-else-if="deadline">
            本团的照片上传期限已于 {{ formatDateTime(deadline.toISOString()) }} 结束，现在不能再上传照片。
          </template>
          <template v-else>本团还没有记录结团时间，因此暂时不能上传照片。</template>
        </CNotice>
        <CNotice v-else-if="remaining === 0" tone="warn">
          本团的照片已经达到 {{ PHOTO_MAX_PER_GAME }} 张的上限。如需继续上传，请先删除部分已有照片。
        </CNotice>

        <div class="gp__drop">
          <p v-if="windowOpen && deadline" class="gp__small">
            上传截止时间为 {{ formatDateTime(deadline.toISOString()) }}。支持的图片格式：
            {{ PHOTO_EXTENSIONS.join(' / ') }}，每张不超过 10 MB，每个团最多上传
            {{ PHOTO_MAX_PER_GAME }} 张。上传后，系统会自动去掉照片里的拍摄位置等隐藏信息，并生成适合浏览的小图和大图，原图仍可下载。
          </p>
          <label class="gp__label" for="gp-caption">照片说明（选填，本次选择的所有照片共用这段说明）</label>
          <input
            id="gp-caption"
            v-model="caption"
            class="c-input"
            type="text"
            maxlength="200"
            placeholder="例如：第三场的最后一幕"
          />
          <CButton class="gp__btn" :disabled="!canUpload || uploading" @click="fileInput?.click()">
            {{ uploading ? `上传中 ${progress.done} / ${progress.total}…` : '选择照片（可以一次选择多张）' }}
          </CButton>
          <!-- 视觉上藏起来（点上面那颗按钮代触发），但它仍在无障碍树里，必须有自己的名字 -->
          <input
            ref="fileInput"
            class="u-hidden"
            type="file"
            multiple
            aria-label="选择要上传的照片"
            :accept="accept"
            @change="onPickFiles"
          />
        </div>
      </section>
      <p v-else-if="game.status === 'finished'" class="gp__small gp__byline">
        相册中的照片由本团 GM 上传。如果某张照片里有你，而你希望它被撤下，请点开这张照片提交下架申请。
      </p>

      <LoadState
        :loading="loading"
        :error="error"
        :empty="!photos.length"
        empty-title="本团暂时没有照片"
        :empty-text="
          game.status === 'finished'
            ? '结团后的上传期限内，本团 GM 可以上传活动照片，上传后会显示在此处。'
            : '本团结团后，GM 才能上传活动照片。'
        "
      >
        <ul class="gp__grid">
          <li v-for="(photo, index) in photos" :key="photo.id">
            <button class="gp__thumb" type="button" @click="openPhoto(index)">
              <LazyImg :src="photo.thumbnail_url" :alt="photo.caption || '活动照片'" />
              <span v-if="photo.status !== 'public'" class="gp__flag">
                {{ STATUS_LABELS[photo.status] }}
              </span>
            </button>
          </li>
        </ul>

        <div v-if="hasNext" class="c-actions">
          <CButton variant="ghost" @click="loadMore">加载更多照片</CButton>
        </div>
      </LoadState>
    </template>

    <!-- 灯箱：预览档 1600px，原图只在点「下载原图」时才取 -->
    <div
      v-if="current"
      ref="viewerEl"
      class="gv"
      role="dialog"
      aria-modal="true"
      aria-label="照片预览"
      tabindex="-1"
      @keydown="trapFocus"
    >
      <button class="gv__bg" type="button" aria-label="关闭预览" @click="closePhoto" />
      <div class="gv__sheet">
        <div class="gv__bar">
          <span class="u-small">{{ openIndex + 1 }} / {{ photos.length }}</span>
          <CButton variant="text" @click="closePhoto">关闭</CButton>
        </div>

        <img class="gv__img" :src="current.preview_url" :alt="current.caption || '活动照片'" />

        <p v-if="current.caption" class="gv__cap">{{ current.caption }}</p>

        <div class="gv__meta">
          <PersonLine :user="current.uploader" :size="24" />
          <CPill v-if="current.status !== 'public'" tone="warn">
            {{ STATUS_LABELS[current.status] }}
          </CPill>
          <span class="u-small">{{ current.width }}×{{ current.height }}</span>
          <span class="u-small">{{ sizeText(current.size) }}</span>
          <span class="u-small">{{ formatDateTime(current.created_at) }}</span>
        </div>

        <CNotice v-if="current.taken_down_reason" tone="warn" title="站主说明">
          {{ current.taken_down_reason }}
        </CNotice>
        <CNotice v-if="viewerError" tone="danger">{{ viewerError }}</CNotice>
        <CNotice v-else-if="viewerOk" tone="ok">{{ viewerOk }}</CNotice>

        <div class="c-actions gv__acts">
          <CButton variant="ghost" :disabled="openIndex <= 0" @click="step(-1)">上一张</CButton>
          <CButton variant="ghost" :disabled="openIndex >= photos.length - 1" @click="step(1)">
            下一张
          </CButton>
          <a class="c-btn c-btn--ghost" :href="current.original_url" download>下载原图</a>
          <CButton variant="ghost" @click="reportOpen = !reportOpen">
            举报 / 我在图中，申请下架
          </CButton>
          <!-- 与后端 approve/reject_photo 的准入状态一致：待审核、已下架可操作；已驳回再点回 400（缺陷 F14） -->
          <template
            v-if="isStaff && (current.status === 'pending_review' || current.status === 'taken_down')"
          >
            <CButton :disabled="acting" @click="onApprove">通过</CButton>
            <CButton variant="ghost" :disabled="acting" @click="onReject">驳回</CButton>
          </template>
          <CButton
            v-if="isStaff && current.status === 'public'"
            variant="ghost"
            :disabled="acting"
            @click="onFeature(!current.is_featured)"
          >
            {{ current.is_featured ? '取消精选' : '设为精选' }}
          </CButton>
          <template v-if="current.can_delete">
            <CButton v-if="!confirmDelete" variant="danger" @click="confirmDelete = true">
              删除这张
            </CButton>
            <template v-else>
              <CButton variant="danger" :disabled="acting" @click="onDelete">确认删除</CButton>
              <CButton variant="ghost" @click="confirmDelete = false">暂不删除</CButton>
            </template>
          </template>
        </div>

        <form v-if="reportOpen" class="gv__form" novalidate @submit.prevent="onReport">
          <label class="gp__label" for="gv-reason">理由</label>
          <select id="gv-reason" v-model="reportReason" class="c-select">
            <option v-for="option in PHOTO_REPORT_REASONS" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <label class="gp__label" for="gv-text">补充说明（可留空）</label>
          <textarea
            id="gv-text"
            v-model="reportText"
            class="c-textarea"
            maxlength="2000"
            rows="3"
            placeholder="例如：照片中左起第二位是我，希望撤下这张照片。"
          ></textarea>
          <p class="gp__small">
            提交后，站主会看到这条申请并进行处理；上传照片的人不会知道是谁提交了申请。站主驳回申请时，也在此栏填写驳回理由。
          </p>
          <div class="c-actions">
            <CButton type="submit" :disabled="reportSending">
              {{ reportSending ? '提交中…' : '提交申请' }}
            </CButton>
            <CButton variant="ghost" @click="reportOpen = false">取消</CButton>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gp__h {
  margin: 0 0 var(--sp-2);
}

.gp__sub,
.gp__mode {
  max-width: 62ch;
  margin: 0 0 var(--sp-5);
  font-size: var(--fs-sm);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.gp__mode {
  padding: var(--sp-3) var(--sp-4);
  font-size: var(--fs-xs);
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.gp__upload {
  margin-bottom: var(--sp-5);
}

.gp__uphead {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-2);
}

.gp__h3 {
  margin: 0;
}

.gp__byline {
  margin-bottom: var(--sp-5);
}

.gp__drop {
  margin-top: var(--sp-3);
  padding: var(--sp-5) var(--sp-4);
  background: var(--white);
  border: 1px dashed var(--line-2);
  border-radius: var(--radius);
}

.gp__label {
  display: block;
  margin: var(--sp-4) 0 var(--sp-1);
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-wide);
  color: var(--ink-muted);
}

.gp__small {
  margin: 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.gp__btn {
  margin-top: var(--sp-4);
}

.gp__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: var(--sp-3);
  margin: var(--sp-4) 0 0;
  padding: 0;
  list-style: none;
}

@media (min-width: 768px) {
  .gp__grid {
    grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
    gap: var(--sp-4);
  }
}

.gp__thumb {
  position: relative;
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;
  padding: 0;
  overflow: hidden;
  background: var(--thumb-bg);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  cursor: pointer;
  transition: box-shadow var(--dur) var(--ease);
}

.gp__thumb:hover {
  box-shadow: var(--shadow-1);
}

.gp__thumb :deep(img) {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.gp__flag {
  position: absolute;
  left: 0;
  bottom: 0;
  padding: 2px var(--sp-2);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps);
  color: var(--on-dark);
  background: var(--veil-tag);
}

/* —— 灯箱 —— */
.gv {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: var(--sp-3);
  overflow-y: auto;
}

/* 容器只是焦点的落脚点（打开时 focus 它），不用画一圈铺满屏幕的轮廓 */
.gv:focus {
  outline: none;
}

.gv__bg {
  position: fixed;
  inset: 0;
  padding: 0;
  border: 0;
  background: var(--overlay-scrim-2);
  cursor: pointer;
}

.gv__sheet {
  position: relative;
  width: 100%;
  max-width: 900px;
  margin: auto;
  padding: var(--sp-4);
  background: var(--white);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-2);
}

.gv__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-bottom: var(--sp-3);
}

.gv__img {
  display: block;
  width: 100%;
  max-height: 60vh;
  object-fit: contain;
  background: var(--thumb-bg);
  border-radius: var(--radius);
}

.gv__cap {
  margin: var(--sp-3) 0 0;
  font-size: var(--fs-md);
  line-height: var(--lh-body);
}

.gv__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-3);
  margin-top: var(--sp-2);
}

.gv__acts {
  margin-top: var(--sp-3);
}

.gv__form {
  margin-top: var(--sp-4);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--line);
}

@media (min-width: 1200px) {
  /* 宽屏上说明文字放宽到 72ch（62ch 在 1440 以上显得过窄） */
  .gp__sub,
  .gp__mode {
    max-width: 72ch;
  }
}
</style>
