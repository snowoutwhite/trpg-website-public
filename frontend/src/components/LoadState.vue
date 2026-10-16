<script setup lang="ts">
/**
 * 列表/详情页的三种「还没有内容」状态：载入中、出错、空。
 * 三种都不成立时才渲染默认插槽，免得每个页面各写一遍 v-if 链。
 *
 * v2 改造（差距分析 §2.5）：**三态逻辑一个字没动**，只换视觉 ——
 * 空态从「一段批注」换成 v2 `recruit.html .empty` 的虚线框（`CEmpty.vue`），
 * 载入中从「左竖线小标签」换成居中的一行弱字。props 与旧骨架完全一致，现有 view 不用改。
 *
 * 出错与空态是两回事：出错是「没取到」（可重试），空态是「确实没有」（给下一步出口）。
 * 页面想在空态里放按钮，用 `empty-actions` 插槽。
 *
 * **首次载入与刷新是两回事**（v2 上手检查 2026-09-23）：调用方的 `load()` 每次重新拉数据
 * （翻页、换筛选、标已读、拨开关）都会把 `loading` 置真。原先这里一律把插槽内容卸掉、
 * 换成一行「载入中…」再重新挂上，用户看到的就是「内容消失 → 闪一下 → 重画」，
 * 页面高度还跟着塌一次。现在只有**第一次**（还没成功渲染过内容）才显示占位；
 * 之后的每次刷新都把旧内容原地留着，只在页面顶端压一条细进度线（固定定位，不占版面）。
 * `settled` 在 `loading` 第一次回落时置真，之后不再回退 —— 组件被 `v-if` 重挂时自然归零。
 */
import { ref, watch } from 'vue'
import CEmpty from './CEmpty.vue'

const props = withDefaults(
  defineProps<{
    loading: boolean
    error?: string
    empty?: boolean
    emptyText?: string
    loadingText?: string
    /** 空态标题；不给就只显示 emptyText。 */
    emptyTitle?: string
  }>(),
  {
    error: '',
    empty: false,
    emptyText: '暂时没有可以显示的内容。',
    loadingText: '正在加载，请稍候…',
    emptyTitle: '',
  },
)

/** 是否已经有过一次「载入结束」：为真之后刷新不再卸载内容。 */
const settled = ref(!props.loading)
watch(
  () => props.loading,
  (value) => {
    if (!value) settled.value = true
  },
)
</script>

<template>
  <p v-if="loading && !settled" class="c-loadstate" role="status">{{ loadingText }}</p>
  <p v-else-if="error" class="c-note c-note--error" role="alert">{{ error }}</p>
  <template v-else>
    <span
      v-if="loading"
      class="c-loadstate__bar"
      role="status"
      aria-label="正在刷新页面内容"
      aria-live="polite"
    ></span>
    <CEmpty v-if="empty" :title="emptyTitle" :text="emptyText">
      <template v-if="$slots['empty-actions']" #actions><slot name="empty-actions" /></template>
    </CEmpty>
    <slot v-else />
  </template>
</template>

<style scoped>
.c-loadstate {
  margin: var(--sp-7) 0;
  font-size: var(--fs-md);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-muted);
  text-align: center;
}

/* 刷新中的细进度线：固定在视口顶端，不进文档流，所以内容一个像素都不动。
   压过 sticky 页头（AppHeader 是 30），让给灯箱与规则覆盖层（50）和编辑态保存条（60）。 */
.c-loadstate__bar {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 40;
  width: 100%;
  height: 2px;
  pointer-events: none;
  background: linear-gradient(90deg, transparent 0%, var(--brand-ink) 40%, var(--brand-ink) 60%, transparent 100%);
  background-size: 50% 100%;
  animation: c-loadstate-slide 1s linear infinite;
}

@keyframes c-loadstate-slide {
  from {
    background-position: -50% 0;
  }

  to {
    background-position: 150% 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .c-loadstate__bar {
    animation: none;
    background: var(--brand-ink);
  }
}
</style>
