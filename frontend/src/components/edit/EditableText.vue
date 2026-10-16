<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useEditStore } from '../../stores/edit'

const props = withDefaults(
  defineProps<{
    /** 当前值（草稿值，由 `stores/edit.ts` 给）。 */
    value: string
    /** 说明这是哪一格：`aria-label` + 聚焦时角上的小标签。 */
    label: string
    /** 与后端 `max_length` 一致。 */
    max: number
    /** 多行（对应后端的长文本字段）。 */
    multiline?: boolean
    /** 兼容旧调用；原地编辑不再需要行数。 */
    rows?: number
    /** 压在深色图上时给 `dark`。 */
    tone?: 'light' | 'dark'
    /** 后端回来的字段级错误。 */
    error?: string
    placeholder?: string
    /** 贴在一行文字里（页脚那种），不占满整行。 */
    inline?: boolean
    /** 根元素标签。默认 `span`；顶替页面标题时传 `h1`/`h2`。 */
    as?: string
    /**
     * 「裸」模式：平时不描框、只在文字下画一条点状下划线（用在按钮文字、胶囊里的字这类
     * 本身已经有边框的地方，避免框中框），聚焦时才描边。
     */
    bare?: boolean
  }>(),
  { multiline: false, rows: 3, tone: 'light', error: '', placeholder: '', inline: false, as: 'span', bare: false },
)

const emit = defineEmits<{ 'update:value': [string] }>()

const edit = useEditStore()
const box = ref<HTMLElement | null>(null)
const focused = ref(false)
const composing = ref(false)
/** 聚焦那一刻的值，Escape 用它还原。 */
let valueAtFocus = ''

/** 浏览器认不认 `plaintext-only`（Firefox 136 之前不认，回落到 true + 粘贴拦截）。 */
const PLAINTEXT_SUPPORTED = (() => {
  if (typeof document === 'undefined') return true
  const probe = document.createElement('div')
  probe.contentEditable = 'plaintext-only'
  return probe.contentEditable === 'plaintext-only'
})()
const editableAttr = PLAINTEXT_SUPPORTED ? 'plaintext-only' : 'true'

const overLimit = computed(() => props.value.length > props.max)

/** 把「正在改哪一格、几个字」报给保存条（聚焦中才报，字数随输入更新）。 */
function report(): void {
  if (!focused.value) return
  edit.focusField = { label: props.label, length: props.value.length, max: props.max }
}
watch(() => props.value, report)
onBeforeUnmount(() => {
  if (edit.focusField?.label === props.label) edit.focusField = null
})

function normalize(raw: string): string {
  let text = raw.replace(/\r\n?/g, '\n')
  // Chrome 在最后一行后面会多补一个换行，读出来去掉
  if (text.endsWith('\n')) text = text.slice(0, -1)
  if (!props.multiline) text = text.replace(/\n+/g, ' ')
  return text
}

function readDom(): string {
  return normalize(box.value?.innerText ?? '')
}

/** 只在外部值与 DOM 不一致时回写（放弃草稿、保存后刷新），避免打断光标。 */
function syncDom(): void {
  const el = box.value
  if (!el || composing.value) return
  if (readDom() !== props.value) el.textContent = props.value
}

onMounted(syncDom)
watch(() => props.value, syncDom)

function commit(): void {
  if (composing.value) return
  let text = readDom()
  if (text.length > props.max) {
    text = text.slice(0, props.max)
    if (box.value) {
      box.value.textContent = text
      placeCaretAtEnd(box.value)
    }
  }
  if (text !== props.value) emit('update:value', text)
}

function placeCaretAtEnd(el: HTMLElement): void {
  const selection = window.getSelection()
  if (!selection) return
  const range = document.createRange()
  range.selectNodeContents(el)
  range.collapse(false)
  selection.removeAllRanges()
  selection.addRange(range)
}

function onBeforeInput(event: InputEvent): void {
  if (composing.value) return
  // 超限：只挡「插入」类操作，删除与替换选区照常
  const inserting = event.inputType.startsWith('insert')
  if (!inserting) return
  const el = box.value
  if (!el) return
  const selected = window.getSelection()?.toString().length ?? 0
  const incoming = event.data?.length ?? (event.inputType === 'insertParagraph' ? 1 : 0)
  if (readDom().length - selected + incoming > props.max) {
    event.preventDefault()
    return
  }
  if (event.inputType === 'insertParagraph' || event.inputType === 'insertLineBreak') {
    if (!props.multiline) {
      // 单行：Enter = 完成
      event.preventDefault()
      el.blur()
    }
  }
}

function onInput(): void {
  if (composing.value) return
  commit()
}

function onCompositionStart(): void {
  composing.value = true
}

function onCompositionEnd(): void {
  composing.value = false
  commit()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    if (box.value) box.value.textContent = valueAtFocus
    emit('update:value', valueAtFocus)
    box.value?.blur()
  }
}

