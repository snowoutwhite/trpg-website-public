<script setup lang="ts">
/** 玩家卡独立页 `/me/player-card`。 */
import { RouterLink } from 'vue-router'
import PageHead from '../components/PageHead.vue'
import PlayerCardPanel from '../components/me/PlayerCardPanel.vue'
</script>

<template>
  <div class="c-sheet u-rise">
    <RouterLink class="c-back" to="/me#cards-player">返回「我的」</RouterLink>

    <PageHead
      eyebrow="Player card · 玩家卡"
      title="玩家卡"
      lead="GM 在审批报名和准备剧本时会阅读这一页。请把你的雷点写清楚，这样 GM 可以提前避开你不接受的内容。"
    />

    <PlayerCardPanel />
  </div>
</template>
