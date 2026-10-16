<script setup lang="ts">
/**
 * `/guide` —— 手册总览：页头 + 分区导航 + 三段（新人指南 / 术语速查 / 常见问题）。
 * 本体全在 `GuideHubView.vue`，这里只是路由的入口（路由表本波不许改，
 * 所以三条路由各留一个薄壳，组件只有一份）。
 */
import GuideHubView from './GuideHubView.vue'
</script>

<template>
  <GuideHubView />
</template>
