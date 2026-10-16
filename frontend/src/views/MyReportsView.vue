<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import BlurStage from '../components/BlurStage.vue'
import CPill from '../components/CPill.vue'
import LoadState from '../components/LoadState.vue'
import PagerBar from '../components/PagerBar.vue'
import PageHead from '../components/PageHead.vue'
import { fetchReports, VISIBILITY_OPTIONS, type ReportListItem } from '../api/reports'
import { errorText } from '../lib/api-error'
import { formatDate } from '../lib/datetime'
import { ruleArtFile } from '../lib/rule-art'
import { useAuthStore } from '../stores/auth'
import { useHomeStore } from '../stores/home'

const auth = useAuthStore()
const home = useHomeStore()
const { authenticated, user } = storeToRefs(auth)

const items = ref<ReportListItem[]>([])
const count = ref(0)
const page = ref(1)
const hasNext = ref(false)
const loading = ref(true)
const error = ref('')

async function load(): Promise<void> {
  if (!user.value) return
  loading.value = true
  error.value = ''
  try {
    const data = await fetchReports({ author: user.value.id, page: page.value })
    items.value = data.results
    count.value = data.count
    hasNext.value = Boolean(data.next)
  } catch (e) {
    error.value = errorText(e, '战报暂时无法读取，请刷新后重试。')
    items.value = []
    count.value = 0
    hasNext.value = false
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await auth.refresh()
  void home.load(authenticated.value === true)
  await load()
})

watch(page, load)

const featuredCount = computed(() => items.value.filter((r) => r.is_featured).length)

function visibilityLabel(item: ReportListItem): string {
  return VISIBILITY_OPTIONS.find((o) => o.value === item.visibility)?.label ?? item.visibility
}

/** 缩略图 = 该团规则的美术（与战报列表、首页同一套取图顺序）。 */
function artFile(ruleSystem: string): string {
  const preset = home.presetByName(ruleSystem)
  return preset?.image.card || preset?.image.thumb || preset?.image.full || ruleArtFile(ruleSystem)
}
</script>

<template>
  <div class="mine u-rise">
    <RouterLink class="c-back" to="/me">
      <AppIcon name="back" :size="16" />
      我的
    </RouterLink>

    <PageHead
      eyebrow="My records · 我的战报"
      title="我的战报"
      lead="每个人在每个团中可以写一份战报，写完后可以随时修改。撰写战报需要从对应的团页面进入：团结束后，在团页面的「战报」标签中撰写。"
    >
      <template #aside>
        <RouterLink class="c-textlink" to="/reports">看全站战报 →</RouterLink>
      </template>
    </PageHead>

    <div class="bar">
      <span class="u-small">
        共 {{ count }} 篇<template v-if="featuredCount">，本页 {{ featuredCount }} 篇被站主精选</template>
      </span>
    </div>

    <LoadState
      :loading="loading"
      :error="error"
      :empty="!items.length"
      empty-title="你暂时没有写过战报"
      empty-text="团结束后，你可以在该团页面的「战报」标签中撰写战报。每个人在每个团中可以写一份，写完后仍可修改。"
    >
      <template #empty-actions>
        <RouterLink class="c-textlink" to="/me/games">看我参加过的团 →</RouterLink>
      </template>

      <div class="rows">
        <div v-for="item in items" :key="item.id" class="row">
          <BlurStage
            class="row__art"
            :file="artFile(item.game.rule_system)"
            :rule="item.game.rule_system"
            size="thumb"
            tone="dark"
            :inset="6"
            alt=""
          />

          <div class="row__main">
            <h2 class="row__title u-h-card">
              <RouterLink :to="'/reports/' + item.id">{{ item.title }}</RouterLink>
              <CPill v-if="item.is_featured" tone="ok">站主精选</CPill>
              <CPill :tone="item.visibility === 'same_game' ? 'wait' : 'off'">
                {{ visibilityLabel(item) }}
              </CPill>
            </h2>
            <p class="row__meta">
              <span v-if="item.game.rule_system">{{ item.game.rule_system }}</span>
              <span>团：{{ item.game.title }}</span>
              <span>{{ formatDate(item.created_at) }}</span>
              <span v-if="item.attachment_count">附件 {{ item.attachment_count }}</span>
            </p>
          </div>

          <div class="row__act">
            <RouterLink
              class="c-btn c-btn--ghost"
              :to="'/games/' + item.game.id + '/reports/edit'"
            >
              改稿
            </RouterLink>
            <RouterLink class="c-textlink" :to="'/reports/' + item.id">查看</RouterLink>
          </div>
        </div>
      </div>

      <PagerBar :page="page" :count="count" :has-next="hasNext" @go="page = $event" />
    </LoadState>
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2) var(--sp-4);
  margin-top: var(--sp-5);
  padding: var(--sp-3) var(--sp-4);
  background: var(--bg-2);
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}

/* ==========================================================================
   记录组行式条目（v2 me.html `.rows` / `.row`）
   ========================================================================== */

.rows {
  margin-top: var(--sp-5);
  border-top: 1px solid var(--line);
}

.row {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: var(--sp-2) var(--sp-5);
  align-items: start;
  padding: var(--sp-4) 0;
  border-bottom: 1px solid var(--line);
}

.row__art {
  width: 72px;
  height: 54px;
  border-radius: var(--radius);
}

.row__main {
  min-width: 0;
}

.row__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  font-size: var(--fs-lg);
  line-height: var(--lh-card);
  letter-spacing: -0.01em;
}

/** 业务界面遵循后端权限与隐私约束。 */
.row__title a {
  display: inline-block;
  min-height: 40px;
  padding: var(--sp-2) 0;
  line-height: 24px;
  text-decoration: none;
}

.row__title a:hover {
  text-decoration: underline;
  text-underline-offset: 4px;
}

.row__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px var(--sp-4);
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-muted);
}

.row__act {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3);
}

.row__act .c-btn {
  min-height: 44px;
  padding: 0 var(--sp-4);
  font-size: var(--fs-xs);
}

@media (min-width: 768px) {
  .row {
    grid-template-columns: 88px minmax(0, 1fr) auto;
    column-gap: var(--sp-6);
    align-items: center;
  }

  .row__art {
    width: 88px;
    height: 64px;
  }

  .row__act {
    grid-column: auto;
    justify-content: flex-end;
  }
}
</style>
