<script setup lang="ts">
/**
 * 我的卡 · GM 卡（v2 `me.html` 的 `#sp-gmcard`）。
 * 独立页 `/me/gm-card` 与 `/me#cards-gm` 用的是**同一个组件**。
 *
 * 「喜欢跑的团」和「喜欢开的团」是两件事，所以 GM 卡与玩家卡各写各的、各统计各的。
 * 非 GM 后端回 `no_gm_card`（2026-09-23 从 `not_gm` 拆出来，与 games 放团那句区分开），
 * 这里翻成「先去申请 GM」，不当成错误页。
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'
import CButton from '../CButton.vue'
import CNotice from '../CNotice.vue'
import LoadState from '../LoadState.vue'
import StatGrid from './StatGrid.vue'
import { ApiError } from '../../api/http'
import { errorText } from '../../lib/api-error'
import { fetchMyGMCard, updateMyGMCard, type GMCard } from '../../api/profiles'
import { useSiteStore } from '../../stores/site'

const site = useSiteStore()
const { config } = storeToRefs(site)

const card = ref<GMCard | null>(null)
const loading = ref(true)
const error = ref('')
const notGm = ref(false)
/** 业务界面遵循后端权限与隐私约束。 */
const LONG_TEXT_MAX = 20_000

const styleText = ref('')
const saving = ref(false)
const saved = ref(false)
const formError = ref('')

onMounted(async () => {
  await site.load()
  try {
    const data = await fetchMyGMCard()
    card.value = data
    styleText.value = data.style_text
  } catch (e) {
    if (e instanceof ApiError && e.errors.some((item) => item.code === 'no_gm_card')) notGm.value = true
    else error.value = errorText(e, 'GM 卡暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
})

const showLikes = computed(() => config.value.like_feature_enabled !== false)

function countText(value: number | null): string {
  return value === null ? '未公布' : String(value)
}

const stats = computed(() => {
  const data = card.value
  if (!data) return []
  const out = [
    {
      key: 'hosted',
      kicker: '主持团次数',
      value: String(data.games_hosted),
      note: '你主持并成功结团的团数，已取消的团不计入',
    },
  ]
  if (!showLikes.value) return out
  out.push({
    key: 'received',
    kicker: '被评价次数',
    value: countText(data.reviews_received),
    note:
      data.reviews_received === null
        ? '被评价次数满 ' + config.value.like_level_publish_threshold + ' 次后才会公布（「无评价」也算在内）'
        : '只统计你作为 GM 收到的评价，与玩家卡分开计算',
  })
  out.push({
    key: 'level',
    kicker: 'GM 侧赞级别',
    value: data.level ? data.level_display : '未公布',
    note: data.level
      ? '赞 ' + countText(data.likes) + ' · 倒赞 ' + countText(data.dislikes)
      : '收到的评价数量达到本站规定的条数后，系统会自动公布级别',
  })
  return out
})

async function onSave(): Promise<void> {
  if (saving.value) return
  saving.value = true
  saved.value = false
  formError.value = ''
  try {
    const data = await updateMyGMCard({ style_text: styleText.value })
    card.value = data
    styleText.value = data.style_text
    saved.value = true
  } catch (e) {
    formError.value =
      (e instanceof ApiError ? e.formMessage() : '') || errorText(e, '保存失败，请稍后再试。')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section aria-labelledby="gm-card-head">
    <div class="head">
      <h2 id="gm-card-head" class="u-h-card">GM 卡</h2>
      <span class="u-small">获得 GM 身份后才会出现，统计数据与玩家卡分开计算</span>
    </div>

    <CNotice v-if="notGm" title="你还不是 GM">
      你作为玩家参加的团累计达到 {{ config.gm_auto_promote_threshold }} 次后，系统会自动授予你 GM 身份。如果你想在此之前开团，请到「账户与通知」页面填写申请理由并提交，由站主审批。
      <template #actions>
        <RouterLink class="c-textlink" to="/me#account">去申请 GM →</RouterLink>
      </template>
    </CNotice>

    <LoadState v-else :loading="loading" :error="error">
      <template v-if="card">
        <CNotice v-if="formError" tone="danger">{{ formError }}</CNotice>
        <CNotice v-else-if="saved" tone="ok">已保存。修改后的内容已经显示在你的个人空间上。</CNotice>

        <StatGrid :items="stats" />
        <p v-if="showLikes" class="u-small note">
          GM 侧赞级别由你主持的团结团后，到场玩家在团后评价中给你的结果算出：每位到场玩家给你的结果是「赞」「倒赞」「无评价」之一（评价截止时仍未提交的记为「无评价」），三种结果都计入你的被评价次数；赞级别看赞和倒赞各自占被评价次数的比例，「无评价」多时两者的比例都会降低，赞级别更接近「中性」。五档从高到低分为「好评如潮」「好评居多」「中性」「倒赞居多」「差评如潮」五档，各档的分界由站主设置。它与玩家卡的赞级别分开统计，只显示在你的个人空间上供玩家参考，不影响你报名其他团。为了保护评价人的匿名，新收到的评价要等你之后又参加并结束几个团才会解锁并计入统计；「无评价」除此之外还要等该团的评价截止之后才会计入。
        </p>

        <form class="form" novalidate @submit.prevent="onSave">
          <div class="c-field">
            <div class="c-field__head">
              <label class="c-field__label" for="gm-style">GM 风格与爱好</label>
            </div>
            <textarea
              id="gm-style"
              v-model="styleText"
              class="c-textarea"
              rows="9"
              :maxlength="LONG_TEXT_MAX"
              placeholder="例如：你通常主持哪类剧本、游戏节奏如何、对玩家有什么期待。"
            ></textarea>
            <p class="c-field__hint">
              这一段与玩家卡中的自我介绍分开填写，因为你作为玩家喜欢参加的团，和作为 GM 喜欢主持的团可能不同。想报名你所主持的团的玩家，会先阅读这一段。{{ styleText.length }} / {{ LONG_TEXT_MAX }} 字。
            </p>
          </div>

          <div class="c-actions">
            <CButton type="submit" :disabled="saving">
              {{ saving ? '保存中…' : '保存 GM 卡' }}
            </CButton>
            <RouterLink class="c-textlink" to="/games/new">放一个新团 →</RouterLink>
          </div>
        </form>
      </template>
    </LoadState>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-bottom: var(--sp-4);
}

.head h2 {
  margin: 0;
}

.note {
  margin: var(--sp-3) 0 0;
  line-height: var(--lh-body);
  color: var(--ink-muted);
}

.form {
  max-width: 860px;
  margin-top: var(--sp-6);
}
</style>
