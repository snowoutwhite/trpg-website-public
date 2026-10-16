<script setup lang="ts">
/** GM 卡独立页 `/me/gm-card`。 */
import { RouterLink } from 'vue-router'
import PageHead from '../components/PageHead.vue'
import GmCardPanel from '../components/me/GmCardPanel.vue'
</script>

<template>
  <div class="c-sheet u-rise">
    <RouterLink class="c-back" to="/me#cards-gm">返回「我的」</RouterLink>

    <PageHead
      eyebrow="GM card · GM 卡"
      title="GM 卡"
      lead="想报名你所主持的团的玩家，会先阅读这一页。请在这里介绍你通常主持哪类剧本、游戏节奏如何，以及对玩家有什么期待。"
    />

    <GmCardPanel />
  </div>
</template>
