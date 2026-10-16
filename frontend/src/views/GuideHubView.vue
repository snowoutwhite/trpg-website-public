<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import BlurStage from '../components/BlurStage.vue'
import CEmpty from '../components/CEmpty.vue'
import LoadState from '../components/LoadState.vue'
import {
  fetchFaqs,
  fetchGlossary,
  fetchGuides,
  type FaqItem,
  type GlossaryTerm,
  type GuideSummary,
} from '../api/content'
import { errorText } from '../lib/api-error'
import { GENERIC_ART } from '../lib/rule-art'

type SectionKey = 'guide' | 'glossary' | 'faq'
type Block = 'hero' | 'nav' | SectionKey

const props = withDefaults(defineProps<{ focus?: SectionKey | '' }>(), { focus: '' })

const route = useRoute()

const SECTION_ORDER: SectionKey[] = ['guide', 'glossary', 'faq']

const SECTIONS: Record<SectionKey, { title: string; to: string; lead: string }> = {
  guide: {
    title: '新人指南',
    to: '/guide',
    lead: '站主写的入门篇，按顺序读。第一次来建议从头翻，一篇几分钟。',
  },
  glossary: {
    title: '术语速查',
    to: '/glossary',
    lead: '别人说 KP、车卡、撕卡的时候不用装懂。别名也能命中 —— 输入「守密人」会找到对应的词条。',
  },
  faq: {
    title: '常见问题',
    to: '/faq',
    lead: '下面这些答案对应站内当前的实际规则。规则改了，这里也会改。',
  },
}

/** 页头图 = 术语/指南两段共用的那张书堆（同图虚化铺底：模糊版铺底，清晰版当前景）。 */
const heroArt = GENERIC_ART.books.file

const guides = ref<GuideSummary[]>([])
const terms = ref<GlossaryTerm[]>([])
const faqs = ref<FaqItem[]>([])
const loading = ref(true)
const guideError = ref('')
const termError = ref('')
const faqError = ref('')
const keyword = ref('')

/** 三段各拉各的：一段挂了另两段照常显示（LoadState 的 error 是分段的）。 */
onMounted(async () => {
  const [g, t, f] = await Promise.allSettled([fetchGuides(), fetchGlossary(), fetchFaqs()])
  if (g.status === 'fulfilled') guides.value = g.value
  else guideError.value = errorText(g.reason, '新人指南暂时无法读取，请刷新后重试。')
  if (t.status === 'fulfilled') terms.value = t.value
  else termError.value = errorText(t.reason, '术语表暂时无法读取，请刷新后重试。')
  if (f.status === 'fulfilled') faqs.value = f.value
  else faqError.value = errorText(f.reason, '常见问题暂时无法读取，请刷新后重试。')
  loading.value = false
  await nextTick()
  jumpToHashedTerm()
})

/** 目标段排第一，分区导航紧随其后，其余两段按 v2 顺序跟上。 */
const blocks = computed<Block[]>(() => {
  const focused = props.focus
  if (!focused) return ['hero', 'nav', ...SECTION_ORDER]
  return [focused, 'nav', ...SECTION_ORDER.filter((key) => key !== focused)]
})

const counts = computed<Record<SectionKey, number>>(() => ({
  guide: guides.value.length,
  glossary: terms.value.length,
  faq: faqs.value.length,
}))

/** 搜索命中范围：术语本身、别名、释义正文（v2 同口径）。 */
const matched = computed(() => {
  const key = keyword.value.trim().toLowerCase()
  if (!key) return terms.value
  return terms.value.filter(
    (term) =>
      term.term.toLowerCase().includes(key) ||
      term.definition.toLowerCase().includes(key) ||
      term.aliases.some((alias) => alias.toLowerCase().includes(key)),
  )
})

const termCountText = computed(() => {
  const key = keyword.value.trim()
  if (!key) return '共 ' + terms.value.length + ' 条，按站主排的顺序'
  return '「' + key + '」命中 ' + matched.value.length + ' 条 / 共 ' + terms.value.length + ' 条'
})

function serial(index: number): string {
  return String(index + 1).padStart(2, '0')
}

function termAnchor(term: GlossaryTerm): string {
  return 'term-' + term.id
}

