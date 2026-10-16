<script setup lang="ts">
/**
 * 用户小名牌：头像（没有就用昵称首字盖一枚朱砂小章）+ 昵称 + GM 标记。
 * 只接受 PublicUser（id / nickname / avatar / is_gm）——后端唯一被审计过的公开表示，
 * 页面里不要再自己拼用户字段，免得把邮箱之类带出来。
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { PublicUser } from '../api/site'

const props = withDefaults(
  defineProps<{ user: PublicUser; size?: number; link?: boolean; showGm?: boolean }>(),
  { size: 28, link: true, showGm: true },
)

const initial = computed(() => props.user.nickname.slice(0, 1) || '·')
const box = computed(() => ({ width: props.size + 'px', height: props.size + 'px' }))
</script>

<template>
  <component
    :is="link ? RouterLink : 'span'"
    :to="link ? '/users/' + user.id : undefined"
    class="chip"
    :class="{ 'chip--link': link }"
  >
    <img v-if="user.avatar" class="chip__face" :style="box" :src="user.avatar" alt="" />
    <span v-else class="chip__face chip__face--blank" :style="box" aria-hidden="true">
      {{ initial }}
    </span>
    <span class="chip__name">{{ user.nickname }}</span>
    <span v-if="showGm && user.is_gm" class="c-tag c-tag--gm">GM</span>
  </component>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  min-height: 40px;
  color: var(--ink);
  text-decoration: none;
  min-width: 0;
}

.chip--link:hover .chip__name {
  color: var(--brand);
}

.chip__face {
  flex: none;
  object-fit: cover;
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
}

.chip__face--blank {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--brand);
  color: var(--on-brand);
  font-family: var(--font-sans);
  font-size: 0.8em;
  font-weight: 700;
  line-height: 1;
}

.chip__name {
  font-family: var(--font-sans);
  font-size: var(--fs-md);
  letter-spacing: 0.06em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
