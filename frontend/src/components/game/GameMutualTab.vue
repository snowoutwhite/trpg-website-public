<script setup lang="ts">
/** 「互见」标签（v2 `game.html` 的 `#reviews` 面板）。原 `/games/:id/mutual` 整页并进这里。 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import CNotice from '../CNotice.vue'
import CPill from '../CPill.vue'
import LoadState from '../LoadState.vue'
import PersonLine from './PersonLine.vue'
import { fetchMutualPanel, type MutualPanel } from '../../api/reviews'
import type { GameDetail } from '../../api/games'
import { errorCode, errorText } from '../../lib/api-error'

const props = defineProps<{
  game: GameDetail
  authenticated: boolean | null
  loginTo: string
}>()

const panel = ref<MutualPanel | null>(null)
const loading = ref(true)
const error = ref('')
/** 后端错误码，用来分辨「为什么看不了」。 */
const code = ref('')

onMounted(async () => {
  if (props.authenticated !== true) {
    loading.value = false
    return
  }
  try {
    panel.value = await fetchMutualPanel(props.game.id)
  } catch (e) {
    code.value = errorCode(e)
    error.value = errorText(e, '互见面板暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
})

/** 三种「看不了」按码分流；其余（网络、500）才当成真错误显示。 */
const blocked = computed(() =>
  ['review_not_open', 'mutual_review_disabled', 'not_attendee', 'like_feature_disabled'].includes(
    code.value,
  ),
)

function countOf(reviews: { verdict: string }[], verdict: string): number {
  return reviews.filter((r) => r.verdict === verdict).length
}
</script>

<template>
  <div class="gm">
    <h2 class="u-h-section gm__h">评价互见</h2>
    <p class="gm__sub">
      下面按被评价的成员分组，列出每位成员在本团<strong class="gm__strong">收到</strong>的匿名评价，不会显示评价是谁写的。
      评价互见设置在本团收到第一条报名后就不能再修改，GM 也无法更改，因为每位成员在报名时已经按当时的设置表示同意。
    </p>

    <CNotice v-if="authenticated !== true" title="评价互见内容只对本团成员开放">
      请登录后查看。所有评价都是匿名的，站内任何位置都不会显示评价是谁写的。
      <template #actions>
        <RouterLink class="c-btn c-btn--ghost" :to="loginTo">登录</RouterLink>
      </template>
    </CNotice>

    <template v-else>
      <CNotice v-if="blocked" title="你暂时无法查看本团的评价互见">{{ error }}</CNotice>

      <LoadState v-else :loading="loading" :error="error">
        <template v-if="panel">
          <CNotice v-if="!panel.available" title="评价互见暂未对你开放">
            在本团之后，你还需要再完成 {{ panel.visible_after_games }} 个团，本团的评价互见内容才会对你开放。
            这项等待条件按每位查看者分别计算，目的是防止有人借助互见内容，提前看到自己收到的评价并推测出评价人。
          </CNotice>

          <template v-else>
            <section v-for="group in panel.groups" :key="group.user.id" class="gm__group">
              <div class="gm__head">
                <span class="gm__to">对</span>
                <PersonLine :user="group.user" :size="28" />
                <span class="gm__to">的评价</span>
                <CPill tone="off">{{ group.role === 'gm' ? '本团 GM' : 'PL' }}</CPill>
                <span class="gm__grow" />
                <span class="gm__nums">
                  收到 赞 {{ countOf(group.reviews, 'like') }} · 倒赞
                  {{ countOf(group.reviews, 'dislike') }}
                </span>
              </div>
              <p v-if="!group.reviews.length" class="gm__small">这位成员暂时没有可以显示的评价。</p>
              <p
                v-for="(item, i) in group.reviews"
                :key="'m' + i"
                class="gm__quote"
                :class="item.verdict === 'dislike' ? 'gm__quote--down' : null"
              >
                <span class="gm__verdict">{{ item.verdict_display }}</span>
                {{ item.text }}
              </p>
            </section>

            <p class="gm__foot">
              评价的显示顺序已被随机打乱，与提交的先后无关。但在人数较少的团里，其他成员仍有可能通过排除法推测出评价人，
              这是评价互见功能无法完全避免的情况。GM 开团时开启这项设置、成员报名参加，即表示大家接受这一点。
            </p>
          </template>
        </template>
      </LoadState>
    </template>
  </div>
</template>

<style scoped>
.gm {
  max-width: 920px;
}

.gm__h {
  margin: 0 0 var(--sp-2);
}

.gm__sub {
  max-width: 62ch;
  margin: 0 0 var(--sp-5);
  font-size: var(--fs-sm);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.gm__strong {
  font-weight: 400;
  color: var(--ink);
}

.gm__group {
  padding: var(--sp-4) 0;
  border-bottom: 1px solid var(--line);
}

.gm__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
}

.gm__to {
  font-size: var(--fs-md);
  color: var(--ink-muted);
}

.gm__grow {
  flex: 1 1 auto;
}

.gm__nums {
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-muted);
  white-space: nowrap;
}

.gm__quote {
  margin: var(--sp-2) 0 0;
  padding-left: var(--sp-4);
  border-left: 2px solid var(--ok-line);
  font-size: var(--fs-sm);
  line-height: 2;
  color: var(--ink-soft);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.gm__quote--down {
  border-left-color: var(--danger-line);
}

.gm__verdict {
  margin-right: var(--sp-2);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps);
  color: var(--ink-muted);
}

.gm__small {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-xs);
  color: var(--ink-muted);
}

.gm__foot {
  max-width: 62ch;
  margin: var(--sp-5) 0 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

@media (min-width: 1200px) {
  /* 宽屏上说明文字放宽到 72ch（62ch 在 1440 以上显得过窄） */
  .gm__sub,
  .gm__foot {
    max-width: 72ch;
  }
}
</style>
