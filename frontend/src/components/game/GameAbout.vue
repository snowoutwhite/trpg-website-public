<script setup lang="ts">
/** 「团介绍」标签（v2 `game.html` 的 `#announcement` 面板，两栏：左长文 + 右「报名要求」侧卡）。 */
import { computed } from 'vue'
import MarkdownView from '../MarkdownView.vue'
import CEmpty from '../CEmpty.vue'
import PersonLine from './PersonLine.vue'
import type { GameDetail } from '../../api/games'
import { formatDateTime } from '../../lib/datetime'

const props = defineProps<{ game: GameDetail; likeOn: boolean }>()

/** 改过的团才显示「最近改于」；差一分钟以内当没改过（保存时两个字段本来就差几毫秒）。 */
const edited = computed(() => {
  const g = props.game
  if (!g.updated_at || !g.created_at) return false
  return new Date(g.updated_at).getTime() - new Date(g.created_at).getTime() > 60_000
})

/**
 * GM 的赞级别文案。`reviews_received === null` = 后端没公布（被评次数不够，或站主关了赞功能），
 * 这时**只能**写「未公布」—— 不是「没有档位」，两者含义不同。
 */
const gmLevel = computed(() => {
  const card = props.game.gm_card
  if (!card) return ''
  if (card.reviews_received === null) return '未公布'
  return card.level_display || '未公布'
})

/** 右侧「报名要求」侧卡的行；只放硬条件，软描述留给正文。 */
const rows = computed(() => {
  const g = props.game
  const list: { k: string; v: string }[] = [
    { k: '人数范围', v: g.min_players + ' – ' + g.max_players + ' 人，不足下限不开团' },
    { k: '报名模式', v: g.signup_mode_display },
  ]
  const gates: string[] = []
  if (g.min_play_count !== null) gates.push('团次数 ≥ ' + g.min_play_count)
  if (g.min_level) gates.push('赞级别 ' + g.min_level_display + ' 及以上')
  list.push({ k: '门槛', v: gates.length ? gates.join(' · ') : '没有设门槛' })
  if (g.campaign_prev) {
    list.push({
      k: '战役限制',
      v: g.restrict_to_prev_members
        ? '只有「' + g.campaign_prev.title + '」的到场成员能报'
        : '接着「' + g.campaign_prev.title + '」往下跑，不限成员',
    })
  }
  list.push({
    k: '角色卡',
    v: g.requires_card ? '需交卡，截止 ' + formatDateTime(g.card_deadline) : '免交卡',
  })
  if (props.likeOn) {
    list.push({
      k: '评价互见',
      v: g.mutual_review
        ? '已开启 · 结团后同团成员能看到彼此收到的匿名评价；出现第一条报名后这个开关就冻结了'
        : '未开启 · 每个人只能延迟看到自己收到的评价',
    })
  }
  return list
})
</script>

