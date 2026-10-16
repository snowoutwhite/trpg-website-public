<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, onBeforeUnmount, ref } from 'vue'
import EditableText from './EditableText.vue'
import { checkSiteImage, SITE_IMAGE_EXTENSIONS } from '../../api/homeAdmin'
import { useEditStore } from '../../stores/edit'

const props = withDefaults(
  defineProps<{
    /** 打哪个接口。 */
    kind: 'preset' | 'quick'
    id: number
    /** 说明换的是哪张图，进 `aria-label`。 */
    label: string
    /** 图片替代文字（`image_alt`，走草稿，要点保存）。 */
    alt: string
    altMax: number
    tone?: 'light' | 'dark'
    /** 整张图都是点击热区（图上没有压文字时用）。 */
    cover?: boolean
    /** 徽标与替代文字胶囊距顶部的距离（首屏顶部压着 sticky 页头，要让出页头高度）。 */
    offsetTop?: string
    /** 距左右两边的距离（全出血的首屏用 `--pad` 与版心对齐，卡片里的图用默认 8px）。 */
    offsetX?: string
  }>(),
  { tone: 'light', cover: false, offsetTop: 'var(--sp-2)', offsetX: 'var(--sp-2)' },
)

const emit = defineEmits<{ 'update:alt': [string] }>()

const edit = useEditStore()
const input = ref<HTMLInputElement | null>(null)
/** 客户端预检不过的那句话（没发请求）。 */
const localError = ref('')
/** 上传期间的本地预览。 */
const preview = ref('')
const dragOver = ref(false)

const busyKey = computed(() => props.kind + '-' + props.id)
const busy = computed(() => edit.uploading === busyKey.value)
const remoteError = computed(() => edit.imageErrors[busyKey.value] ?? '')
const errorText = computed(() => localError.value || remoteError.value)
const accept = computed(() => SITE_IMAGE_EXTENSIONS.map((e) => '.' + e).join(','))

function clearPreview(): void {
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''
}

onBeforeUnmount(clearPreview)

async function take(file: File | null): Promise<void> {
  localError.value = ''
  if (edit.imageErrors[busyKey.value]) {
    const next = { ...edit.imageErrors }
    delete next[busyKey.value]
    edit.imageErrors = next
  }
  if (!file || busy.value) return
  const problem = checkSiteImage(file)
  if (problem) {
    localError.value = problem
    return
  }
  clearPreview()
  preview.value = URL.createObjectURL(file)
  const ok = await edit.uploadImage(props.kind, props.id, file)
  // 成功：新图已经随 `home.load()` 刷进页面，预览可以撤；失败：撤掉预览让原图露出来
  clearPreview()
  if (!ok && !remoteError.value) localError.value = '图片上传失败，请稍后再试。'
}

function onPick(event: Event): void {
  const el = event.target as HTMLInputElement
  const file = el.files?.[0] ?? null
  el.value = ''
  void take(file)
}

function onDrop(event: DragEvent): void {
  dragOver.value = false
  void take(event.dataTransfer?.files?.[0] ?? null)
}
</script>

<template>
  <div
    class="ei"
    :class="['ei--' + tone, { 'ei--cover': cover, 'is-busy': busy, 'is-drag': dragOver }]"
    :style="{ '--ei-top': offsetTop, '--ei-x': offsetX }"
    @dragover.prevent="dragOver = true"
    @dragleave="dragOver = false"
    @drop.prevent="onDrop"
  >
    <img v-if="preview" class="ei__preview" :src="preview" alt="" />

    <!-- 整图热区：透明按钮铺满，悬停时压暗并浮出中央提示 -->
    <button
      v-if="cover"
      class="ei__hit"
      type="button"
      :aria-label="label + '：更换图片'"
      :disabled="busy"
      @click="input?.click()"
    >
      <span class="ei__hitpill">{{ busy ? '正在上传…' : '更换图片' }}</span>
    </button>

    <!-- 右上角常驻徽标 -->
    <button
      class="ei__badge"
      type="button"
      :aria-label="label + '：更换图片'"
      :title="'选好后立即生效，与底部的「保存」无关'"
      :disabled="busy"
      @click="input?.click()"
    >
      <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
        <path
          d="M2 5.5A1.5 1.5 0 0 1 3.5 4H5l1-1.5h4L11 4h1.5A1.5 1.5 0 0 1 14 5.5v6A1.5 1.5 0 0 1 12.5 13h-9A1.5 1.5 0 0 1 2 11.5z"
          fill="none"
          stroke="currentColor"
          stroke-width="1.3"
        />
        <circle cx="8" cy="8.5" r="2.3" fill="none" stroke="currentColor" stroke-width="1.3" />
      </svg>
      <span>{{ busy ? '正在上传…' : '更换图片' }}</span>
    </button>

    <!-- 左上角：替代文字 -->
    <span class="ei__alt">
      <span class="ei__altlabel">替代文字</span>
      <EditableText
        inline
        bare
        class="ei__altbox"
        :value="alt"
        :label="label + '：图片替代文字'"
        :max="altMax"
        :tone="tone"
        placeholder="给看不到图的人一句描述"
        @update:value="emit('update:alt', $event)"
      />
    </span>

    <p v-if="errorText" class="ei__err" role="alert">{{ errorText }}</p>

    <!-- 隐藏的真 input：不进 Tab 序、不进无障碍树 -->
    <input
      ref="input"
      class="ei__file"
      data-edit
      type="file"
      :accept="accept"
      tabindex="-1"
      aria-hidden="true"
      @change="onPick"
    />
  </div>
