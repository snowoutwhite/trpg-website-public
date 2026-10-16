<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import BlurStage from '../components/BlurStage.vue'
import CButton from '../components/CButton.vue'
import CNotice from '../components/CNotice.vue'
import LoadState from '../components/LoadState.vue'
import MarkdownView from '../components/MarkdownView.vue'
import SectionHead from '../components/SectionHead.vue'
import {
  deleteReport,
  fetchReport,
  fetchReports,
  reportAbuse,
  type ReportDetail,
  type ReportListItem,
} from '../api/reports'
import { ApiError } from '../api/http'
import { errorText } from '../lib/api-error'
import { formatDate, formatDateTime } from '../lib/datetime'
import { ruleArtFile } from '../lib/rule-art'
import { useAuthStore } from '../stores/auth'
import { useHomeStore } from '../stores/home'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const home = useHomeStore()
const { authenticated } = storeToRefs(auth)

const reportId = String(route.params.id ?? '')
const report = ref<ReportDetail | null>(null)
const loading = ref(true)
const error = ref('')

/** 同一个团的其他战报（v2 FROM THE SAME TABLE），拿不到就整段不渲染。 */
const siblings = ref<ReportListItem[]>([])

const abuseOpen = ref(false)
const abuseReason = ref('')
const abuseSending = ref(false)
const abuseError = ref('')
const abuseDone = ref('')

const confirmDelete = ref(false)
const deleting = ref(false)
const actionError = ref('')

const visibilityLabel = computed(() =>
  report.value?.visibility === 'same_game' ? '仅同团可见' : '公开',
)

const gameHash = computed(() => (report.value ? '/games/' + report.value.game.id + '#reports' : '/reports'))

