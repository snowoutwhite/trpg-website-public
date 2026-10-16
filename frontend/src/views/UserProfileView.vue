<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import BlurStage from '../components/BlurStage.vue'
import CCard from '../components/CCard.vue'
import CEmpty from '../components/CEmpty.vue'
import CNotice from '../components/CNotice.vue'
import CPill from '../components/CPill.vue'
import LoadState from '../components/LoadState.vue'
import SectionHead from '../components/SectionHead.vue'
import { fetchPublicProfile, type GMCard, type PlayerCard, type PublicProfile } from '../api/profiles'
import { fetchCardPool, type PublicCard } from '../api/cards'
import { fetchReports, type ReportListItem } from '../api/reports'
import { fetchGames, type GameListItem } from '../api/games'
import { errorText } from '../lib/api-error'
import { formatDate, formatDateTime } from '../lib/datetime'
import { ruleArtFile } from '../lib/rule-art'
import { useAuthStore } from '../stores/auth'
import { useHomeStore } from '../stores/home'
import { useSiteStore } from '../stores/site'

const route = useRoute()
const site = useSiteStore()
const home = useHomeStore()
const auth = useAuthStore()
const { config } = storeToRefs(site)
const { user: me } = storeToRefs(auth)

const profile = ref<PublicProfile | null>(null)
const cards = ref<PublicCard[]>([])
const reports = ref<ReportListItem[]>([])
const hosted = ref<GameListItem[]>([])
/** 三段附属内容各自的读取失败文案：失败要和「真的没有」分开显示（缺陷 F12）。 */
const cardsError = ref('')
const reportsError = ref('')
const hostedError = ref('')
const loading = ref(true)
const error = ref('')

const userId = computed(() => String(route.params.id ?? ''))
const isMe = computed(() => Boolean(me.value) && String(me.value?.id) === userId.value)
const showLikes = computed(() => config.value.like_feature_enabled !== false)

const player = computed<PlayerCard | null>(() => profile.value?.player_card ?? null)
const gmCard = computed<GMCard | null>(() => profile.value?.gm_card ?? null)

/** 头部铺底用 TA 最常跑的那个规则的美术；没写偏好就回落默认图。 */
const headRule = computed(() => player.value?.preferred_rule_systems[0] ?? '')
const headPreset = computed(() => home.presetByName(headRule.value))

onMounted(async () => {
  await site.load()
  try {
    profile.value = await fetchPublicProfile(userId.value)
  } catch (e) {
    error.value = errorText(e, '这个人的个人空间暂时无法读取，请刷新后重试。', {
      not_found: '找不到这位成员，或者该账号已经注销。',
    })
    loading.value = false
    return
  }
  await home.load(Boolean(me.value))
  // 三块附属内容各自独立：任何一块读不到都不该把整页变成错误页
  const [pool, written, run] = await Promise.allSettled([
    fetchCardPool({ owner: userId.value, page_size: 12 }),
    fetchReports({ author: userId.value }),
    fetchGames({ gm: userId.value, ordering: '-start_at', page_size: 8 }),
  ])
  if (pool.status === 'fulfilled') cards.value = pool.value.results
  else cardsError.value = errorText(pool.reason, '公开角色卡暂时无法读取，请刷新后重试。')
  if (written.status === 'fulfilled') reports.value = written.value.results
  else reportsError.value = errorText(written.reason, '公开战报暂时无法读取，请刷新后重试。')
  if (run.status === 'fulfilled') hosted.value = run.value.results
  else hostedError.value = errorText(run.reason, '主持过的团暂时无法读取，请刷新后重试。')
  loading.value = false
})

/** 未公布时后端给 null；一律显示「未公布」，不显示 null，也不显示 0。 */
function levelText(card: PlayerCard | GMCard | null): string {
  if (!card || !showLikes.value) return '未公布'
  return card.level ? card.level_display : '未公布'
}

function levelNote(card: PlayerCard | GMCard | null): string {
  if (!showLikes.value) return '站主关闭了赞功能'
  if (!card) return ''
  if (card.reviews_received === null) {
    return '被评价次数满 ' + config.value.like_level_publish_threshold + ' 次后才会公布赞级别（「无评价」也算在内）'
  }
  return '基于 ' + card.reviews_received + ' 次匿名评价（含「无评价」）'
}

