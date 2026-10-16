<script setup lang="ts">
/**
 * 「评价」标签 —— **v2 全站没画这一页**，按实施方案「不砍功能」补的（写评价表单原在 `/me/reviews`）。
 *
 * 谁看得到这个标签（由 `GameDetailView` 判定，这里只负责内容）：
 *   赞功能开着 + 团已结团 + 还在评价窗口内 + 本人是到场成员（GM 永远算到场）。
 *   窗口一关标签就消失，和后端 `in_review_window` 同口径。
 *
 * 行从哪来：
 * - `GET /reviews/pending/` 里属于本团的那一组 = 还没评的人（后端已经按
 *   `reviewable_targets` 算好：PL 评 GM 与其他到场 PL，GM 评所有到场 PL，谁都不能评自己）；
 * - `GET /reviews/mine/given/` 里属于本团的 = 已评的人（带 reviewee，本人当然知道自己评了谁）。
 *   两者并起来就是「同团其他到场者」的完整名单，不用另外去读名单接口。
 *
 * 三档与「无评价」的口径见 `ReviewForm.vue`。
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import CNotice from '../CNotice.vue'
import CEmpty from '../CEmpty.vue'
import LoadState from '../LoadState.vue'
import ReviewForm from './ReviewForm.vue'
import {
  fetchGivenReviews,
  fetchPendingReviews,
  fetchReviewQuota,
  submitReview,
  type GivenReview,
  type PendingTarget,
  type ReviewQuota,
  type Verdict,
} from '../../api/reviews'
import type { GameDetail } from '../../api/games'
import type { PublicUser } from '../../api/site'
import { errorText } from '../../lib/api-error'
import { formatDateTime, timeLeft } from '../../lib/datetime'

const props = defineProps<{ game: GameDetail }>()

interface Row {
  user: PublicUser
  roleDisplay: string
  existing: GivenReview | null
}

const targets = ref<PendingTarget[]>([])
const given = ref<GivenReview[]>([])
const quota = ref<ReviewQuota | null>(null)
const windowEndsAt = ref<string | null>(null)
const loading = ref(true)
const error = ref('')

const busyFor = ref(0)
const actionError = ref('')
const actionOk = ref('')

async function load(): Promise<void> {
  error.value = ''
  try {
    const [pending, mine, q] = await Promise.all([
      fetchPendingReviews(),
      fetchGivenReviews(),
      fetchReviewQuota(),
    ])
    const group = pending.results.find((g) => g.game.id === props.game.id)
    targets.value = group?.targets ?? []
    windowEndsAt.value = group?.window_ends_at ?? props.game.review_window_ends_at
    given.value = mine.results.filter((r) => r.game.id === props.game.id)
    quota.value = q
  } catch (e) {
    error.value = errorText(e, '评价数据暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
}

onMounted(load)

/**
 * 待评 + 已评 = 同团其他到场者。
 * `role_display` 优先用 pending 下发的那一份；已评的行 pending 里没有，就按被评者身份取
 * 同样的两个值（后端 `ROLE_CHOICES` 的 label 就是 "GM" / "PL"，不是需要翻译的中文枚举）。
 */
const rows = computed<Row[]>(() => {
  const list: Row[] = targets.value.map((t) => ({
    user: t.user,
    roleDisplay: t.role_display,
    existing: null,
  }))
  for (const review of given.value) {
    list.push({
      user: review.reviewee,
      roleDisplay: review.reviewee_role === 'gm' ? 'GM' : 'PL',
      existing: review,
    })
  }
  return list
})

async function onSubmit(row: Row, payload: { verdict: Verdict; text: string }): Promise<void> {
  if (busyFor.value) return
  busyFor.value = row.user.id
  actionError.value = ''
  actionOk.value = ''
  try {
    await submitReview({
      game: props.game.id,
      reviewee: row.user.id,
      verdict: payload.verdict,
      text: payload.text,
    })
    actionOk.value = '评价已提交。窗口关闭前还能改，但不能撤回。'
    await load()
  } catch (e) {
    actionError.value = errorText(e, '提交失败，请稍后再试。')
  } finally {
    busyFor.value = 0
  }
}
</script>

<template>
  <div class="gv">
    <h2 class="u-h-section gv__h">团后评价</h2>
    <p class="gv__sub">
      只有被标记为到场的成员可以评价他人，也只有他们会被评价；你可以对同团的每一位其他成员各评价一次。评价是匿名的：被评价的人能看到评价内容，但看不到是谁写的。
      <template v-if="windowEndsAt">
        本团的评价开放到 {{ formatDateTime(windowEndsAt) }}（{{ timeLeft(windowEndsAt) }}）。截止后将无法再提交或修改评价，本页的「团后评价」标签也会随之隐藏。
      </template>
    </p>

    <CNotice title="评价分为三种：赞、无评价、倒赞">
      「赞」和「倒赞」会分别计入对方的赞数和倒赞数。对方在本团担任 GM 时，评价计入其 GM 侧赞级别；以玩家身份参加时，计入其玩家侧赞级别，两侧分开统计。
      <strong class="gv__strong">如果你在评价截止前没有提交评价，就记为「无评价」。</strong>「无评价」既不算赞，也不算倒赞，但会计入对方的被评价次数。赞级别按赞和倒赞各自占被评价次数的比例算出，因此「无评价」会同时拉低赞所占的比例和倒赞所占的比例，使对方的赞级别更接近中间的「中性」。
      赞级别会显示在每个人的个人空间，部分 GM 放团时还会把它设为报名条件，因此请认真对待每一次评价。选择赞或倒赞时都必须填写评价内容；提交后在评价截止前可以修改，但不能撤回。
    </CNotice>

    <CNotice v-if="actionError" tone="danger">{{ actionError }}</CNotice>
    <CNotice v-else-if="actionOk" tone="ok">{{ actionOk }}</CNotice>

    <LoadState :loading="loading" :error="error">
      <p v-if="quota" class="gv__quota">
        你在全站可写的评价共 {{ quota.quota }} 条（按你参加的每个团中其他成员的人数累计），已写 {{ quota.used }} 条，还可以写 {{ quota.remaining }} 条。
        <RouterLink class="u-tap" to="/me/reviews">前往「我的 · 团后评价」查看全部 →</RouterLink>
      </p>

      <CEmpty
        v-if="!rows.length"
        title="本团没有你可以评价的成员"
        text="可能是本团到场名单中除你之外没有其他成员，或者你不在本团的到场名单中。"
      />

      <ReviewForm
        v-for="row in rows"
        :key="row.user.id"
        :user="row.user"
        :role-display="row.roleDisplay"
        :existing="row.existing"
        :busy="busyFor === row.user.id"
        @submit="onSubmit(row, $event)"
      />
    </LoadState>
  </div>
</template>

<style scoped>
.gv {
  max-width: 920px;
}

.gv__h {
  margin: 0 0 var(--sp-2);
}

.gv__sub {
  max-width: 62ch;
  margin: 0 0 var(--sp-4);
  font-size: var(--fs-sm);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.gv__strong {
  font-weight: 400;
  color: var(--ink);
}

.gv__quota {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-4);
  margin: var(--sp-4) 0;
  font-size: var(--fs-xs);
  color: var(--ink-muted);
}

.gv :deep(.c-note) {
  margin-bottom: var(--sp-3);
}

@media (min-width: 1200px) {
  /* 宽屏上说明文字放宽到 72ch（62ch 在 1440 以上显得过窄） */
  .gv__sub {
    max-width: 72ch;
  }
}
</style>
