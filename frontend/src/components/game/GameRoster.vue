<script setup lang="ts">
/** 「名单」标签（v2 `game.html` 的 `#roster` 面板）。 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import CNotice from '../CNotice.vue'
import CPill from '../CPill.vue'
import CEmpty from '../CEmpty.vue'
import PersonLine from './PersonLine.vue'
import type { GameDetail, RecruitingSignup, RosterSignup } from '../../api/games'
import { formatDateTime } from '../../lib/datetime'

const props = defineProps<{
  game: GameDetail
  authenticated: boolean | null
  /** 招募中名单（登录可见）；`recruitingOk` 为假说明这一层没权限。 */
  recruiting: RecruitingSignup[]
  recruitingOk: boolean
  /**
   * 正式名单（同团可见）。
   * **只能是 `status === 'accepted'` 的那一档**：本团 GM 拉到的 `roster/` 是全量报名
   * （含已退出 / 被拒 / 被移除），调用方必须先过滤再传进来（`GameDetailView.loadRosters`）。
   */
  roster: RosterSignup[]
  rosterOk: boolean
  loginTo: string
}>()

const isFinished = computed(() => props.game.status === 'finished')

/** 状态 → CPill 的 tone（tone 与类名是错位的，见 CPill 头部对照表）。 */
function toneOf(status: string): 'ok' | 'wait' | 'off' {
  if (status === 'accepted') return 'ok'
  if (status === 'pending' || status === 'submitted') return 'wait'
  return 'off'
}
</script>

<template>
  <div class="gr">
    <h2 class="u-h-section gr__h">名单</h2>
    <p class="gr__sub">
      名单按查看者分为三种范围：所有访客都能看到报名人数；登录后可以看到尚未确定的报名；正式名单只有本团成员能看到。
    </p>

    <!-- 游客 -->
    <CNotice v-if="authenticated !== true" title="登录后可以查看报名者">
      <p class="gr__count">{{ game.occupied_seats }}</p>
      <p class="gr__ctext">
        人已占位（上限 {{ game.max_players }} 人）。正式名单只对本团成员开放，这是本站的统一规定，GM 也无法修改。
      </p>
      <template #actions>
        <RouterLink class="c-btn c-btn--ghost" :to="loginTo">登录查看</RouterLink>
      </template>
    </CNotice>

    <template v-else>
      <!-- 登录成员：招募中名单 -->
      <section v-if="recruitingOk" class="gr__block">
        <h3 class="u-h-card gr__h3">尚未确定的报名</h3>
        <p class="gr__small">这里列出状态为「待交卡」或「已交卡待审」的报名者，所有登录用户都能看到这部分内容。</p>
        <ul v-if="recruiting.length" class="gr__people">
          <li v-for="item in recruiting" :key="item.id">
            <PersonLine
              :user="item.player"
              :meta="'第 ' + item.order + ' 位报名 · ' + formatDateTime(item.created_at)"
            />
            <span class="gr__grow" />
            <CPill :tone="toneOf(item.status)">{{ item.status_display }}</CPill>
          </li>
        </ul>
        <CEmpty v-else compact title="暂时没有尚未确定的报名" text="有玩家报名后，报名信息会显示在此处。" />
      </section>

      <!-- 同团成员：正式名单 -->
      <section v-if="rosterOk" class="gr__block">
        <CNotice tone="ok" title="你是本团成员">
          因为你在本团的正式名单中，所以可以查看下面的完整名单、团相册，以及结团后的评价互见内容。如果你退出本团或被移出名单，将无法再查看这三项内容。
        </CNotice>
        <h3 class="u-h-card gr__h3">{{ isFinished ? '到场名单' : '正式名单（成功报团）' }}</h3>
        <p class="gr__small">
          到场标记由 GM 在结团时勾选。被标记为到场的成员，团次数会增加一次，并且可以撰写战报、参与团后评价。
        </p>
        <ul v-if="roster.length" class="gr__people">
          <li v-for="item in roster" :key="item.id">
            <PersonLine :user="item.player" meta="报名已通过，是正式名单成员" />
            <span class="gr__grow" />
            <CPill v-if="isFinished" :tone="item.attended ? 'ok' : 'off'">
              {{ item.attended ? '到场' : '未到场' }}
            </CPill>
            <CPill v-else tone="off">到场待勾选</CPill>
          </li>
        </ul>
        <CEmpty v-else compact title="正式名单中暂时没有成员" text="报名通过的玩家会显示在此处。" />
      </section>

      <!-- 登录但不同团 -->
      <CNotice v-else class="gr__block" title="正式名单只对本团成员开放">
        你的报名通过后，此处会列出本团的全部成员，结团后还会显示每位成员是否到场。
      </CNotice>
    </template>
  </div>
</template>

<style scoped>
.gr {
  max-width: 920px;
}

.gr__h {
  margin: 0 0 var(--sp-2);
}

.gr__sub {
  max-width: 62ch;
  margin: 0 0 var(--sp-5);
  font-size: var(--fs-sm);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.gr__block {
  margin-top: var(--sp-6);
}

.gr__h3 {
  margin: var(--sp-4) 0 var(--sp-1);
}

.gr__small {
  margin: 0 0 var(--sp-2);
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.gr__count {
  margin: 0;
  font-size: var(--fs-h-section);
  letter-spacing: var(--ls-section);
  line-height: 1.2;
  color: var(--ink);
}

.gr__ctext {
  margin: var(--sp-1) 0 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
}

.gr__people {
  margin: var(--sp-2) 0 0;
  padding: 0;
  list-style: none;
}

.gr__people li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-3);
  min-height: 56px;
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--line);
}

.gr__grow {
  flex: 1 1 auto;
}

@media (min-width: 1200px) {
  /* 宽屏上说明文字放宽到 72ch（62ch 在 1440 以上显得过窄） */
  .gr__sub {
    max-width: 72ch;
  }
}
</style>