const stats = computed(() => {
  const out: { key: string; kicker: string; value: string }[] = [
    { key: 'played', kicker: '团次数', value: String(player.value?.games_played ?? 0) },
    { key: 'hosted', kicker: '主持', value: String(gmCard.value?.games_hosted ?? 0) },
  ]
  if (showLikes.value) {
    out.push({ key: 'pl-level', kicker: '玩家侧赞级别', value: levelText(player.value) })
    if (gmCard.value) out.push({ key: 'gm-level', kicker: 'GM 侧赞级别', value: levelText(gmCard.value) })
    else out.push({ key: 'role', kicker: '身份', value: '玩家' })
  } else {
    out.push({ key: 'role', kicker: '身份', value: gmCard.value ? 'GM · 玩家' : '玩家' })
  }
  return out
})

function cardArt(name: string): string {
  const preset = home.presetByName(name)
  return preset?.image?.card || preset?.image?.thumb || ruleArtFile(name)
}
</script>

<template>
  <div class="up">
    <LoadState :loading="loading" :error="error">
      <template v-if="profile">
        <!-- ============ ① 身份条 ============ -->
        <BlurStage
          class="head"
          as="header"
          tone="dark"
          :rule="headRule"
          :image="headPreset?.image ?? null"
          :foreground="false"
        >
          <div class="head__row">
            <img v-if="profile.user.avatar" class="head__face" :src="profile.user.avatar" alt="" />
            <span v-else class="head__face head__face--blank" aria-hidden="true">
              {{ profile.user.nickname.slice(0, 1) || '·' }}
            </span>

            <div class="head__who">
              <p class="u-kicker head__kicker">Member profile · 个人空间</p>
              <h1 class="head__name">{{ profile.user.nickname }}</h1>
              <p class="head__marks">
                <span class="idtag idtag--solid">PL</span>
                <span v-if="profile.user.is_gm" class="idtag idtag--solid">GM</span>
                <span v-for="name in player?.preferred_rule_systems ?? []" :key="name" class="idtag">
                  {{ name }}
                </span>
              </p>
            </div>

            <RouterLink v-if="isMe" class="head__edit c-btn c-btn--light" to="/me#cards-player">
              编辑我的卡
            </RouterLink>
          </div>

          <dl class="head__stats">
            <div v-for="item in stats" :key="item.key" class="head__stat">
              <dt class="u-kicker">{{ item.kicker }}</dt>
              <dd>{{ item.value }}</dd>
            </div>
          </dl>
        </BlurStage>

        <!-- ============ ② 玩家卡 ============ -->
        <section class="l-section" aria-label="玩家卡">
          <SectionHead
            kicker="Player card"
            title="玩家卡"
            lead="每个账号注册后都有一张玩家卡。此处显示的是 TA 选择公开的内容：雷点、常玩的规则，以及 TA 自己写的一段介绍。"
          />
          <div class="split">
            <div class="split__aside">
              <CCard class="box">
                <p class="u-kicker box__k">雷点</p>
                <p class="box__text">{{ player?.taboos || 'TA 暂时没有填写。' }}</p>
              </CCard>
              <CCard class="box">
                <p class="u-kicker box__k">偏好规则</p>
                <p v-if="player?.preferred_rule_systems.length" class="box__chips">
                  <RouterLink
                    v-for="name in player.preferred_rule_systems"
                    :key="name"
                    class="c-chip"
                    :to="'/recruit?rule_system=' + encodeURIComponent(name)"
                  >
                    {{ name }}
                  </RouterLink>
                </p>
                <p v-else class="box__text">TA 暂时没有填写。</p>
              </CCard>
              <CCard v-if="showLikes" class="box">
                <p class="u-kicker box__k">玩家侧赞级别</p>
                <p class="box__level">{{ levelText(player) }}</p>
                <p class="u-small box__note">{{ levelNote(player) }}</p>
              </CCard>
            </div>

            <div class="split__main">
              <p v-if="player?.free_text" class="prose">{{ player.free_text }}</p>
              <CEmpty v-else compact title="TA 暂时没有填写这一部分" text="TA 暂时没有填写自我介绍、个人风格或跑团经验。" />
            </div>
          </div>
          <CNotice v-if="showLikes" class="likes-note" title="赞级别是怎么算出来的">
            <p class="likes-note__p">
              每个团结团后，到场的成员可以互相进行匿名的团后评价，对同团的每一位其他成员各评价一次，结果分为「赞」「倒赞」「无评价」三种。「无评价」就是在评价截止前没有提交评价，它既不算赞，也不算倒赞，但会计入被评价次数。
              一个人以玩家身份收到的评价计入玩家侧赞级别，作为 GM 收到的评价计入 GM 侧赞级别，两侧分开统计。
            </p>
            <p class="likes-note__p">
              赞级别看赞和倒赞各自占被评价次数的比例，从高到低分为「好评如潮」「好评居多」「中性」「倒赞居多」「差评如潮」五档，各档的分界由站主设置。「无评价」越多，赞和倒赞所占的比例都越低，赞级别越接近「中性」。
              被评价次数满 {{ config.like_level_publish_threshold }} 次之后（「无评价」也算在内），赞级别才会公布；在此之前显示为「未公布」。
              为了保护评价人的匿名，每条评价都要等被评价的人之后又参加并结束几个团，才会计入统计，「无评价」还要等该团的评价截止之后才会计入，因此赞级别的变化会比评价本身晚一些出现。
            </p>
            <p class="likes-note__p">
              部分 GM 放团时会要求报名者的玩家侧赞级别不低于某一档。赞级别低于要求或尚未公布的玩家，都无法报名这类团。
            </p>
          </CNotice>
        </section>

        <!-- ============ ③ GM 卡 ============ -->
        <section v-if="gmCard" class="l-section l-section--tone-2" aria-label="GM 卡">
          <SectionHead
            kicker="Game master card"
            title="GM 卡"
            lead="一个人作为玩家喜欢参加的团和作为 GM 喜欢主持的团可能不同，因此 GM 卡的统计数据和介绍文字都与玩家卡分开。"
          />
          <div class="split">
            <div class="split__aside">
              <CCard class="box">
                <p class="u-kicker box__k">主持团次数</p>
                <p class="box__level">{{ gmCard.games_hosted }}</p>
              </CCard>
              <CCard v-if="showLikes" class="box">
                <p class="u-kicker box__k">GM 侧赞级别</p>
                <p class="box__level">{{ levelText(gmCard) }}</p>
                <p class="u-small box__note">{{ levelNote(gmCard) }}</p>
              </CCard>
            </div>
            <div class="split__main">
              <p v-if="gmCard.style_text" class="prose">{{ gmCard.style_text }}</p>
              <CEmpty v-else compact title="TA 暂时没有填写这一部分" text="TA 暂时没有填写自己作为 GM 的主持风格。" />
            </div>
          </div>
        </section>

        <!-- ============ ④ 公开角色卡 ============ -->
        <section class="l-section" aria-label="公开的角色卡">
          <SectionHead kicker="Characters in play" title="公开的角色卡">
            <template #aside>
              <RouterLink class="c-textlink" :to="'/cards?owner=' + userId">
                在卡池里看 TA 的全部公开卡 →
              </RouterLink>
            </template>
          </SectionHead>
          <CNotice v-if="cardsError" tone="danger">{{ cardsError }}</CNotice>
          <div v-else-if="cards.length" class="grid">
            <RouterLink v-for="card in cards" :key="card.id" class="pic" :to="'/cards/' + card.id">
              <img class="pic__img" :src="cardArt(card.rule_system)" alt="" loading="lazy" />
              <span class="pic__cap">
                <span class="pic__tags">
                  <CPill tone="off">{{ card.rule_system }}</CPill>
                  <CPill :tone="card.status === 'alive' ? 'ok' : 'off'">{{ card.status_display }}</CPill>
                </span>
                <strong class="pic__name">{{ card.name }}</strong>
                <span class="pic__meta u-small">参团 {{ card.play_count }} 次</span>
              </span>
            </RouterLink>
          </div>
          <CEmpty
            v-else
            title="没有公开的角色卡"
            text="TA 暂时没有公开的角色卡。设为私密的角色卡不会显示在此处，其他人也无法搜索到。"
          />
        </section>

        <!-- ============ ⑤ 公开战报 ============ -->
        <section class="l-section l-section--tone-3" aria-label="公开的战报">
          <SectionHead
            kicker="What was written down"
            title="公开的战报"
            lead="TA 在团结束后写下的记录。其中设为仅登录成员可见的战报，未登录的访客在此处看不到。"
          />
          <CNotice v-if="reportsError" tone="danger">{{ reportsError }}</CNotice>
          <div v-else-if="reports.length" class="rows">
            <article v-for="item in reports" :key="item.id" class="row">
              <img class="row__thumb" :src="cardArt(item.game.rule_system)" alt="" loading="lazy" />
              <div class="row__main">
                <h3 class="row__title">
                  <RouterLink :to="'/reports/' + item.id">{{ item.title }}</RouterLink>
                  <CPill v-if="item.is_featured" tone="ok">站主精选</CPill>
                </h3>
                <p class="row__meta">
                  <span>{{ item.game.rule_system }}</span>
                  <span>团：{{ item.game.title }}</span>
                  <span>{{ formatDate(item.created_at) }}</span>
                </p>
                <p v-if="item.excerpt" class="row__sub">{{ item.excerpt }}</p>
              </div>
            </article>
          </div>
          <CEmpty v-else title="还没有公开的战报" text="TA 设为私密或仅登录成员可见的战报，不会在此处列出。" />
        </section>

        <!-- ============ ⑥ 主持过的团 ============ -->
        <section v-if="profile.user.is_gm" class="l-section" aria-label="主持过的团">
          <SectionHead
            kicker="At the table"
            title="主持过的团"
            lead="此处只列出 TA 主持过的团。每个团的成员名单只对该团的成员可见，不会在此处显示。"
          />
          <CNotice v-if="hostedError" tone="danger">{{ hostedError }}</CNotice>
          <div v-else-if="hosted.length" class="rows">
            <article v-for="item in hosted" :key="item.id" class="row">
              <img class="row__thumb" :src="cardArt(item.rule_system)" alt="" loading="lazy" />
              <div class="row__main">
                <h3 class="row__title">
                  <RouterLink :to="'/games/' + item.id">{{ item.title }}</RouterLink>
                  <CPill tone="off">{{ item.status_display }}</CPill>
                </h3>
                <p class="row__meta">
                  <span>{{ item.rule_system }}</span>
                  <span>{{ formatDateTime(item.start_at) }}</span>
                  <span>{{ item.occupied_seats }} / {{ item.max_players }} 人</span>
                </p>
              </div>
            </article>
          </div>
          <CEmpty v-else title="TA 暂时没有主持过团" text="TA 主持过的团会显示在此处。" />
          <p class="u-small privacy">
            本页不显示邮箱，也不显示任何一条评价是谁写的。赞和倒赞只以赞级别的形式显示；被评价次数未达到本站规定的次数时，赞级别也不会显示。
          </p>
        </section>
      </template>
    </LoadState>
  </div>