/** 老浏览器（不认 plaintext-only）的粘贴：只取纯文本手工插入。 */
function onPaste(event: ClipboardEvent): void {
  if (PLAINTEXT_SUPPORTED) return
  event.preventDefault()
  const text = event.clipboardData?.getData('text/plain') ?? ''
  const selection = window.getSelection()
  if (!selection || !selection.rangeCount) return
  const range = selection.getRangeAt(0)
  range.deleteContents()
  range.insertNode(document.createTextNode(props.multiline ? text : text.replace(/\n+/g, ' ')))
  range.collapse(false)
  selection.removeAllRanges()
  selection.addRange(range)
  commit()
}

function onFocus(): void {
  focused.value = true
  valueAtFocus = props.value
  report()
}

function onBlur(): void {
  focused.value = false
  composing.value = false
  if (edit.focusField?.label === props.label) edit.focusField = null
  void nextTick(commit)
}
</script>

<template>
  <component
    :is="as"
    class="ed"
    :class="['ed--' + tone, { 'ed--inline': inline, 'ed--bare': bare, 'ed--focus': focused, 'ed--error': error || overLimit }]"
  >
    <span
      ref="box"
      class="ed__box"
      data-edit
      role="textbox"
      :contenteditable="editableAttr"
      :aria-label="label"
      :aria-multiline="multiline ? 'true' : 'false'"
      :aria-invalid="error || overLimit ? 'true' : undefined"
      :data-placeholder="placeholder || label"
      spellcheck="false"
      @beforeinput="onBeforeInput"
      @input="onInput"
      @compositionstart="onCompositionStart"
      @compositionend="onCompositionEnd"
      @keydown="onKeydown"
      @paste="onPaste"
      @focus="onFocus"
      @blur="onBlur"
    ></span>
    <span v-if="error" class="ed__err">{{ error }}</span>
  </component>
</template>

<style scoped>
/* 根元素拿的是页面原文字的类名（字号/字重/行高/颜色都从那里来）；
   这里只负责「可编辑」的提示描边与角标，不改任何排版。 */
.ed {
  position: relative;
  display: block;
}

.ed--inline {
  display: inline-block;
  max-width: 100%;
}

/* 控件本体：inline-block 收缩到文字本身的宽度（框贴着字，不按整栏画）；
   描边用 outline + 外扩 3px：不占布局、不改行高，和字之间留一口气。 */
.ed__box {
  display: inline-block;
  min-width: 1.5em;
  max-width: 100%;
  min-height: 1em;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  cursor: text;
  border-radius: 2px;
  outline: 1px dashed var(--ed-line-rest);
  outline-offset: 3px;
  transition: outline-color 0.12s;
  /* 聚焦时浏览器自动滚入视野：给 sticky 页头与底部保存条各让出一段 */
  scroll-margin: 88px 0 150px;
}

.ed__box:hover {
  outline: 1px solid var(--ed-line-hover);
}

.ed__box:focus {
  outline: 2px solid var(--ed-line-focus);
}

.ed--error > .ed__box,
.ed--error > .ed__box:focus {
  outline: 2px solid var(--danger);
}

/* 裸模式：只画点状下划线，聚焦才描边（按钮里的字、胶囊里的字） */
.ed--bare > .ed__box {
  outline: none;
  text-decoration: underline dotted;
  text-decoration-color: var(--ed-line-hover);
  text-underline-offset: 3px;
}

.ed--bare > .ed__box:focus {
  outline: 2px solid var(--ed-line-focus);
  text-decoration: none;
}

/* 空值占位：显示这一格的名字，不占真实文本 */
.ed__box:empty::before {
  content: attr(data-placeholder);
  opacity: 0.45;
  pointer-events: none;
}

/* 浅色底：品牌墨绿系；深色底（压在图上）：白系。平时那圈虚线只给 30–40% 的量，
   不让整页变成一堆表单格；悬停变实线、聚焦描粗才是「这里在改」的信号 */
.ed--light {
  --ed-line-rest: color-mix(in srgb, var(--brand-ink) 26%, transparent);
  --ed-line-hover: var(--brand-ink);
  --ed-line-focus: var(--brand-ink);
}

.ed--dark {
  --ed-line-rest: color-mix(in srgb, var(--on-dark) 34%, transparent);
  --ed-line-hover: var(--on-dark);
  --ed-line-focus: var(--on-dark);
}

.ed__err {
  display: block;
  margin-top: 4px;
  font-family: var(--font-sans);
  font-size: var(--fs-2xs);
  font-weight: 400;
  letter-spacing: var(--ls-caps-sm);
  line-height: 1.4;
  text-align: left;
  text-shadow: none;
}

.ed--light .ed__err {
  color: var(--danger);
}

/* 深色底上的红字对比度不够，换成白字 + 红底的小条 */
.ed--dark .ed__err {
  display: inline-block;
  padding: 1px var(--sp-2);
  color: var(--on-dark);
  background: var(--danger);
  border-radius: var(--radius);
}
</style>