<template>
  <div class="ga">
    <div class="ga__main">
      <h2 class="u-h-section ga__h">团介绍</h2>
      <p class="ga__byline">
        发布于 {{ formatDateTime(game.created_at) }}
        <template v-if="edited"> · 最近改于 {{ formatDateTime(game.updated_at) }}</template>
      </p>
      <p class="ga__sub">
        团介绍由本团 GM 撰写，GM 可以随时修改。开团时间、人数上限、报名门槛等报名条件修改后，招募列表中显示的信息会同步更新。
      </p>

      <MarkdownView v-if="game.announcement" class="ga__md" :source="game.announcement" />
      <CEmpty v-else compact title="本团 GM 暂时没有填写团介绍" text="开团时间、人数上限和报名门槛等条件，请查看本页的「报名要求」一栏。" />

      <section v-if="game.requirements" class="ga__block">
        <h3 class="u-h-card ga__h3">需求</h3>
        <p class="ga__plain">{{ game.requirements }}</p>
      </section>

      <section v-if="game.sessions.length" class="ga__block">
        <h3 class="u-h-card ga__h3">场次</h3>
        <p class="ga__small">
          需要多次聚会才能跑完的长团，会按回次登记每一场的时间。场次仅用于记录；无论实际跑了多少场，团次数和团后评价都只按整个团计算一次。
        </p>
        <ul class="ga__sessions">
          <li v-for="s in game.sessions" :key="s.id">
            <span class="ga__sno">{{ s.display_label }}</span>
            <span class="ga__stime">{{
              s.held_at ? formatDateTime(s.held_at) : '时间待定'
            }}</span>
          </li>
        </ul>
      </section>
    </div>

    <div class="ga__side">
      <aside class="ga__card" aria-label="报名要求">
        <h3 class="u-h-card ga__h3">报名要求</h3>
        <dl class="ga__dl">
          <div v-for="row in rows" :key="row.k">
            <dt class="u-kicker">{{ row.k }}</dt>
            <dd>{{ row.v }}</dd>
          </div>
        </dl>
      </aside>

      <!-- 业务信息 -->
      <aside class="ga__card" aria-label="本团的 GM">
        <h3 class="u-h-card ga__h3">本团的 GM</h3>
        <PersonLine class="ga__gm" :user="game.gm" :size="38" meta="点击可查看这位 GM 的 GM 卡与战报" />
        <dl v-if="game.gm_card" class="ga__dl">
          <div>
            <dt class="u-kicker">主持团数</dt>
            <dd>{{ game.gm_card.games_hosted }} 个团</dd>
          </div>
          <div v-if="likeOn">
            <dt class="u-kicker">赞级别</dt>
            <dd>{{ gmLevel }}</dd>
          </div>
          <div v-if="game.gm_card.style_text">
            <dt class="u-kicker">风格自述</dt>
            <dd class="ga__style">{{ game.gm_card.style_text }}</dd>
          </div>
        </dl>
        <p v-else class="ga__small ga__nocard">
          这位 GM 目前没有 GM 卡，因此无法显示其主持团数等统计信息。这不影响本团的报名和进行。
        </p>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.ga {
  display: grid;
  gap: var(--sp-6);
  align-items: start;
}

.ga__main {
  min-width: 0;
}

.ga__h {
  margin: 0 0 var(--sp-1);
}

/** 业务界面遵循后端权限与隐私约束。 */
.ga__byline {
  margin: 0 0 var(--sp-2);
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-wide);
  color: var(--ink-faint);
}

.ga__sub {
  max-width: 62ch;
  margin: 0 0 var(--sp-5);
  font-size: var(--fs-sm);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.ga__md {
  max-width: 72ch;
}

.ga__block {
  margin-top: var(--sp-6);
}

.ga__h3 {
  margin: 0 0 var(--sp-2);
}

.ga__small {
  margin: 0 0 var(--sp-2);
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
  color: var(--ink-muted);
}

.ga__plain {
  max-width: 72ch;
  margin: 0;
  font-size: var(--fs-base);
  line-height: var(--lh-body);
  color: var(--ink-soft);
  /* 需求是 GM 手写的多段文本，换行照原样留着 */
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.ga__sessions {
  margin: var(--sp-2) 0 0;
  padding: 0;
  list-style: none;
  max-width: 560px;
}

.ga__sessions li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-4);
  min-height: 44px;
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--line);
  font-size: var(--fs-md);
}

.ga__sno {
  color: var(--ink);
}

.ga__stime {
  color: var(--ink-muted);
}

/** 业务界面遵循后端权限与隐私约束。 */
.ga__side {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-4);
  align-content: start;
}

.ga__card {
  padding: var(--sp-5);
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.ga__gm {
  margin-top: var(--sp-3);
}

.ga__style {
  white-space: pre-wrap;
}

.ga__nocard {
  margin: var(--sp-3) 0 0;
}

.ga__dl {
  display: grid;
  gap: var(--sp-4);
  margin: var(--sp-4) 0 0;
}

.ga__dl dt {
  margin-bottom: var(--sp-1);
  color: var(--kicker);
}

.ga__dl dd {
  margin: 0;
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
  color: var(--ink-soft);
  overflow-wrap: anywhere;
}

@media (min-width: 1200px) {
  /** 这样「团介绍」侧卡的右边界与首屏行动卡落在同一条线上（版心右边界）。 */
  .ga {
    grid-template-columns: minmax(0, 1fr) 352px;
    gap: var(--sp-7);
  }

  /* 宽屏上说明文字放宽到 72ch（62ch 在 1440 以上显得过窄） */
  .ga__sub {
    max-width: 72ch;
  }
}
</style>