</template>

<style scoped>
/* ---------- 赞级别说明 ---------- */
.likes-note {
  margin-top: var(--sp-6);
}

.likes-note__p {
  margin: 0;
}

.likes-note__p + .likes-note__p {
  margin-top: var(--sp-2);
}

/* ---------- ① 身份条 ---------- */
.head {
  padding: var(--sec-y-tight) var(--pad);
  color: var(--on-dark);
}

/** 遮罩换成 83% 满铺（--scrim-3），最不利底图下 --on-dark-kicker 仍 ≥ 4.5:1。 */
.head::after {
  background: var(--scrim-3);
}

.head__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-5);
}

.head__face {
  flex: none;
  width: 86px;
  height: 86px;
  object-fit: cover;
  border-radius: var(--radius-pill);
  background: var(--avatar-bg);
}

.head__face--blank {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--fs-h-section);
  color: var(--ink-soft); /** 业务界面遵循后端权限与隐私约束。 */
}

.head__who {
  min-width: 0;
  flex: 1 1 260px;
}

.head__kicker {
  color: var(--on-dark-kicker);
}

.head__name {
  margin: var(--sp-2) 0 var(--sp-3);
  font-size: var(--fs-h-display);
  font-weight: 400;
  line-height: var(--lh-tight);
  letter-spacing: var(--ls-display);
  color: var(--on-dark);
  text-shadow: var(--text-shadow-dark);
  overflow-wrap: anywhere;
}

