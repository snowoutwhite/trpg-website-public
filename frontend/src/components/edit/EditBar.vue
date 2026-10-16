<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import CButton from '../CButton.vue'
import { useEditStore } from '../../stores/edit'

const edit = useEditStore()
const router = useRouter()

const root = ref<HTMLElement | null>(null)
let observer: ResizeObserver | null = null

function publishHeight(): void {
  const height = root.value?.getBoundingClientRect().height
  if (height) document.documentElement.style.setProperty('--edit-bar-h', Math.ceil(height) + 'px')
}

onMounted(() => {
  publishHeight()
  if ('ResizeObserver' in window && root.value) {
    observer = new ResizeObserver(publishHeight)
    observer.observe(root.value)
  }
  window.addEventListener('resize', publishHeight, { passive: true })
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  window.removeEventListener('resize', publishHeight)
  document.documentElement.style.removeProperty('--edit-bar-h')
})

/** 非字段级的失败原因（键以 `__form__` 结尾），去重后摆到保存条上。 */
const formErrors = computed(() => {
  const out: string[] = []
  for (const [key, msg] of Object.entries(edit.fieldErrors)) {
    if (key.endsWith('__form__') && msg && !out.includes(msg)) out.push(msg)
  }
  return out
})

const countText = computed(() =>
  edit.dirtyCount > 0 ? '有 ' + edit.dirtyCount + ' 处改动' : '还没有改动',
)

function onSave(): void {
  void edit.save()
}

/** 「确认离开」：丢掉草稿并放行那次被拦下的跳转。 */
function leaveTo(): void {
  const target = edit.pendingLeave
  edit.leave()
  if (target) void router.push(target)
}
</script>

<template>
  <div ref="root" class="eb" role="region" aria-label="编辑操作">
    <div class="eb__inner">
      <p class="eb__state">
        <strong class="eb__count">{{ countText }}</strong>
        <!-- 正在改的那一格：名字 + 字数（原地编辑不在字旁边浮角标，放这里不压任何内容） -->
        <span v-if="edit.focusField" class="eb__focus" aria-live="polite">
          正在改：{{ edit.focusField.label }}
          <span class="eb__len" :class="{ 'is-over': edit.focusField.length > edit.focusField.max }">
            {{ edit.focusField.length }} / {{ edit.focusField.max }} 字
          </span>
        </span>
        <span v-else class="eb__note">文字改动要点「保存」才生效；换图与公告是立刻生效的。</span>
      </p>

      <p v-if="edit.loadError" class="eb__err">{{ edit.loadError }}</p>
      <p v-else-if="edit.error" class="eb__err">
        {{ edit.error }}
        <!-- 业务信息 -->
        <a v-if="edit.authLost" class="eb__login" href="/auth/login?next=%2F" target="_blank" rel="noopener noreferrer">在新标签页登录 ↗</a>
      </p>
      <p v-else-if="edit.saved" class="eb__ok">{{ edit.saved }}</p>
      <!-- 业务信息 -->
      <ul v-if="formErrors.length" class="eb__forms">
        <li v-for="msg in formErrors" :key="msg">{{ msg }}</li>
      </ul>

      <!-- 被路由守卫拦下：先问一次 -->
      <div v-if="edit.pendingLeave" class="eb__ask">
        <span>有 {{ edit.dirtyCount }} 处改动还没保存。离开这一页会丢掉它们。</span>
        <CButton class="eb__btn" variant="danger" @click="leaveTo">放弃改动并离开</CButton>
        <CButton class="eb__btn" variant="ghost" @click="edit.pendingLeave = ''">留在本页</CButton>
      </div>

      <!-- 退出编辑态（有改动） -->
      <div v-else-if="edit.exitAsk" class="eb__ask">
        <span>有 {{ edit.dirtyCount }} 处改动还没保存。退出编辑会丢掉它们。</span>
        <CButton class="eb__btn" variant="danger" @click="edit.leave()">放弃改动并退出</CButton>
        <CButton class="eb__btn" variant="ghost" @click="edit.exitAsk = false">继续编辑</CButton>
      </div>

      <!-- 放弃（二次确认） -->
      <div v-else-if="edit.discardAsk" class="eb__ask">
        <span>把这 {{ edit.dirtyCount }} 处改动全部还原成保存前的样子？</span>
        <CButton class="eb__btn" variant="danger" @click="edit.discard()">确认放弃</CButton>
        <CButton class="eb__btn" variant="ghost" @click="edit.discardAsk = false">再想想</CButton>
      </div>

      <div v-else class="eb__acts">
        <CButton
          class="eb__btn"
          variant="ghost"
          :disabled="edit.saving || !edit.dirty"
          @click="edit.discardAsk = true"
        >
          放弃
        </CButton>
        <CButton class="eb__btn" :disabled="edit.saving || !edit.dirty" @click="onSave">
          {{ edit.saving ? '正在保存…' : '保存' }}
        </CButton>
        <CButton class="eb__btn" variant="ghost" :disabled="edit.saving" @click="edit.exit()">
          退出编辑
        </CButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.eb__focus {
  color: var(--ink-soft);
}

.eb__len {
  margin-left: var(--sp-2);
  font-variant-numeric: tabular-nums;
  color: var(--ink-muted);
}

.eb__len.is-over {
  color: var(--danger);
}

/* 会话过期时的「去登录」出口：与错误文字同行，触控目标靠行高撑到 ≥44px */
.eb__login {
  display: inline-block;
  margin-left: var(--sp-2);
  padding: var(--sp-2) 0;
  font-weight: 600;
  color: var(--brand-ink);
  text-underline-offset: 3px;
}

/* 非字段级失败原因列表（401 / 500 / 断网） */
.eb__forms {
  margin: 0;
  padding-left: 1.2em;
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--danger);
}

.eb {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  /* 压过 .rulepage / .lightbox（两者都是 50）：规则介绍那三格就在覆盖层里改 */
  z-index: 60;
  color: var(--ink);
  background: var(--white);
  border-top: 1px solid var(--line-2);
  box-shadow: var(--shadow-1);
}

.eb__inner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2) var(--sp-4);
  max-width: var(--max);
  margin: 0 auto;
  padding: var(--sp-2) var(--pad) calc(var(--sp-2) + var(--safe-bottom));
}

.eb__state {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--sp-1) var(--sp-3);
  margin: 0;
  min-width: 0;
}

.eb__count {
  font-size: var(--fs-sm);
  letter-spacing: var(--ls-caps-sm);
  color: var(--brand-ink);
}

.eb__note {
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-muted);
}

.eb__err,
.eb__ok {
  flex: 1 1 100%;
  order: 3;
  margin: 0;
  font-size: var(--fs-xs);
  line-height: 1.5;
}

.eb__err {
  color: var(--danger);
}

.eb__ok {
  color: var(--ok);
}

.eb__acts,
.eb__ask {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--ink-soft);
}

/* 触控目标 ≥44px（全局 .c-btn 只保证 40） */
.eb__btn {
  min-height: 44px;
}

@media (min-width: 768px) {
  .eb__inner {
    padding-left: var(--sp-5);
    padding-right: var(--sp-5);
  }
}
</style>
