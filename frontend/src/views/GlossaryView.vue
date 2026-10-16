<script setup lang="ts">
/**
 * `/glossary` —— 手册的「术语速查」段。薄壳：渲染同一个 `GuideHubView`，
 * 把术语段顶到首位（落地即在这一段的标题上，不用滚）。
 */
import GuideHubView from './GuideHubView.vue'
</script>

<template>
  <GuideHubView focus="glossary" />
</template>
