<script setup lang="ts">
/**
 * 懒加载图片：优先用浏览器原生 `loading="lazy"`，不支持时才退回 IntersectionObserver。
 *
 * 为什么两套：微信内置浏览器（X5 / 旧 WKWebView）对原生 lazy 的支持不确定，
 * 相册一屏几十张缩略图又都要带 Cookie 走鉴权视图，不能一次性全发出去。
 * 判定依据是 `'loading' in HTMLImageElement.prototype`（特性检测，不嗅探 UA）。
 *
 * 图片一律用 `<img src>` 直取鉴权路径，让浏览器自己带会话 Cookie 与缓存，
 * **不 fetch 成 blob**（那样会多一份内存副本、丢掉缓存，还要手动回收 objectURL）。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = withDefaults(defineProps<{ src: string; alt?: string }>(), { alt: '' })

const el = ref<HTMLImageElement | null>(null)
/** 真正写进 src 的地址：没轮到它之前是空的，浏览器不会发请求。 */
const shown = ref('')
const loaded = ref(false)
const failed = ref(false)
let observer: IntersectionObserver | null = null

function stop(): void {
  observer?.disconnect()
  observer = null
}

onMounted(() => {
  const nativeLazy =
    typeof HTMLImageElement !== 'undefined' && 'loading' in HTMLImageElement.prototype
  if (nativeLazy || typeof IntersectionObserver === 'undefined') {
    shown.value = props.src
    return
  }
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        shown.value = props.src
        stop()
      }
    },
    // 提前一屏开始取，滚动时不至于看到空框
    { rootMargin: '200px' },
  )
  if (el.value) observer.observe(el.value)
})

onBeforeUnmount(stop)
</script>

<template>
  <img
    ref="el"
    class="lazy"
    :class="{ 'lazy--in': loaded, 'lazy--bad': failed }"
    :src="shown || undefined"
    :alt="alt"
    loading="lazy"
    decoding="async"
    @load="loaded = true"
    @error="failed = true"
  />
</template>

<style scoped>
.lazy {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  background: var(--bg-2);
  opacity: 0;
  transition: opacity var(--dur) var(--ease);
}

.lazy--in {
  opacity: 1;
}

.lazy--bad {
  opacity: 1;
  background: var(--bg-2);
}

@media (prefers-reduced-motion: reduce) {
  .lazy {
    transition: none;
    opacity: 1;
  }
}
</style>