/** 段内锚点：`/glossary#term-7` 落地后滚到那一条。 */
function jumpToHashedTerm(): void {
  const hash = route.hash
  if (!hash.startsWith('#term-')) return
  document.getElementById(hash.slice(1))?.scrollIntoView({ block: 'start' })
}

/** 业务界面遵循后端权限与隐私约束。 */
watch(() => route.hash, jumpToHashedTerm)
</script>

<template>
  <div class="hub u-rise">
    <template v-for="block in blocks" :key="block">
      <!-- ===== 页头（只有 /guide 有；两个薄壳路由把目标段顶到首位，不再重复一遍总览） ===== -->
      <BlurStage
        v-if="block === 'hero'"
        as="header"
        class="hub-hero"
        tone="light"
        :file="heroArt"
        :foreground="false"
      >
        <div class="hub-hero__inner">
          <div class="hub-hero__text">
            <p class="u-kicker">Handbook · 手册</p>
            <h1 class="u-h-display hub-hero__title">手册</h1>
            <p class="u-lead hub-hero__lead">
              刚开始跑团时，最大的困难往往不是规则书太厚，而是第一次参加时不知道该做什么。本页提供三部分内容：写给新人的入门指南、帮助你理解跑团常用术语的术语表，以及关于本站规则的常见问题。这些内容都由站主维护，你看到的始终是最新版本。
            </p>
          </div>
          <figure class="hub-hero__fig">
            <img
              class="hub-hero__img"
              :src="heroArt"
              alt="桌上摊开的规则书与笔记"
              loading="lazy"
              decoding="async"
            />
            <figcaption class="u-small">规则书不必一次读完。建议先参加第一场团，之后再根据需要查阅。</figcaption>
          </figure>
        </div>
      </BlurStage>

      <!-- ===== 分区导航：三段各有自己的路由，点哪一格就落在哪一段的顶上 ===== -->
      <nav v-else-if="block === 'nav'" class="hub-nav" aria-label="手册分区">
        <RouterLink
          v-for="key in SECTION_ORDER"
          :key="key"
          class="hub-nav__item"
          :to="SECTIONS[key].to"
        >
          {{ SECTIONS[key].title }}
          <span class="hub-nav__count">{{ counts[key] }}</span>
        </RouterLink>
      </nav>

      <!-- ===== 三段 ===== -->
      <section v-else :id="block" class="hub-sec" :aria-labelledby="block + '-title'">
        <component
          :is="block === focus ? 'h1' : 'h2'"
          :id="block + '-title'"
          class="hub-sec__title"
          :class="block === focus ? 'u-h-display' : 'u-h-section'"
        >
          {{ SECTIONS[block].title }}
        </component>
        <p class="u-lead hub-sec__lead">{{ SECTIONS[block].lead }}</p>

        <!-- 一、新人指南：列表，正文在 /guide/:slug -->
        <template v-if="block === 'guide'">
          <LoadState
            :loading="loading"
            :error="guideError"
            :empty="!guides.length"
            empty-title="暂时没有新人指南"
            empty-text="站主暂时还没有发布指南。你可以先查看下方的术语表和常见问题，也可以报名参团后直接向 GM 请教。"
          >
            <p class="u-small hub-sec__count">共 {{ guides.length }} 篇</p>
            <RouterLink
              v-for="(guide, index) in guides"
              :key="guide.id"
              class="c-entry"
              :to="'/guide/' + guide.slug"
            >
              <span class="c-entry__no">{{ serial(index) }}</span>
              <span class="c-entry__body">
                <span class="c-entry__title">{{ guide.title }}</span>
              </span>
              <AppIcon class="c-entry__arrow" name="arrow" :size="18" />
            </RouterLink>
          </LoadState>
        </template>

        <!-- 二、术语速查：一次拉全、本地过滤、别名命中、每条一个锚点 -->
        <template v-else-if="block === 'glossary'">
          <div class="gl-search">
            <AppIcon class="gl-search__icon" name="search" :size="16" />
            <input
              v-model="keyword"
              class="c-input gl-search__input"
              type="search"
              placeholder="输入术语、别名或关键词"
              aria-label="搜索术语"
              autocomplete="off"
            />
          </div>
          <LoadState
            :loading="loading"
            :error="termError"
            :empty="!terms.length"
            empty-title="暂时没有收录术语"
            empty-text="站主暂时还没有录入术语。遇到不理解的词，可以直接向 GM 请教；站主会陆续把经常被问到的术语补充到这里。"
          >
            <p class="u-small hub-sec__count">{{ termCountText }}</p>
            <CEmpty
              v-if="!matched.length"
              compact
              title="没有找到相关术语"
              text="请尝试换一种说法或关键词再搜索，也可以直接向 GM 请教这个词。站主会陆续把经常被问到的术语补充到这里。"
            />
            <dl v-else class="gl-list">
              <div v-for="term in matched" :id="termAnchor(term)" :key="term.id" class="term">
                <dt class="term__head">
                  <span class="term__name">{{ term.term }}</span>
                  <span v-if="term.aliases.length" class="term__alias">
                    也称作 {{ term.aliases.join(' · ') }}
                  </span>
                </dt>
                <dd class="term__def">{{ term.definition }}</dd>
              </div>
            </dl>
          </LoadState>
        </template>

        <!-- 三、常见问题：原生 details/summary，键盘与读屏天然可用 -->
        <template v-else>
          <LoadState
            :loading="loading"
            :error="faqError"
            :empty="!faqs.length"
            empty-title="暂时没有收录常见问题"
            empty-text="如果你的问题没有在这里找到答案，可以在团里向 GM 请教，或者联系站主。"
          >
            <div class="faq">
              <details
                v-for="(faq, index) in faqs"
                :key="faq.id"
                class="qa"
                :open="index === 0"
              >
                <summary class="qa__q">
                  <span class="qa__text">{{ faq.question }}</span>
                  <AppIcon class="qa__icon" name="arrow" :size="15" />
                </summary>
                <p class="qa__a">{{ faq.answer }}</p>
              </details>
            </div>
          </LoadState>
        </template>
      </section>
    </template>
  </div>
