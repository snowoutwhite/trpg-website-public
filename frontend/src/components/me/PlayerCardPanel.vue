<script setup lang="ts">
/** 我的卡 · 玩家卡（v2 `me.html` 的 `#sp-player`）。 */
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import CButton from '../CButton.vue'
import CChip from '../CChip.vue'
import CNotice from '../CNotice.vue'
import LoadState from '../LoadState.vue'
import StatGrid from './StatGrid.vue'
import { ApiError } from '../../api/http'
import { errorText } from '../../lib/api-error'
import { fetchMyPlayerCard, updateMyPlayerCard, type PlayerCard } from '../../api/profiles'
import { useSiteStore } from '../../stores/site'

const site = useSiteStore()
const { config } = storeToRefs(site)

const card = ref<PlayerCard | null>(null)
const loading = ref(true)
const error = ref('')
const saving = ref(false)
const saved = ref(false)
const formError = ref('')

/** 业务界面遵循后端权限与隐私约束。 */
const LONG_TEXT_MAX = 20_000

const taboos = ref('')
const freeText = ref('')
const rules = ref<string[]>([])
const customRule = ref('')

function apply(data: PlayerCard): void {
  card.value = data
  taboos.value = data.taboos
  freeText.value = data.free_text
  rules.value = [...data.preferred_rule_systems]
}