.head__marks {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin: 0;
}

.idtag {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 11px;
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps);
  color: var(--on-dark);
  background: var(--glass-dark-1);
  border: 1px solid var(--glass-line);
  border-radius: var(--radius-pill);
}

.idtag--solid {
  color: var(--brand-ink);
  background: var(--white);
  border-color: var(--white);
}

.head__edit {
  flex: none;
}

.head__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  margin: var(--sp-6) 0 0;
  background: var(--glass-line);
  border: 1px solid var(--glass-line);
  border-radius: var(--radius);
  overflow: hidden;
}

/** 最不利底图（纯白）下白字仍 ≥ 4.5:1。 */
.head__stat {
  padding: var(--sp-4);
  background: var(--scrim-3);
}

.head__stat dt {
  color: var(--on-dark-kicker);
}

.head__stat dd {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-2xl);
  line-height: var(--lh-tight);
  letter-spacing: var(--ls-section);
  color: var(--on-dark);
}

/* ---------- ②③ 两栏 ---------- */
.split {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-6);
}

.split__aside {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.box__k {
  margin: 0 0 var(--sp-2);
}

.box__text {
  margin: 0;
  font-size: var(--fs-md);
  line-height: var(--lh-read);
  color: var(--ink-soft);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.box__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin: 0;
}

.box__level {
  margin: 0;
  font-size: var(--fs-xl);
  line-height: var(--lh-tight);
}

.box__note {
  margin: var(--sp-2) 0 0;
  color: var(--ink-muted);
}

.prose {
  margin: 0;
  font-size: var(--fs-md);
  line-height: 2;
  color: var(--ink-soft);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

/* ---------- ④ 图卡网格 ---------- */
.grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-3);
}

