<script setup lang="ts">
/** 一行「人」：圆头像 + 昵称 +（可选）第二行小字。 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { PublicUser } from '../../api/site'

const props = withDefaults(
  defineProps<{
    user: PublicUser
    /** 头像边长。v2 默认 32，首屏 GM 行用 38。 */
    size?: number
    /** 第二行小字（报名顺序、身份说明…）。 */
    meta?: string
    /** 点昵称进个人空间。成排的管理行里关掉，避免整行误触跳走。 */
    link?: boolean
    /** 压在深色图上时换成浅色文字档。 */
    onDark?: boolean
  }>(),
  { size: 32, meta: '', link: true, onDark: false },
)

const initial = computed(() => props.user.nickname.slice(0, 1) || '·')
const box = computed(() => ({ width: props.size + 'px', height: props.size + 'px' }))
</script>

<template>
  <component
    :is="link ? RouterLink : 'span'"
    :to="link ? '/users/' + user.id : undefined"
    class="pl"
    :class="[link ? 'pl--link' : null, onDark ? 'pl--dark' : null]"
  >
    <img v-if="user.avatar" class="pl__face" :style="box" :src="user.avatar" alt="" />
    <span v-else class="pl__face pl__face--blank" :style="box" aria-hidden="true">
      {{ initial }}
    </span>
    <span class="pl__text">
      <span class="pl__name"><span class="pl__nick">{{ user.nickname }}</span><slot name="badge" /></span>
      <span v-if="meta || $slots.meta" class="pl__meta">{{ meta }}<slot name="meta" /></span>
    </span>
  </component>
</template>

<style scoped>
.pl {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-3);
  min-height: 44px;
  min-width: 0;
  /** 业务界面遵循后端权限与隐私约束。 */
  max-width: 100%;
  color: var(--ink);
  text-decoration: none;
}

.pl--link:hover .pl__name {
  color: var(--brand-ink);
}

.pl__face {
  flex: none;
  object-fit: cover;
  border-radius: var(--radius-pill);
  background: var(--avatar-bg);
}

/** 业务界面遵循后端权限与隐私约束。 */
.pl__face--blank {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-soft);
  font-size: 0.8em;
  line-height: 1;
}

.pl__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.pl__name {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 0;
  font-size: var(--fs-md);
  line-height: var(--lh-card);
}

/** 业务界面遵循后端权限与隐私约束。 */
.pl__nick {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pl__meta {
  font-size: var(--fs-xs);
  line-height: var(--lh-card);
  color: var(--ink-muted);
}

/* 压在首屏深色图上 */
.pl--dark {
  color: var(--on-dark);
}

.pl--dark .pl__face {
  border: 1px solid var(--glass-line);
}

.pl--dark .pl__meta {
  color: var(--on-dark-2);
}

.pl--dark.pl--link:hover .pl__name {
  color: var(--on-dark);
  text-decoration: underline;
  text-underline-offset: 3px;
}
</style>
