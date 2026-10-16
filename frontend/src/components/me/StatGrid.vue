<script setup lang="ts">
/**
 * 只读统计块（v2 `me.html` 的 `.stats` / `.stat`）：眼标 + 大数字 + 一句注脚。
 * 玩家卡与 GM 卡的「团次数 / 被评价次数 / 赞级别」用它。
 *
 * 口径提醒：`reviews_received` / `likes` / `dislikes` 在未达公布阈值（或站主关掉赞功能）
 * 时后端回 **null**，调用方要把它显示成「未公布」，**不许把 null 直接插进模板**
 * （会渲染成空白，看上去像「0 条」）。本组件只管排版，判空在调用方。
 */
defineProps<{
  items: {
    key: string
    /** 眼标。 */
    kicker: string
    /** 已经是人话的值：数字或「未公布」。 */
    value: string
    note?: string
  }[]
}>()
</script>

<template>
  <div class="stats">
    <div v-for="item in items" :key="item.key" class="stat">
      <span class="u-kicker">{{ item.kicker }}</span>
      <b class="stat__value">{{ item.value }}</b>
      <span v-if="item.note" class="stat__note u-small">{{ item.note }}</span>
    </div>
  </div>
</template>

<style scoped>
.stats {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-3);
  max-width: 860px;
}

.stat {
  padding: var(--sp-4);
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.stat__value {
  display: block;
  margin-top: var(--sp-2);
  font-size: var(--fs-h-section);
  font-weight: 400;
  line-height: var(--lh-tight);
  letter-spacing: var(--ls-section);
}

.stat__note {
  display: block;
  margin-top: var(--sp-2);
  line-height: var(--lh-body);
  color: var(--ink-muted);
}

@media (min-width: 768px) {
  .stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
