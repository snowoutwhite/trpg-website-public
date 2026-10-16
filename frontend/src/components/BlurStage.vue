<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed } from 'vue'
import type { RuleImageTiers } from '../api/home'
import { RULE_ART_DEFAULT, ruleArtFile } from '../lib/rule-art'

const props = withDefaults(
  defineProps<{
    /** 直接给的图片地址（第 3 优先）。 */
    file?: string
    /** 前景清晰图的替代文字。给空串表示纯装饰（会带 alt="" + aria-hidden）。 */
    alt?: string
    /** 遮罩方向：dark = 压白字（默认），light = 压墨字。与后端预设的 `tone` 同名同义。 */
    tone?: 'dark' | 'light'
    /** 规则名，用于回落本地规则美术（第 4 优先）。 */
    rule?: string
    /** 后端规则预设自带的三档图（第 1/2 优先）。 */
    image?: RuleImageTiers | null
    /** 想要哪一档；给不出就自动降级到别的档。 */
    size?: keyof RuleImageTiers
    /** 是否渲染前景清晰图。只想要一块虚化底（例如压文字的首屏舞台）时给 false。 */
    foreground?: boolean
    /**
     * 前景图四边内缩的像素数。**这才是「同图虚化铺底」的招牌观感**：
     * 清晰图缩在中间，四周露出同一张图的模糊版当画框
     * （v2 `reports.html .rthumb img { inset: 10px }`、`resources.html .res-thumb img { inset: 22px }`）。
     * 0 = 铺满整块（v2 `recruit.html .g-card .stage img`）。
     */
    inset?: number
    as?: 'div' | 'section' | 'article' | 'header'
  }>(),
  { tone: 'dark', size: 'full', foreground: true, inset: 0, as: 'div' },
)

/** 同源相对路径或 http(s) 绝对地址；引号、括号、反斜杠、空白一律不收。 */
const SAFE_IMAGE_URL = /^(?:https?:\/\/[^"'()\\\s]+|\/[^"'()\\\s]*)$/

function pick(...candidates: (string | undefined | null)[]): string {
  for (const value of candidates) {
    // `//evil/x` 与 `/\\evil/x` 是协议相对地址（与 lib/url-guard.ts safeNextPath 同口径），一律拒绝
    if (value && SAFE_IMAGE_URL.test(value) && !/^\/[/\\]/.test(value)) return value
  }
  return ''
}

/** 最终用的图片地址；一定非空（最差也是 `RULE_ART_DEFAULT`）。 */
const src = computed(() =>
  pick(
    props.image?.[props.size],
    props.image?.full,
    props.image?.card,
    props.image?.thumb,
    props.file,
    props.rule ? ruleArtFile(props.rule) : null,
    RULE_ART_DEFAULT.file,
  ),
)

/** 铺底走 CSS 自定义属性：`--art` 给 `.c-blur-stage::before`，`--fg-inset` 给前景图。 */
const artStyle = computed(() => ({
  '--art': 'url("' + src.value + '")',
  '--fg-inset': props.inset + 'px',
  // 内缩时给清晰图一点圆角（v2 .rthumb img / .res-thumb img 都是 3px，并进 --radius）
  '--fg-radius': props.inset > 0 ? 'var(--radius)' : '0',
}))
</script>

<template>
  <component
    :is="as"
    class="c-blur-stage"
    :class="tone === 'light' ? 'c-blur-stage--light' : null"
    :style="artStyle"
  >
    <img
      v-if="foreground"
      class="c-blur-stage__fg"
      :src="src"
      :alt="alt ?? ''"
      :aria-hidden="alt ? undefined : 'true'"
      loading="lazy"
      decoding="async"
    />
    <div class="c-blur-stage__body"><slot /></div>
  </component>
</template>

<style scoped>
/** <img> 是替换元素：绝对定位时 right/bottom 不会把它撑开（CSS 2.1 §10.3.8）， */
.c-blur-stage__fg {
  position: absolute;
  inset: var(--fg-inset, 0px);
  width: calc(100% - 2 * var(--fg-inset, 0px));
  height: calc(100% - 2 * var(--fg-inset, 0px));
  object-fit: cover;
  border-radius: var(--fg-radius, 0);
}

/* 内容层压在图与遮罩之上 */
.c-blur-stage__body {
  position: relative;
  z-index: 1;
}
</style>