onMounted(async () => {
  await site.load()
  try {
    apply(await fetchMyPlayerCard())
  } catch (e) {
    error.value = errorText(e, '玩家卡暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
})

const presets = computed(() => config.value.rule_system_presets ?? [])
/** 自己加的规则（不在站级预设里的），单独一行显示，可以删。 */
const extraRules = computed(() => rules.value.filter((name) => !presets.value.includes(name)))
const showLikes = computed(() => config.value.like_feature_enabled !== false)

function toggleRule(name: string): void {
  const index = rules.value.indexOf(name)
  if (index >= 0) rules.value.splice(index, 1)
  else rules.value.push(name)
}

function addCustomRule(): void {
  const name = customRule.value.trim()
  if (!name) return
  if (!rules.value.includes(name)) rules.value.push(name)
  customRule.value = ''
}

/** 未公布时后端给 null，这里统一翻成「未公布」。 */
function countText(value: number | null): string {
  return value === null ? '未公布' : String(value)
}

/** 一格统计（与 `StatGrid` 的 props 同形）。 */
interface StatItem {
  key: string
  kicker: string
  value: string
  note?: string
}

const stats = computed<StatItem[]>(() => {
  const data = card.value
  if (!data) return []
  const out: StatItem[] = [
    {
      key: 'played',
      kicker: '团次数',
      value: String(data.games_played),
      note: '你作为玩家参加并成功结团的团数',
    },
  ]
  if (!showLikes.value) return out
  out.push({
    key: 'received',
    kicker: '被评价次数',
    value: countText(data.reviews_received),
    note:
      data.reviews_received === null
        ? '被评价次数满 ' + config.value.like_level_publish_threshold + ' 次后才会公布（「无评价」也算在内）；未满时，次数本身也不显示'
        : '已经解锁并计入统计的评价条数',
  })
  out.push({
    key: 'level',
    kicker: '赞级别',
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
    apply(
      await updateMyPlayerCard({
        taboos: taboos.value,
        free_text: freeText.value,
        preferred_rule_systems: rules.value,
      }),
    )
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
  <section aria-labelledby="player-card-head">
    <div class="head">
      <h2 id="player-card-head" class="u-h-card">玩家卡</h2>
      <span class="u-small">每个账号注册后都有一张玩家卡，其中公开的内容会显示在你的个人空间</span>
    </div>

    <LoadState :loading="loading" :error="error">
      <template v-if="card">
        <CNotice v-if="formError" tone="danger">{{ formError }}</CNotice>
        <CNotice v-else-if="saved" tone="ok">已保存。修改后的内容已经显示在你的个人空间上。</CNotice>

        <form novalidate @submit.prevent="onSave">
          <div class="c-field">
            <div class="c-field__head">
              <label class="c-field__label" for="pc-taboos">雷点</label>
            </div>
            <textarea
              id="pc-taboos"
              v-model="taboos"
              class="c-textarea"
              rows="4"
              :maxlength="LONG_TEXT_MAX"
              placeholder="写明你不接受的题材或行为。"
            ></textarea>
            <p class="c-field__hint">
              请用文字自由填写，不需要从选项中选择。GM 审批报名时，会看到每位报名者填写的雷点。{{ taboos.length }} / {{ LONG_TEXT_MAX }} 字。
            </p>
          </div>

          <div class="c-field">
            <div class="c-field__head">
              <span class="c-field__label" id="pc-rules-label">偏好规则</span>
            </div>
            <div class="c-chips" role="group" aria-labelledby="pc-rules-label">
              <CChip
                v-for="name in presets"
                :key="name"
                :active="rules.includes(name)"
                @click="toggleRule(name)"
              >
                {{ name }}
              </CChip>
              <CChip v-for="name in extraRules" :key="'x-' + name" active @click="toggleRule(name)">
                {{ name }} ×
              </CChip>
            </div>
            <p class="c-field__hint">可以从本站提供的规则中选择多个，也可以在下方填写不在列表中的规则名称。再次点击已选中的规则即可取消选择。</p>
          </div>

          <div class="c-field">
            <div class="c-field__head">
              <label class="c-field__label" for="pc-custom">自定义规则（可留空）</label>
            </div>
            <div class="add">
              <input
                id="pc-custom"
                v-model="customRule"
                class="c-input"
                type="text"
                maxlength="40"
                placeholder="例如：剑之世界 2.5"
                @keydown.enter.prevent="addCustomRule"
              />
              <CButton variant="ghost" @click="addCustomRule">添加</CButton>
            </div>
          </div>

          <div class="c-field">
            <div class="c-field__head">
              <label class="c-field__label" for="pc-free">关于我（一段自由文本）</label>
            </div>
            <textarea
              id="pc-free"
              v-model="freeText"
              class="c-textarea"
              rows="9"
              :maxlength="LONG_TEXT_MAX"
              placeholder="例如：自我介绍、个人风格、跑团经验，以及接下来想参加什么样的团。"
            ></textarea>
            <p class="c-field__hint">
              这一栏是一整段文字，不分小节。如果需要分段，请直接换行，换行会原样显示在你的个人空间。{{ freeText.length }} / {{ LONG_TEXT_MAX }} 字。
            </p>
          </div>

          <div class="c-actions">
            <CButton type="submit" :disabled="saving">
              {{ saving ? '保存中…' : '保存玩家卡' }}
            </CButton>
            <span class="u-small">保存后，修改内容会立即显示在你的个人空间</span>
          </div>
        </form>

        <div class="stats-block">
          <div class="head">
            <h3 class="u-h-card">统计（只读）</h3>
            <span class="u-small">以下数据由系统自动统计，无法手动修改</span>
          </div>
          <StatGrid :items="stats" />
          <p v-if="showLikes" class="u-small note">
            赞级别由同团成员在团后评价中给你的结果算出。你作为玩家参加的每个团结束后，每位同团成员给你的结果是「赞」「倒赞」「无评价」之一（评价截止时仍未提交的记为「无评价」），三种结果都计入你的被评价次数。赞级别看赞和倒赞各自占被评价次数的比例：赞占得越多越接近「好评如潮」，倒赞占得越多越接近「差评如潮」；「无评价」多时，赞和倒赞所占的比例都会降低，赞级别更接近「中性」。五档从高到低为「好评如潮」「好评居多」「中性」「倒赞居多」「差评如潮」，各档的分界由站主设置。你作为 GM 收到的评价只计入 GM 卡，不影响这里的数字。部分 GM 放团时会要求报名者的赞级别不低于某一档；你的赞级别未达到要求或尚未公布时，将无法报名这类团。
            被评价次数和赞级别只统计已经解锁的评价。为了保护评价人的匿名，新收到的评价要等你之后又参加并结束几个团才会解锁；「无评价」除此之外还要等该团的评价截止之后才会计入。因此这里的数字可能比你实际收到的评价少，变化也会比评价本身晚一些出现。
          </p>
          <p v-else class="u-small note">站主目前关闭了赞功能，因此赞级别和被评价次数暂时不显示。</p>
        </div>
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

.head h2,
.head h3 {
  margin: 0;
}

form {
  max-width: 860px;
}

.add {
  display: flex;
  gap: var(--sp-2);
}

.add .c-input {
  flex: 1 1 auto;
}

/* 「加进去」不许折成两行（1440 实测踩到） */
.add :deep(.c-btn) {
  flex: none;
  white-space: nowrap;
}

.stats-block {
  margin-top: var(--sp-7);
  padding-top: var(--sp-5);
  border-top: 1px solid var(--line);
}

.note {
  margin: var(--sp-3) 0 0;
  line-height: var(--lh-body);
  color: var(--ink-muted);
}
</style>
