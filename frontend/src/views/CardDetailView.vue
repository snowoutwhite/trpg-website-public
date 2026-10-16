<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import BlurStage from '../components/BlurStage.vue'
import CCard from '../components/CCard.vue'
import CNotice from '../components/CNotice.vue'
import LoadState from '../components/LoadState.vue'
import { fetchCard, type CardPlay, type PublicCard } from '../api/cards'
import { errorStatus, errorText } from '../lib/api-error'
import { cardArt } from '../lib/card-display'
import { formatDate, formatDateTime } from '../lib/datetime'
import { useAuthStore } from '../stores/auth'
import { useHomeStore } from '../stores/home'

const route = useRoute()
const auth = useAuthStore()
const home = useHomeStore()
const { authenticated, user } = storeToRefs(auth)

const card = ref<PublicCard | null>(null)
const loading = ref(true)
const error = ref('')
const needLogin = ref(false)

onMounted(async () => {
  void home.load(authenticated.value)
  try {
    card.value = (await fetchCard(String(route.params.id ?? ''))) as PublicCard
  } catch (e) {
    if (errorStatus(e) === 401) {
      needLogin.value = true
      error.value = ''
    } else {
      // 404 是「不公开 或 不存在」的合并答案，不能说成「这张卡不存在」——
      // 那样等于替后端否认了一个可能存在的对象。
      error.value = errorText(e, '这张角色卡暂时无法读取，请刷新后重试。', {
        not_found: '这张卡不存在，或尚未公开。',
      })
    }
  } finally {
    loading.value = false
  }
})

const isMine = computed(() => Boolean(card.value && user.value && card.value.owner.id === user.value.id))

const loginNext = computed(() => '/auth/login?next=' + encodeURIComponent(route.fullPath))

const art = computed(() =>
  card.value ? cardArt(home.presetByName(card.value.rule_system), card.value.rule_system, 'full') : null,
)

/** 事实网格。公开性两档的话术要写清后果，不能只给一个「公开 / 私密」。 */
const facts = computed<{ k: string; v: string }[]>(() => {
  const data = card.value
  if (!data) return []
  return [
    { k: '规则', v: data.rule_system || '未填' },
    { k: '公开性', v: data.is_public ? '公开（在卡池里，登录可下载）' : '私密（只有卡主看得到）' },
    { k: '状态', v: data.status_display },
    { k: '参团次数', v: data.play_count + ' 次' },
    { k: '建卡时间', v: formatDate(data.created_at) },
  ]
})

/**
 * 参团记录。后端只存 `game_id` / `played_at`，团名等由 games 注册的 provider 补
 * （`apps/charactercards/services.py:games_played_for`）；**团被删掉时补不上**，
 * 这类条目降级成一行不可点的说明，不伪造团名、也不留一个必然 404 的链接。
 */
function playTitle(play: CardPlay): string {
  return play.title || '此团已经不在站里了'
}
</script>