onMounted(async () => {
  await auth.refresh()
  void home.load(authenticated.value === true)
  try {
    const detail = await fetchReport(reportId)
    report.value = detail
    document.title = detail.title + ' · 战报'
    try {
      const more = await fetchReports({ game: detail.game.id })
      siblings.value = more.results.filter((r) => r.id !== detail.id).slice(0, 3)
    } catch {
      siblings.value = []
    }
  } catch (e) {
    error.value =
      e instanceof ApiError && e.status === 404
        ? '这份战报不存在，或者作者没有对你公开。登录之后能看到的战报会多一些。'
        : errorText(e, '战报暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
})

async function onAbuse(): Promise<void> {
  if (!report.value || abuseSending.value) return
  const reason = abuseReason.value.trim()
  if (!reason) {
    abuseError.value = '请填写举报理由。'
    return
  }
  abuseSending.value = true
  abuseError.value = ''
  try {
    await reportAbuse(report.value.id, reason)
    abuseDone.value = '已经提交，站主会看到这条举报。处理结果以站内通知为准。'
    abuseOpen.value = false
    abuseReason.value = ''
  } catch (e) {
    abuseError.value = errorText(e, '提交失败，请稍后再试。')
  } finally {
    abuseSending.value = false
  }
}

async function onDelete(): Promise<void> {
  if (!report.value || deleting.value) return
  deleting.value = true
  actionError.value = ''
  try {
    await deleteReport(report.value.id)
    await router.replace({ name: 'reports' })
  } catch (e) {
    actionError.value = errorText(e, '战报删除失败，请稍后再试。')
    deleting.value = false
    confirmDelete.value = false
  }
}

function sizeText(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

/** 同团战报卡的底图 = 该团规则的美术（与列表页同一套取图顺序）。 */
function artFile(ruleSystem: string): string {
  const preset = home.presetByName(ruleSystem)
  return preset?.image.card || preset?.image.full || preset?.image.thumb || ruleArtFile(ruleSystem)
}

function excerptOf(item: ReportListItem): string {
  return (item.excerpt || '')
    .split('\n')
    .map((line) => line.replace(/^\s*(#{1,6}\s+|>\s?|[-*+]\s+|\d+\.\s+)/, '').trim())
    .filter(Boolean)
    .join(' ')
    .replace(/[*_`]/g, '')
}
</script>

<template>
  <div class="post u-rise">
    <LoadState :loading="loading" :error="error">
      <template v-if="report">
        <!-- ===== 顶部「所属团」细带：规则 + 团名 + 结团日期 / 可见性 ===== -->
        <div class="crumb l-narrow">
          <div class="crumb__left">
            <span v-if="report.game.rule_system" class="c-tag">{{ report.game.rule_system }}</span>
            <RouterLink class="crumb__game" :to="gameHash">
              <span>{{ report.game.title }}</span>
            </RouterLink>
            <span v-if="report.game.finished_at" class="u-small">
              {{ formatDate(report.game.finished_at) }} 结团
            </span>
          </div>
          <div class="crumb__right">
            <span v-if="report.is_featured" class="c-tag c-tag--seal">精选</span>
            <span class="c-tag c-tag--mute">{{ visibilityLabel }}</span>
          </div>
        </div>

        <!-- ===== 文章 ===== -->
        <article class="post__main l-narrow">
          <h1 class="post__title u-h-display">{{ report.title }}</h1>

          <div class="byline">
            <RouterLink class="byline__who" :to="'/users/' + report.author.id">
              <img
                v-if="report.author.avatar"
                class="byline__face"
                :src="report.author.avatar"
                alt=""
              />
              <span v-else class="byline__face byline__face--blank" aria-hidden="true"></span>
              <span>{{ report.author.nickname }}</span>
            </RouterLink>
            <span class="byline__dates">
              发布于 {{ formatDateTime(report.created_at) }}
              <template v-if="report.updated_at !== report.created_at">
                · 最后修改 {{ formatDateTime(report.updated_at) }}
              </template>
            </span>
          </div>

          <hr class="post__rule" />

          <CNotice v-if="actionError" tone="danger">{{ actionError }}</CNotice>
          <CNotice v-else-if="abuseDone" tone="ok">{{ abuseDone }}</CNotice>

          <!-- 正文：全页唯一的 v-html 在 MarkdownView 内部 -->
          <MarkdownView
            v-if="report.body_markdown"
            class="post__body"
            :source="report.body_markdown"
          />
          <p v-else class="u-muted post__body">这篇战报暂时没有正文内容。</p>

          <!-- ===== 附件 ===== -->
          <section v-if="report.attachments.length" class="atts" aria-label="附件">
            <h2 class="atts__head">附件</h2>
            <p class="u-small">
              附件的可见范围与这篇战报相同，登录后才能下载。附件中的图片不会自动显示在正文里。
            </p>
            <ul class="atts__list">
              <li v-for="file in report.attachments" :key="file.id" class="att">
                <span class="att__grow">
                  <span class="att__name">{{ file.original_name }}</span>
                  <span class="att__size">{{ sizeText(file.size) }} · {{ file.mime }}</span>
                </span>
                <a
                  v-if="authenticated === true"
                  class="c-textlink att__act"
                  :href="file.download_url"
                >
                  下载 ↓
                </a>
                <span v-else class="u-small att__act">登录后可下载</span>
              </li>
            </ul>
          </section>

          <!-- ===== 文末动作 ===== -->
          <div class="post__actions">
            <div class="post__acts-l">
              <RouterLink
                v-if="report.can_edit"
                class="c-btn c-btn--ghost"
                :to="'/games/' + report.game.id + '/reports/edit'"
              >
                编辑这篇战报
              </RouterLink>
              <template v-if="report.can_delete">
                <CButton v-if="!confirmDelete" variant="danger" @click="confirmDelete = true">
                  删除
                </CButton>
                <template v-else>
                  <CButton variant="danger" :disabled="deleting" @click="onDelete">
                    {{ deleting ? '删除中…' : '确认删除' }}
                  </CButton>
                  <CButton variant="ghost" @click="confirmDelete = false">暂不删除</CButton>
                </template>
              </template>
              <span v-if="authenticated === false" class="u-small">
                这是一篇经站主精选的公开战报，因此未登录也可以阅读。登录后，你可以阅读本站所有公开的战报。
              </span>
            </div>
            <div class="post__acts-r">
              <span v-if="report.can_edit" class="u-small">
                每人在每个团只能有一篇战报，编辑后保存会替换原来的内容，不会新增一篇。
              </span>
              <CButton
                v-if="authenticated === true"
                variant="text"
                @click="abuseOpen = !abuseOpen"
              >
                举报这篇战报
              </CButton>
            </div>
          </div>

          <form v-if="abuseOpen" class="abuse" novalidate @submit.prevent="onAbuse">
            <CNotice v-if="abuseError" tone="danger">{{ abuseError }}</CNotice>
            <div class="c-field">
              <div class="c-field__head">
                <span class="c-field__no">01</span>
                <label class="c-field__label" for="abuse-reason">举报理由</label>
                <span class="c-field__req">必填</span>
              </div>
              <textarea
                id="abuse-reason"
                v-model="abuseReason"
                class="c-textarea"
                maxlength="1000"
                placeholder="请说明这篇战报哪里有问题，站主会看到你填写的内容。每人对同一篇战报只能举报一次。"
              />
            </div>
            <div class="c-actions">
              <CButton type="submit" :disabled="abuseSending">
                {{ abuseSending ? '提交中…' : '提交举报' }}
              </CButton>
              <CButton variant="ghost" @click="abuseOpen = false">取消</CButton>
            </div>
          </form>

          <div class="post__back">
            <RouterLink class="c-textlink" :to="gameHash">← 返回本团页面</RouterLink>
            <RouterLink class="c-textlink" to="/reports">查看全部战报 →</RouterLink>
          </div>
        </article>

        <!-- ===== 同一个团的其他战报 ===== -->
        <section v-if="siblings.length" class="more l-narrow" aria-label="同一个团的其他战报">
          <SectionHead kicker="From the same table" title="同一个团的其他战报" />
          <div class="more__list">
            <RouterLink
              v-for="item in siblings"
              :key="item.id"
              class="mitem"
              :to="'/reports/' + item.id"
            >
              <BlurStage
                class="mitem__art"
                :file="artFile(item.game.rule_system)"
                :rule="item.game.rule_system"
                size="card"
                tone="dark"
                :inset="9"
                alt=""
              />
              <span class="mitem__body">
                <span class="mitem__title u-h-card">{{ item.title }}</span>
                <span v-if="excerptOf(item)" class="mitem__excerpt">{{ excerptOf(item) }}</span>
                <span class="mitem__meta">
                  <span>{{ item.author.nickname }}</span>
                  <span>{{ formatDate(item.created_at) }}</span>
                  <span v-if="item.visibility === 'same_game'">仅同团可见</span>
                </span>
              </span>
            </RouterLink>
          </div>
        </section>
      </template>
    </LoadState>
  </div>
</template>

<style scoped>
/* ==========================================================================
   顶部「所属团」细带
   ========================================================================== */

.crumb {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2) var(--sp-5);
  padding-bottom: var(--sp-3);
  border-bottom: 1px solid var(--line);
}

.crumb__left {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-3);
  min-width: 0;
}

.crumb__right {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.crumb__game {
  display: inline-flex;
  align-items: center;
  min-height: 44px;
  max-width: 100%;
  font-size: var(--fs-md);
  text-decoration: none;
  /** 业务界面遵循后端权限与隐私约束。 */
  overflow-wrap: anywhere;
}

/** 业务界面遵循后端权限与隐私约束。 */
.crumb__left > .c-tag {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.crumb__game span {
  padding-bottom: 1px;
  border-bottom: 1px solid var(--line-2);
}

.crumb__game:hover span {
  border-bottom-color: var(--ink);
}

/* ==========================================================================
   文章骨架（v2 report.html：800 单栏 / 16px 正文 / 标题细而大）
   ========================================================================== */

.post__main {
  padding-top: var(--sp-7);
}

.post__title {
  margin: 0;
  /** 业务界面遵循后端权限与隐私约束。 */
  overflow-wrap: anywhere;
}

.byline {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-4);
  margin-top: var(--sp-4);
}

.byline__who {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  min-height: 44px;
  font-size: var(--fs-base);
  text-decoration: none;
}

.byline__face {
  width: 26px;
  height: 26px;
  object-fit: cover;
  border-radius: var(--radius-pill);
  background: var(--avatar-bg);
}

.byline__face--blank {
  display: inline-block;
}

.byline__dates {
  font-size: var(--fs-sm);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-muted);
}

.post__rule {
  margin: var(--sp-5) 0 var(--sp-6);
  border: 0;
  border-top: 1px solid var(--line);
}

/** 长文版式（16px / 1.7 / `--read-ink`、h2 上分隔线、引用块只留左竖线、插图满栏） */
.post__body {
  margin-bottom: var(--sp-6);
}

/* ==========================================================================
   附件
   ========================================================================== */

.atts {
  margin-top: var(--sp-7);
  padding-top: var(--sp-5);
  border-top: 1px solid var(--line);
}

.atts__head {
  margin: 0 0 var(--sp-1);
  font-size: var(--fs-lg);
  letter-spacing: var(--ls-caps-sm);
}

.atts__list {
  display: grid;
  gap: var(--sp-2);
  margin: var(--sp-4) 0 0;
  padding: 0;
  list-style: none;
}

.att {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.att__grow {
  flex: 1 1 12em;
  min-width: 0;
}

.att__name {
  display: block;
  font-size: var(--fs-md);
  line-height: var(--lh-card);
  word-break: break-all;
}

.att__size {
  display: block;
  margin-top: 3px;
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-muted);
}

.att__act {
  flex: none;
  min-height: 44px;
  display: inline-flex;
  align-items: center;
}

/* ==========================================================================
   文末动作 / 举报
   ========================================================================== */

.post__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3) var(--sp-5);
  margin-top: var(--sp-6);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--line);
}

.post__acts-l,
.post__acts-r {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3) var(--sp-4);
}

.abuse {
  margin-top: var(--sp-5);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--line);
}

.c-field__req {
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps);
  color: var(--brand-ink);
  padding: 2px 6px;
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
}

.post__back {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2) var(--sp-4);
  margin-top: var(--sp-5);
}

/* ==========================================================================
   同一个团的其他战报
   ========================================================================== */

.more {
  margin-top: var(--sp-8);
  padding-top: var(--sp-6);
  border-top: 1px solid var(--line);
}

.more__list {
  display: grid;
  gap: var(--sp-3);
  margin-top: var(--sp-5);
}

.mitem {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: var(--sp-4);
  align-items: stretch;
  padding: var(--sp-3);
  color: inherit;
  text-decoration: none;
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.mitem:hover {
  border-color: var(--line-2);
}

.mitem__art {
  min-height: 92px;
  border-radius: var(--radius);
}

.mitem__body {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}

.mitem__title {
  font-size: var(--fs-lg);
  line-height: var(--lh-card);
  /** 业务界面遵循后端权限与隐私约束。 */
  overflow-wrap: anywhere;
}

.mitem__excerpt {
  margin-top: var(--sp-2);
  font-size: var(--fs-sm);
  line-height: var(--lh-read);
  color: var(--ink-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.mitem__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px var(--sp-3);
  margin-top: var(--sp-2);
  font-size: var(--fs-xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-muted);
}

@media (min-width: 768px) {
  .post__main {
    padding-top: var(--sp-8);
  }

  .mitem {
    grid-template-columns: 116px minmax(0, 1fr);
    gap: var(--sp-5);
    padding: var(--sp-4);
  }
}
</style>
