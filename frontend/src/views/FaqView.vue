<script setup lang="ts">
/**
 * `/faq` —— 手册的「常见问题」段。薄壳：渲染同一个 `GuideHubView`，
 * 把问答段顶到首位（落地即在这一段的标题上，不用滚）。
 */
import GuideHubView from './GuideHubView.vue'
</script>

<template>
  <GuideHubView focus="faq" />
</template>