<template>
  <div class="cd u-rise">
    <RouterLink class="c-back" to="/cards">
      <AppIcon name="back" :size="16" />
      角色卡池
    </RouterLink>

    <CNotice v-if="needLogin" tone="brand" title="这张角色卡没有公开">
      如果这是你自己的角色卡，请先<RouterLink :to="loginNext">登录</RouterLink>
      再查看。
    </CNotice>

    <LoadState v-else :loading="loading" :error="error">
      <CCard v-if="card" as="article" flush class="cd-card">
        <BlurStage
          class="cd-hero"
          :image="art?.image ?? null"
          :rule="card.rule_system"
          size="full"
          tone="dark"
          :foreground="false"
        >
          <p class="u-kicker cd-hero__kicker">Character sheet</p>
          <h1 class="u-h-section cd-hero__title">{{ card.name }}</h1>
          <p class="cd-hero__tags">
            <span v-if="card.rule_system" class="c-tag c-tag--dark">{{ card.rule_system }}</span>
            <span class="c-tag c-tag--dark">{{ card.status_display }}</span>
            <span class="c-tag c-tag--dark">{{ card.is_public ? '公开' : '私密' }}</span>
          </p>
        </BlurStage>

        <div class="cd-body">
          <div class="cd-main">
            <dl class="facts">
              <div v-for="fact in facts" :key="fact.k" class="facts__cell">
                <dt class="u-kicker">{{ fact.k }}</dt>
                <dd>{{ fact.v }}</dd>
              </div>
            </dl>

            <h2 class="cd-sub">参与过的团</h2>
            <div class="rows">
              <div v-for="play in card.games_played" :key="play.game_id" class="row">
                <span class="row__t">
                  <RouterLink v-if="play.title" :to="'/games/' + play.game_id">
                    {{ play.title }}
                  </RouterLink>
                  <span v-else class="u-muted">{{ playTitle(play) }}</span>
                </span>
                <span class="row__d u-small">结团 {{ formatDateTime(play.finished_at || play.played_at) }}</span>
              </div>
              <p v-if="!card.games_played.length" class="rows__none u-small">
                这张角色卡暂时没有参团记录。使用它参加的团结团后，这里会增加一条记录，参团次数也会加一。
              </p>
            </div>

            <p class="u-small cd-tiny">
              参团记录属于这张角色卡本身，与上传的文件无关：即使卡主更换了角色卡文件，这些记录也会保留。
            </p>
          </div>

          <aside class="cd-side">
            <RouterLink class="owner" :to="'/users/' + card.owner.id">
              <img v-if="card.owner.avatar" class="owner__face" :src="card.owner.avatar" alt="" />
              <span v-else class="owner__face owner__face--blank" aria-hidden="true"></span>
              <span class="owner__who">
                <span class="u-kicker">持卡人</span>
                <b>{{ card.owner.nickname }}</b>
              </span>
            </RouterLink>

            <div class="dlbox">
              <!-- download_url 是后端下发的同源鉴权路径，只有 can_download 为真时非空 -->
              <template v-if="card.can_download && card.download_url">
                <a class="c-btn c-btn--block" :href="card.download_url">
                  <AppIcon name="download" :size="18" />
                  下载角色卡文件
                </a>
                <p class="u-small dlbox__note">你下载这张角色卡时，卡主不会收到通知。</p>
              </template>
              <template v-else-if="!card.has_file">
                <p class="u-kicker">暂无文件</p>
                <p class="u-small dlbox__note">
                  这张角色卡目前只填写了基本信息，卡主还没有上传角色卡文件。
                </p>
              </template>
              <template v-else-if="authenticated === false">
                <p class="u-kicker">登录后才能下载</p>
                <p class="u-small dlbox__note">
                  角色卡的名称、规则和参团次数所有人都能查看，角色卡文件只有登录后才能下载。
                </p>
                <RouterLink class="c-btn c-btn--block dlbox__btn" :to="loginNext">
                  登录后下载
                </RouterLink>
                <RouterLink class="c-textlink" to="/auth/signup">注册账号</RouterLink>
              </template>
              <template v-else>
                <p class="u-kicker">暂时无法下载</p>
                <p class="u-small dlbox__note">
                  这张角色卡的文件没有向你开放下载。如果你的账号正处于封禁状态或已注销，也将无法下载。
                </p>
              </template>
            </div>

            <p class="u-small cd-tiny">
              {{
                card.status === 'torn'
                  ? '这张角色卡已经撕卡：文件仍然可以下载，但不能再用于报名。'
                  : '角色卡撕卡后，文件仍然可以下载，但不能再用于报名。'
              }}
            </p>

            <RouterLink v-if="isMine" class="c-textlink" :to="'/me/cards/' + card.id">
              管理这张角色卡 →
            </RouterLink>
          </aside>
        </div>
      </CCard>
    </LoadState>
  </div>
</template>

<style scoped>
.cd-card {
  margin-top: var(--sp-4);
}