</template>

<style scoped>
/** 页头使用同图虚化背景、清晰前景与双栏布局。 */
.hub-hero {
  border-radius: var(--radius-lg);
  padding: var(--sp-6) var(--sp-5);
}

.hub-hero__inner {
  display: grid;
  gap: var(--sp-5);
}

.hub-hero__text {
  min-width: 0;
}

.hub-hero__title {
  margin: var(--sp-2) 0 var(--sp-3);
}

.hub-hero__lead {
  margin: 0;
  max-width: 54ch;
}

.hub-hero__fig {
  margin: 0;
  min-width: 0;
}

.hub-hero__img {
  width: 100%;
  height: 186px;
  object-fit: cover;
  border-radius: var(--radius);
  box-shadow: var(--shadow-1);
}

.hub-hero__fig figcaption {
  margin-top: var(--sp-2);
}

/** hero 是 `BlurStage tone="light"`：一层浅 scrim（--scrim-light-1/-2，80% → 90%） */
.hub-hero .u-kicker,
.hub-hero__lead,
.hub-hero__fig figcaption {
  color: var(--ink-soft);
}

@media (min-width: 768px) {
  .hub-hero {
    padding: var(--sp-7);
  }

  .hub-hero__inner {
    grid-template-columns: 1.08fr 0.92fr;
    gap: var(--sp-7);
    align-items: center;
  }

  .hub-hero__img {
    height: 244px;
  }
}

/* ===================================================================
   分区导航（v2 .tabs 的样子，但每一格是一条真路由）
   =================================================================== */
.hub-nav {
  display: flex;
  gap: var(--sp-5);
  margin-top: var(--sp-6);
  overflow-x: auto;
  border-bottom: 1px solid var(--line);
  scrollbar-width: none;
}

.hub-nav::-webkit-scrollbar {
  display: none;
}

.hub-nav__item {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  min-height: 44px;
  margin-bottom: -1px;
  padding: 14px 0;
  font-size: var(--fs-sm);
  letter-spacing: var(--ls-wide);
  color: var(--ink-muted);
  text-decoration: none;
  white-space: nowrap;
  border-bottom: 1px solid transparent;
  transition: color var(--dur) var(--ease);
}

.hub-nav__item:hover {
  color: var(--ink);
}

.hub-nav__item.router-link-exact-active {
  color: var(--ink);
  border-bottom-color: var(--ink);
}

