<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export interface TabItem {
  /** 唯一键，也是 hash 值（`#members`）。 */
  key: string
  label: string
  /** 右侧小计数，undefined 不显示。 */
  count?: number
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    items: TabItem[]
    /** 与 hash / 地址栏同步。 */
    hashSync?: boolean
    /** 标签条的无障碍名字（`aria-label`）。 */
    ariaLabel?: string
  }>(),
  { hashSync: false, ariaLabel: '标签' },
)

const model = defineModel<string>({ required: true })

const route = useRoute()
const router = useRouter()
const root = ref<HTMLElement | null>(null)

const enabled = computed(() => props.items.filter((t) => !t.disabled))

function select(key: string): void {
  if (key === model.value) return
  model.value = key
  if (props.hashSync) void router.replace({ hash: '#' + key })
}

/** 把焦点挪到某个标签上（roving tabindex 要求焦点跟着选中项走）。 */
function focusTab(key: string): void {
  void nextTick(() => {
    const el = root.value?.querySelector<HTMLElement>('[data-tab="' + CSS.escape(key) + '"]')
    if (!el) return
    // `preventScroll` + 自己滚：默认的 focus 滚动会连纵向一起动（这条标签条是吸顶的，
    // 页面跟着跳一下很突兀）。`nearest / nearest` 只把被裁掉的那枚横向拉进视野。
    el.focus({ preventScroll: true })
    el.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  })
}

// --------------------------------------------------------------------------
// 两端渐隐提示（只在真的横向溢出时出现）
// --------------------------------------------------------------------------

const fadeStart = ref(false)
const fadeEnd = ref(false)

function updateFade(): void {
  const el = root.value
  if (!el) return
  const max = el.scrollWidth - el.clientWidth
  fadeStart.value = el.scrollLeft > 1
  fadeEnd.value = max > 1 && el.scrollLeft < max - 1
}

let observer: ResizeObserver | null = null

onMounted(() => {
  updateFade()
  if (typeof ResizeObserver !== 'undefined' && root.value) {
    observer = new ResizeObserver(updateFade)
    observer.observe(root.value)
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
})

/** 标签增减（身份判完之后「管理」「评价」才出现）也要重算一次。 */
watch(() => props.items.length, () => void nextTick(updateFade))

function move(step: number): void {
  const list = enabled.value
  if (list.length === 0) return
  const at = list.findIndex((t) => t.key === model.value)
  const next = list[(at + step + list.length) % list.length]
  select(next.key)
  focusTab(next.key)
}

function jump(to: 'first' | 'last'): void {
  const list = enabled.value
  if (list.length === 0) return
  const next = to === 'first' ? list[0] : list[list.length - 1]
  select(next.key)
  focusTab(next.key)
}

/** 进页 / 前进后退时，hash 指到哪一个标签就跟过去。 */
watch(
  () => route.hash,
  (hash) => {
    if (!props.hashSync) return
    const key = hash.replace(/^#/, '')
    if (key && key !== model.value && enabled.value.some((t) => t.key === key)) model.value = key
  },
  { immediate: true },
)
</script>

<template>
  <div
    ref="root"
    class="c-tabs"
    :class="{ 'c-tabs--fade-s': fadeStart, 'c-tabs--fade-e': fadeEnd }"
    role="tablist"
    :aria-label="ariaLabel"
    @scroll.passive="updateFade"
    @keydown.left.prevent="move(-1)"
    @keydown.right.prevent="move(1)"
    @keydown.home.prevent="jump('first')"
    @keydown.end.prevent="jump('last')"
  >
    <button
      v-for="tab in items"
      :id="'tab-' + tab.key"
      :key="tab.key"
      class="c-tabs__item"
      type="button"
      role="tab"
      :aria-controls="'panel-' + tab.key"
      :data-tab="tab.key"
      :aria-selected="tab.key === model ? 'true' : 'false'"
      :tabindex="tab.key === model ? 0 : -1"
      :disabled="tab.disabled"
      @click="select(tab.key)"
    >
      {{ tab.label }}
      <span v-if="tab.count !== undefined" class="c-tabs__count">{{ tab.count }}</span>
    </button>
  </div>
</template>

<style scoped>
.c-tabs {
  display: flex;
  gap: var(--sp-5);
  overflow-x: auto;
  border-bottom: 1px solid var(--line);
  scrollbar-width: none;
}

.c-tabs::-webkit-scrollbar {
  display: none;
}

/* 两端渐隐：滚动条藏了，得有别的办法说「这条还能往这边滑」。
   用 mask 而不是压一层底色的渐变 —— 标签条在不同页面底色不一样（吸顶时是 --bg），
   mask 不需要知道背后是什么颜色。`--sp-6` 当渐隐宽度，不写死像素。 */
.c-tabs--fade-s {
  -webkit-mask-image: linear-gradient(to right, transparent 0, var(--ink) var(--sp-6));
  mask-image: linear-gradient(to right, transparent 0, var(--ink) var(--sp-6));
}

.c-tabs--fade-e {
  -webkit-mask-image: linear-gradient(
    to right,
    var(--ink) calc(100% - var(--sp-6)),
    transparent 100%
  );
  mask-image: linear-gradient(to right, var(--ink) calc(100% - var(--sp-6)), transparent 100%);
}

.c-tabs--fade-s.c-tabs--fade-e {
  -webkit-mask-image: linear-gradient(
    to right,
    transparent 0,
    var(--ink) var(--sp-6),
    var(--ink) calc(100% - var(--sp-6)),
    transparent 100%
  );
  mask-image: linear-gradient(
    to right,
    transparent 0,
    var(--ink) var(--sp-6),
    var(--ink) calc(100% - var(--sp-6)),
    transparent 100%
  );
}

.c-tabs__item {
  flex: none;
  min-height: 44px;
  margin-bottom: -1px;
  padding: 14px 0;
  font-size: var(--fs-sm);
  letter-spacing: var(--ls-wide);
  color: var(--ink-muted);
  background: none;
  border: 0;
  border-bottom: 1px solid transparent;
  white-space: nowrap;
  transition: color var(--dur) var(--ease);
}

.c-tabs__item:hover:not(:disabled) {
  color: var(--ink);
}

.c-tabs__item:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.c-tabs__item[aria-selected='true'] {
  color: var(--ink);
  border-bottom-color: var(--ink);
}

.c-tabs__count {
  margin-left: var(--sp-1);
  font-size: var(--fs-2xs);
  letter-spacing: 0;
  color: var(--ink-faint);
}

.c-tabs__item[aria-selected='true'] .c-tabs__count {
  color: var(--ink);
}

@media (min-width: 768px) {
  .c-tabs {
    gap: var(--sp-6);
  }
}
</style>
