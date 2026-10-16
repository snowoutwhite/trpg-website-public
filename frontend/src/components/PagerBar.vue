<script setup lang="ts">
/** 上一页 / 下一页 + 计数。列表页共用，样式与资源区那条一致。 */
defineProps<{ page: number; count: number; hasNext: boolean }>()
const emit = defineEmits<{ (event: 'go', page: number): void }>()
</script>

<template>
  <div v-if="hasNext || page > 1" class="pager">
    <button class="c-btn c-btn--ghost" type="button" :disabled="page <= 1" @click="emit('go', page - 1)">
      上一页
    </button>
    <span class="pager__at u-label">第 {{ page }} 页 · 共 {{ count }} 条</span>
    <button class="c-btn c-btn--ghost" type="button" :disabled="!hasNext" @click="emit('go', page + 1)">
      下一页
    </button>
  </div>
</template>

<style scoped>
.pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3);
  margin-top: var(--sp-5);
}

.pager__at {
  flex: 1 1 auto;
  text-align: center;
}
</style>