</template>

<style scoped>
/* 覆盖层自身不吃事件（下面压着的文字控件要能点），只有各个按钮吃 */
.ei {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
  border-radius: inherit;
  font-family: var(--font-sans);
  text-shadow: none;
}

.ei--light {
  --ei-ink: var(--brand-ink);
  --ei-bg: var(--white);
  --ei-line: var(--brand-ink);
}

.ei--dark {
  --ei-ink: var(--on-dark);
  --ei-bg: var(--scrim-3);
  --ei-line: var(--on-dark);
}

.ei__preview {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: inherit;
}

.ei__hit {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  padding: 0;
  margin: 0;
  border: 0;
  border-radius: inherit;
  background: transparent;
  color: var(--on-dark);
  cursor: pointer;
  pointer-events: auto;
  transition: background 0.15s;
}

.ei__hit:hover,
.ei__hit:focus-visible,
.is-drag .ei__hit,
.is-busy .ei__hit {
  background: rgb(16 38 32 / 0.6);
}

.ei__hit:focus-visible {
  outline: 2px solid var(--on-dark);
  outline-offset: -4px;
}

.ei__hitpill {
  padding: 8px 14px;
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--brand-ink);
  background: var(--white);
  border-radius: 999px;
  opacity: 0;
  transform: translateY(4px);
  transition:
    opacity 0.15s,
    transform 0.15s;
}

.ei__hit:hover .ei__hitpill,
.ei__hit:focus-visible .ei__hitpill,
.is-drag .ei__hitpill,
.is-busy .ei__hitpill {
  opacity: 1;
  transform: none;
}

/* 右上角徽标 */
.ei__badge {
  position: absolute;
  top: var(--ei-top, var(--sp-2));
  right: var(--ei-x, var(--sp-2));
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 28px;
  padding: 3px 9px;
  margin: 0;
  font: inherit;
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps-sm);
  line-height: 1.4;
  color: var(--ei-ink);
  background: var(--ei-bg);
  border: 1px solid var(--ei-line);
  border-radius: 999px;
  cursor: pointer;
  pointer-events: auto;
  box-shadow: 0 1px 4px rgb(0 0 0 / 0.18);
}

.ei__badge:hover,
.ei__badge:focus-visible {
  color: var(--on-dark);
  background: var(--brand-ink);
  border-color: var(--brand-ink);
  outline: none;
}

.ei--dark .ei__badge:hover,
.ei--dark .ei__badge:focus-visible {
  color: var(--brand-ink);
  background: var(--on-dark);
  border-color: var(--on-dark);
}

/* 整图热区悬停时中央已经有「更换图片」，角上的徽标让开，不重复出现两次 */
.ei--cover:has(.ei__hit:hover) .ei__badge {
  opacity: 0;
}

.ei__badge:disabled {
  cursor: progress;
  opacity: 0.8;
}

/* 左上角：替代文字胶囊 */
.ei__alt {
  position: absolute;
  top: var(--ei-top, var(--sp-2));
  left: var(--ei-x, var(--sp-2));
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  max-width: calc(100% - 140px);
  min-height: 28px;
  padding: 3px 9px;
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps-sm);
  line-height: 1.4;
  color: var(--ei-ink);
  background: var(--ei-bg);
  border: 1px solid var(--ei-line);
  border-radius: 999px;
  pointer-events: auto;
}

.ei__altlabel {
  opacity: 0.7;
  white-space: nowrap;
}

.ei__altbox {
  min-width: 6em;
}

.ei__err {
  position: absolute;
  left: var(--sp-2);
  bottom: var(--sp-2);
  margin: 0;
  padding: 3px 9px;
  font-size: var(--fs-2xs);
  line-height: 1.4;
  color: var(--on-dark);
  background: var(--danger);
  border-radius: 999px;
  pointer-events: auto;
}

.ei__file {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}
</style>
