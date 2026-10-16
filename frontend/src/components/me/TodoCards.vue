<script setup lang="ts">
/**
 * 待办卡片网格（v2 `me.html` 的 `.todo-grid` / `.todo-card`）。
 * 数据来自 `lib/todos.ts`，与首页「我的当下」**同一份**；这里只负责摆。
 */
import { RouterLink } from 'vue-router'
import CEmpty from '../CEmpty.vue'
import type { TodoCard } from '../../lib/todos'

defineProps<{ cards: TodoCard[] }>()
</script>

<template>
  <div v-if="cards.length" class="todo">
    <RouterLink
      v-for="card in cards"
      :key="card.key"
      class="c-card todo__card"
      :class="card.urgent ? 'todo__card--urgent' : null"
      :to="card.to"
    >
      <span class="todo__kicker">
        <span class="u-kicker">{{ card.kicker }}</span>
        <span class="todo__days">{{ card.days }} {{ card.unit }}</span>
      </span>
      <strong class="todo__title">{{ card.title }}</strong>
      <span class="todo__small u-small">{{ card.small }}</span>
    </RouterLink>
  </div>
  <CEmpty
    v-else
    title="你目前没有待办事项"
    text="需要交的角色卡、需要填写的评价、可以上传照片的团相册，以及尚未阅读的通知，都会显示在此处。"
  />
</template>

<style scoped>
.todo {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-3);
}

.todo__card {
  display: grid;
  grid-template-rows: auto 1fr auto;
  gap: var(--sp-2);
  min-height: 150px;
  color: inherit;
  text-decoration: none;
  transition: box-shadow var(--dur) var(--ease);
}

.todo__card:hover {
  box-shadow: var(--shadow-1);
}

.todo__card--urgent {
  border-left: 3px solid var(--danger);
}

.todo__kicker {
  display: flex;
  justify-content: space-between;
  gap: var(--sp-2);
}

.todo__card--urgent .todo__kicker {
  color: var(--danger);
}

.todo__days {
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-kicker);
  color: var(--ink-faint);
}

.todo__card--urgent .todo__days {
  color: var(--danger);
}

.todo__title {
  font-size: var(--fs-lg);
  font-weight: 400;
  line-height: var(--lh-card);
}

.todo__small {
  margin-top: auto;
  line-height: var(--lh-body);
  color: var(--ink-muted);
}

@media (min-width: 768px) {
  .todo {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (min-width: 1200px) {
  .todo {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
</style>