.hub-nav__count {
  font-size: var(--fs-2xs);
  letter-spacing: 0;
  color: var(--ink-faint);
}

.hub-nav__item.router-link-exact-active .hub-nav__count {
  color: var(--ink);
}

/* ===================================================================
   三段的共同壳：段间一条线 + 一段留白；第一段（薄壳路由的目标段）贴顶
   =================================================================== */
.hub-sec {
  margin-top: var(--sec-y-tight);
  padding-top: var(--sec-y-tight);
  border-top: 1px solid var(--line);
  /* 万一有人从别处带 #glossary / #faq 进来，锚点别被吸顶顶栏盖住 */
  scroll-margin-top: calc(var(--header-h) + var(--sp-4));
}

.hub-sec:first-child {
  margin-top: 0;
  padding-top: 0;
  border-top: 0;
}

/* 紧跟分区导航的那一段不用再画一条线（导航自己有下边线） */
.hub-nav + .hub-sec {
  border-top: 0;
  padding-top: var(--sp-6);
  margin-top: 0;
}

.hub-sec__title {
  margin: 0;
}

.hub-sec__lead {
  margin: var(--sp-3) 0 0;
  max-width: 62ch;
}

.hub-sec__count {
  margin: var(--sp-5) 0 var(--sp-2);
}

/* ===================================================================
   二、术语速查（v2 .gl-search / .term）
   =================================================================== */
.gl-search {
  position: relative;
  max-width: 320px;
  margin-top: var(--sp-5);
}

.gl-search__icon {
  position: absolute;
  left: var(--sp-3);
  top: 50%;
  transform: translateY(-50%);
  color: var(--ink-muted);
  pointer-events: none;
}

.gl-search__input {
  padding-left: var(--sp-7);
}

.gl-list {
  margin: var(--sp-2) 0 0;
}

.term {
  padding: var(--sp-4) 0;
  border-top: 1px solid var(--line);
  scroll-margin-top: calc(var(--header-h) + var(--sp-4));
}

.term:last-child {
  border-bottom: 1px solid var(--line);
}

.term__head {
  min-width: 0;
}

.term__name {
  font-size: var(--fs-lg);
  line-height: var(--lh-card);
  color: var(--ink);
}

.term__alias {
  display: block;
  margin-top: var(--sp-1);
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps-sm);
  line-height: var(--lh-body);
  color: var(--ink-faint);
}

.term__def {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-md);
  line-height: var(--lh-read);
  color: var(--ink-soft);
}

@media (min-width: 768px) {
  .term {
    display: grid;
    grid-template-columns: 196px minmax(0, 1fr);
    gap: var(--sp-1) var(--sp-6);
    padding: var(--sp-4) 0 var(--sp-4);
  }

  .term__def {
    margin-top: 0;
  }
}

/* ===================================================================
   三、常见问题（v2 .faq details/summary）
   =================================================================== */
.faq {
  margin-top: var(--sp-5);
  /* v2 .faq 是 820px 单栏；本站的长文净宽令牌就是 800（--max-narrow） */
  max-width: var(--max-narrow);
}

.qa {
  border-top: 1px solid var(--line);
}

.qa:last-of-type {
  border-bottom: 1px solid var(--line);
}

.qa__q {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  min-height: 56px;
  padding: var(--sp-4) 0;
  font-size: var(--fs-base);
  line-height: var(--lh-card);
  color: var(--ink);
  cursor: pointer;
  list-style: none;
}

/* 去掉 Safari/Chrome 的默认三角 */
.qa__q::-webkit-details-marker {
  display: none;
}

.qa__text {
  min-width: 0;
}

/* 图标表里没有独立的「下箭头」，用右箭头转 90°（组件目录本波不许改） */
.qa__icon {
  flex: none;
  color: var(--ink-muted);
  transform: rotate(90deg);
  transition: transform var(--dur) var(--ease);
}

.qa[open] .qa__icon {
  transform: rotate(-90deg);
}

.qa__a {
  margin: 0;
  padding: 0 0 var(--sp-5);
  font-size: var(--fs-md);
  line-height: var(--lh-read);
  color: var(--ink-muted);
  white-space: pre-wrap;
}
</style>