.pic {
  position: relative;
  display: block;
  min-height: 220px;
  border-radius: var(--radius);
  overflow: hidden;
  color: var(--on-dark);
  text-decoration: none;
  background: var(--thumb-bg);
}

.pic__img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.pic__cap {
  position: relative;
  display: block;
  padding: var(--sp-8) var(--sp-4) var(--sp-4);
  background: linear-gradient(to top, var(--cap-scrim-2), var(--cap-scrim-1) 55%, transparent);
}

.pic__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

/** `.c-pill` 是 inline-flex，`text-overflow` 对 flex 容器不生效，这里改成 inline-block */
.pic__tags .c-pill {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  line-height: 20px;
  text-overflow: ellipsis;
}

.pic__name {
  display: block;
  margin-top: var(--sp-2);
  font-size: var(--fs-xl);
  font-weight: 400;
  line-height: var(--lh-card);
  text-shadow: var(--text-shadow-dark);
}

.pic__meta {
  display: block;
  margin-top: var(--sp-1);
  color: var(--on-dark-2);
}

/* ---------- ⑤⑥ 行列表 ---------- */
.rows {
  border-top: 1px solid var(--line);
}

.row {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  align-items: start;
  gap: var(--sp-2) var(--sp-4);
  padding: var(--sp-4) 0;
  border-bottom: 1px solid var(--line);
}

.row__thumb {
  width: 72px;
  height: 54px;
  object-fit: cover;
  border-radius: var(--radius);
  background: var(--thumb-bg);
}

.row__main {
  min-width: 0;
  /** 业务界面遵循后端权限与隐私约束。 */
  overflow-wrap: anywhere;
}

.row__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: 400;
  line-height: var(--lh-card);
}

/** 业务界面遵循后端权限与隐私约束。 */
.row__title a {
  display: inline-flex;
  align-items: center;
  min-height: 40px;
  color: var(--ink);
  text-decoration: none;
}

.row__title a:hover {
  text-decoration: underline;
  text-underline-offset: 4px;
}

.row__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-4);
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-wide);
  color: var(--ink-muted);
}

.row__sub {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-read);
  color: var(--ink-muted);
  overflow-wrap: anywhere;
}

.privacy {
  margin: var(--sp-6) 0 0;
  line-height: var(--lh-read);
  color: var(--ink-faint);
}

@media (min-width: 768px) {
  .head {
    padding: var(--sec-y) var(--pad);
  }

  .head__face {
    width: 118px;
    height: 118px;
  }

  .head__stats {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .split {
    grid-template-columns: 330px minmax(0, 1fr);
    gap: var(--sp-8);
  }

  .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .row {
    grid-template-columns: 88px minmax(0, 1fr);
    align-items: center;
  }

  .row__thumb {
    width: 88px;
    height: 64px;
  }
}

@media (min-width: 1200px) {
  .grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
</style>