/* 抬头：同图虚化铺底 + 压白字（v2 cards.html .sheet-top.blur-stage） */
.cd-hero {
  padding: var(--sp-6) var(--sp-4) var(--sp-5);
  color: var(--on-dark);
  text-shadow: var(--text-shadow-dark);
}

.cd-hero__kicker {
  margin: 0;
  color: var(--on-dark-kicker);
}

.cd-hero__title {
  margin: var(--sp-2) 0 var(--sp-3);
  overflow-wrap: anywhere;
}

.cd-hero__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1);
  margin: 0;
}

/** 业务界面遵循后端权限与隐私约束。 */
.cd-hero__tags .c-tag {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cd-body {
  display: grid;
  gap: var(--sp-6);
  padding: var(--sp-5) var(--sp-4) var(--sp-6);
}

/* 事实网格（v2 .facts：1px 缝当分隔线） */
.facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  margin: 0;
  background: var(--line);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}

.facts__cell {
  padding: var(--sp-3) var(--sp-4);
  background: var(--white);
}

/* 奇数格时最后一格通栏：`.facts` 用 1px 缝当分隔线（底色是 --line），
   留一个空位会在版面上露出一块灰方块（1440 复看发现） */
.facts__cell:last-child:nth-child(odd) {
  grid-column: 1 / -1;
}

.facts__cell dt {
  margin: 0 0 var(--sp-2);
}

.facts__cell dd {
  margin: 0;
  font-size: var(--fs-base);
  line-height: var(--lh-card);
  color: var(--ink);
  overflow-wrap: anywhere;
}

.cd-sub {
  margin: var(--sp-6) 0 var(--sp-2);
  font-size: var(--fs-lg);
  line-height: var(--lh-card);
}

.rows {
  border-top: 1px solid var(--line);
}

.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-1) var(--sp-4);
  padding: var(--sp-1) 0;
  border-bottom: 1px solid var(--line);
}

.row__t {
  min-width: 0;
  font-size: var(--fs-base);
  overflow-wrap: anywhere;
}

.row__t a {
  display: inline-block;
  min-height: 40px;
  padding: var(--sp-2) 0;
  line-height: 24px;
  color: var(--brand-ink);
  text-decoration: none;
}

.row__t a:hover {
  text-decoration: underline;
  text-underline-offset: 4px;
}

.row__d {
  flex: none;
}

.rows__none {
  margin: 0;
  padding: var(--sp-4) 0;
  border-bottom: 1px solid var(--line);
}

.cd-tiny {
  margin: var(--sp-3) 0 0;
  line-height: var(--lh-body);
}

.cd-side {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.owner {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-2) 0;
  min-height: 44px;
  color: inherit;
  text-decoration: none;
}

.owner__face {
  flex: none;
  width: 40px;
  height: 40px;
  object-fit: cover;
  border-radius: var(--radius-pill);
  background: var(--avatar-bg);
}

.owner__who {
  display: grid;
  gap: var(--sp-1);
  min-width: 0;
}

.owner__who b {
  font-weight: 400;
  font-size: var(--fs-lg);
  overflow-wrap: anywhere;
}

.dlbox {
  padding: var(--sp-4);
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.dlbox__note {
  margin: var(--sp-2) 0 0;
  line-height: var(--lh-body);
}

.dlbox__btn {
  margin-top: var(--sp-3);
}

/* 「登录后下载」是块按钮，紧跟着的「注册账号」文字链要自己让开一行 */
.dlbox .c-textlink {
  display: inline-block;
  margin-top: var(--sp-2);
}

@media (min-width: 768px) {
  .cd-hero {
    padding: var(--sp-7) var(--sp-6) var(--sp-6);
  }

  .cd-body {
    padding: var(--sp-6);
  }
}

/* 宽屏：正文与「持卡人 + 下载」两栏（v2 .sheet-grid 1fr / 300px） */
@media (min-width: 1200px) {
  .cd-body {
    grid-template-columns: minmax(0, 1fr) 300px;
    gap: var(--sp-7);
  }
}
</style>
