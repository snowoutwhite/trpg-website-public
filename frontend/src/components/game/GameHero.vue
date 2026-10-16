<script setup lang="ts">
/** 团详情首屏（v2 `game.html` 的 `.detail-hero`）：规则美术同图虚化铺底 + */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import BlurStage from '../BlurStage.vue'
import PersonLine from './PersonLine.vue'
import type { GameDetail } from '../../api/games'
import type { RuleSystemPreset } from '../../api/home'
import { formatDateTime } from '../../lib/datetime'

const props = defineProps<{
  game: GameDetail
  /** 站长内容里的规则预设（有就用它自带的三档图，没有走本地兜底）。 */
  preset?: RuleSystemPreset | null
}>()

/** v2 的事实网格：线上团不出现「地点」那一格。 */
const facts = computed(() => {
  const g = props.game
  const rows: { k: string; v: string }[] = [
    { k: '开团时间', v: formatDateTime(g.start_at) },
    { k: '形式', v: g.mode_display },
  ]
  if (g.mode === 'offline' && g.location) rows.push({ k: '地点', v: g.location })
  rows.push({
    k: '占位',
    v: g.occupied_seats + ' / ' + g.max_players + ' 人 · 下限 ' + g.min_players + ' 人',
  })
  rows.push({ k: '报名模式', v: g.signup_mode_display })
  rows.push({
    k: '角色卡',
    v: g.requires_card ? '需交卡 · 截止 ' + formatDateTime(g.card_deadline) : '免交卡',
  })
  return rows
})

/**
 * 底图明暗（与首页首屏 `HomeView.vue` 的 `heroTone` 同口径）：后端 `tone` 描述的是**画面**明暗，
 * 文字始终是白字，`light`（浅色底图）用最深一档遮罩，`dark` 保持原来的渐变。
 * 没有站级预设（本地兜底图、自由文本规则名）时不知道画面明暗，按 `light` 取保守档。
 */
const heroTone = computed<'light' | 'dark'>(() => (props.preset?.tone === 'dark' ? 'dark' : 'light'))
</script>

<template>
  <BlurStage
    as="section"
    class="gh"
    data-hero
    :image="preset?.image ?? null"
    :rule="game.rule_system"
    :foreground="false"
    tone="dark"
    :data-tone="heroTone"
    aria-label="团概览"
  >
    <div class="gh__inner">
      <div class="gh__main">
        <p class="gh__crumbs">
          <RouterLink to="/recruit">招募</RouterLink>
          <span aria-hidden="true">/</span>
          <span>{{ game.rule_system || '未注明规则' }}</span>
          <template v-if="game.tags.length">
            <span aria-hidden="true">/</span>
            <span>{{ game.tags[0] }}</span>
          </template>
        </p>

        <p class="gh__status" :class="'gh__status--' + game.status">{{ game.status_display }}</p>

        <h1 class="gh__title">{{ game.title }}</h1>

        <p class="gh__tags">
          <span v-if="game.rule_system" class="c-tag c-tag--dark">{{ game.rule_system }}</span>
          <span v-for="name in game.tags" :key="name" class="c-tag c-tag--dark">{{ name }}</span>
        </p>

        <PersonLine
          class="gh__gm"
          :user="game.gm"
          :size="38"
          meta="GM · 点击可查看这位 GM 的 GM 卡与战报"
          on-dark
        />

        <dl class="gh__facts">
          <div v-for="row in facts" :key="row.k">
            <dt class="gh__k">{{ row.k }}</dt>
            <dd class="gh__v">{{ row.v }}</dd>
          </div>
        </dl>

        <p v-if="game.campaign_prev" class="gh__note">
          本团是「<RouterLink :to="'/games/' + game.campaign_prev.id">{{
            game.campaign_prev.title
          }}</RouterLink>」的后续。<template v-if="game.restrict_to_prev_members"
            >只有在上一团中被标记为到场的成员才能报名本团，其他人无法报名。</template
          >
        </p>
      </div>

      <div class="gh__side"><slot name="action" /></div>
    </div>
  </BlurStage>
</template>

<style scoped>
.gh {
  padding: calc(var(--header-h) + var(--sp-5)) var(--pad) var(--sp-7);
  color: var(--on-dark);
  /* 首屏贴着玻璃顶栏往上钻（.l-main--flush 已去掉主体顶部留白） */
  margin-top: calc(-1 * var(--header-h));
}

/** 业务界面遵循后端权限与隐私约束。 */
.gh[data-tone="light"]::after {
  background: var(--scrim-3);
}

.gh__inner {
  display: grid;
  gap: var(--sp-6);
  align-items: start;
}

.gh__main {
  min-width: 0;
}

.gh__crumbs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: 0 0 var(--sp-4);
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps);
  color: var(--on-dark-2);
  text-shadow: var(--hero-text-shadow);
}

/** 业务界面遵循后端权限与隐私约束。 */
.gh__crumbs a {
  display: inline-flex;
  align-items: center;
  min-height: 40px;
  margin-block: calc((var(--fs-xs) * var(--lh-body) - 40px) / 2);
  color: inherit;
  text-decoration: none;
}

.gh__crumbs a:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

/** 业务界面遵循后端权限与隐私约束。 */
.gh__status {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-wide);
  color: var(--on-dark);
  text-shadow: var(--hero-text-shadow);
}

.gh__status::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: var(--radius-pill);
  background: var(--dot, currentcolor);
}

.gh__status--recruiting {
  --dot: var(--st-recruiting);
}

.gh__status--closed_signup {
  --dot: var(--st-closed-signup);
}

.gh__status--running {
  --dot: var(--st-running);
}

.gh__status--finished {
  --dot: var(--on-dark-3);
}

.gh__status--cancelled {
  --dot: var(--st-cancelled);
}

.gh__title {
  margin: var(--sp-2) 0 var(--sp-3);
  font-size: var(--fs-h-display);
  font-weight: 400;
  letter-spacing: var(--ls-section);
  line-height: var(--lh-tight);
  text-shadow: var(--hero-text-shadow);
  overflow-wrap: anywhere;
}

.gh__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1);
  margin: 0 0 var(--sp-3);
}

.gh__gm {
  margin-bottom: var(--sp-2);
}

.gh__facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-4) var(--sp-5);
  max-width: 700px;
  margin: var(--sp-4) 0 0;
  padding-top: var(--sp-4);
  border-top: 1px solid var(--glass-line);
}

.gh__k {
  display: block;
  margin-bottom: var(--sp-1);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps);
  color: var(--on-dark-3);
  text-shadow: var(--hero-text-shadow);
}

.gh__v {
  margin: 0;
  font-size: var(--fs-md);
  line-height: var(--lh-card);
  text-shadow: var(--hero-text-shadow);
  overflow-wrap: anywhere;
}

.gh__note {
  max-width: 560px;
  margin: var(--sp-4) 0 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
  color: var(--on-dark-2);
  text-shadow: var(--hero-text-shadow);
}

.gh__note a {
  color: var(--on-dark);
}

.gh__side {
  min-width: 0;
}

@media (min-width: 768px) {
  .gh {
    padding-top: calc(var(--header-h) + var(--sp-7));
    padding-bottom: var(--sp-8);
  }

  .gh__facts {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (min-width: 1200px) {
  .gh__inner {
    grid-template-columns: minmax(0, 1fr) 352px;
    gap: var(--sp-7);
  }
}
</style>
