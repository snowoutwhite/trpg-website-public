<script setup lang="ts">
/**
 * 「战报」标签（v2 `game.html` 的 `#reports` 面板 `.report-item` 卡）。
 * 原 `/games/:id/reports` 整页并进这里。
 *
 * 可见性由后端过滤（游客只看得到精选且公开的，同团才看得到「仅同团可见」的那些），
 * **前端不再自己猜**；看不见的一律不在列表里。
 *
 * 「写我的战报」的资格 = 本团 GM 或到场成员（后端 `apps/reports/services.attended_game`，
 * 判据是 `accepted + attended`，退团 / 被移出的不算）。每人每团一份，可以反复改。
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import BlurStage from '../BlurStage.vue'
import CButton from '../CButton.vue'
import LoadState from '../LoadState.vue'
import PersonLine from './PersonLine.vue'
import { fetchReports, type ReportListItem } from '../../api/reports'
import type { GameDetail } from '../../api/games'
import type { RuleSystemPreset } from '../../api/home'
import type { CurrentUser } from '../../api/site'
import { errorText } from '../../lib/api-error'
import { formatDate } from '../../lib/datetime'

const props = defineProps<{
  game: GameDetail
  user: CurrentUser | null
  isGm: boolean
  preset?: RuleSystemPreset | null
}>()

const emit = defineEmits<{ count: [n: number] }>()

const items = ref<ReportListItem[]>([])
const loading = ref(true)
const error = ref('')
const page = ref(1)
const hasNext = ref(false)

/** 自己在本团的那一份（有就是「改」，没有就是「写」）。 */
const mine = computed(() =>
  props.user ? items.value.find((item) => item.author.id === props.user?.id) : undefined,
)
/** 后端口径：本团 GM 或 `accepted + attended` 的成员。 */
const canWrite = computed(
  () => props.game.status === 'finished' && (props.isGm || props.game.my_signup?.attended === true),
)

async function load(append = false): Promise<void> {
  loading.value = !append
  error.value = ''
  try {
    const data = await fetchReports({ game: props.game.id, page: page.value })
    items.value = append ? [...items.value, ...data.results] : data.results
    hasNext.value = Boolean(data.next)
    emit('count', data.count)
  } catch (e) {
    error.value = errorText(e, '战报暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())

function loadMore(): void {
  page.value += 1
  void load(true)
}
</script>

<template>
  <div class="gt">
    <h2 class="u-h-section gt__h">战报</h2>
    <p class="gt__sub">
      这里是本团到场成员撰写的跑团记录。每位成员在每个团只能写一篇战报，发布后可以随时修改；是否撰写、写多长都由成员自己决定。设为公开的战报无需登录即可阅读。
    </p>

    <div v-if="canWrite" class="gt__cta">
      <RouterLink class="c-btn" :to="'/games/' + game.id + '/reports/edit'">
        {{ mine ? '修改我的战报' : '撰写我的战报' }}
      </RouterLink>
      <span class="gt__small">
        你在本团的到场名单中，因此可以为本团撰写战报。每人每团只能写一篇，发布后仍可以回来修改。
      </span>
    </div>
    <p v-else-if="game.status === 'finished'" class="gt__small">
      只有被 GM 标记为到场的成员才能为本团撰写战报。设为公开的战报所有人都可以阅读。
    </p>
    <p v-else class="gt__small">
      本团还没有结团（当前状态：{{ game.status_display }}）。结团后，被标记为到场的成员才能撰写战报。
    </p>

    <LoadState
      :loading="loading"
      :error="error"
      :empty="!items.length"
      empty-title="本团暂时没有你可以阅读的战报"
      empty-text="设为「仅同团可见」的战报，只有本团的到场成员和 GM 可以阅读。"
    >
      <ul class="gt__list">
        <li v-for="item in items" :key="item.id">
          <RouterLink class="gt__card" :to="'/reports/' + item.id">
            <BlurStage
              class="gt__stage"
              :image="preset?.image ?? null"
              :rule="game.rule_system"
              :inset="10"
              alt=""
            />
            <span class="gt__body">
              <span class="u-h-card gt__title">{{ item.title }}</span>
              <span class="gt__excerpt">{{ item.excerpt }}</span>
              <span class="gt__who">
                <PersonLine :user="item.author" :size="22" :link="false" />
                <span class="gt__date">{{ formatDate(item.created_at) }}</span>
                <span v-if="item.visibility === 'same_game'" class="c-tag">仅同团可见</span>
                <span v-if="item.is_featured" class="c-tag c-tag--seal">精选</span>
              </span>
            </span>
          </RouterLink>
        </li>
      </ul>

      <div v-if="hasNext" class="c-actions">
        <CButton variant="ghost" @click="loadMore">加载更多战报</CButton>
      </div>
    </LoadState>
  </div>
</template>

<style scoped>
.gt__h {
  margin: 0 0 var(--sp-2);
}

.gt__sub {
  max-width: 62ch;
  margin: 0 0 var(--sp-4);
  font-size: var(--fs-sm);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.gt__cta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3) var(--sp-4);
  margin-bottom: var(--sp-4);
}

.gt__small {
  display: block;
  max-width: 52ch;
  margin: 0 0 var(--sp-4);
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.gt__list {
  display: grid;
  gap: var(--sp-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

/** `auto-fill + minmax(330px)` 自己会在放不下两列时退回单列，所以提前到 768 不会挤。 */
@media (min-width: 768px) {
  .gt__list {
    grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  }
}

.gt__card {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr);
  gap: var(--sp-3);
  overflow: hidden;
  color: inherit;
  text-decoration: none;
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  transition: box-shadow var(--dur) var(--ease);
}

.gt__card:hover {
  box-shadow: var(--shadow-1);
}

.gt__stage {
  min-height: 118px;
}

.gt__body {
  display: flex;
  flex-direction: column;
  padding: var(--sp-3) var(--sp-3) var(--sp-3) 0;
  min-width: 0;
}

.gt__title {
  display: block;
  margin-bottom: var(--sp-2);
  overflow-wrap: anywhere;
}

.gt__excerpt {
  display: block;
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  color: var(--ink-muted);
  overflow-wrap: anywhere;
}

.gt__who {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin-top: auto;
  padding-top: var(--sp-3);
  font-size: var(--fs-xs);
  color: var(--ink-muted);
}

.gt__date {
  color: var(--ink-muted);
}

/* 同上：原来是约定外的 560 */
@media (min-width: 768px) {
  .gt__card {
    grid-template-columns: 118px minmax(0, 1fr);
    gap: var(--sp-4);
  }

  .gt__stage {
    min-height: 132px;
  }

  .gt__body {
    padding: var(--sp-4) var(--sp-4) var(--sp-4) 0;
  }
}

@media (min-width: 1200px) {
  /* 宽屏上说明文字放宽到 72ch（62ch 在 1440 以上显得过窄） */
  .gt__sub {
    max-width: 72ch;
  }
}
</style>
