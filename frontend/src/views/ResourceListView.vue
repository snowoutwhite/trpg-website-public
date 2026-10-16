<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import BlurStage from '../components/BlurStage.vue'
import BtnLink from '../components/BtnLink.vue'
import CButton from '../components/CButton.vue'
import CCard from '../components/CCard.vue'
import CChip from '../components/CChip.vue'
import LoadState from '../components/LoadState.vue'
import PageHead from '../components/PageHead.vue'
import {
  fetchResourceCategories,
  fetchResources,
  type ResourceCategory,
  type ResourceItem,
  type ResourceKind,
} from '../api/resources'
import { errorText } from '../lib/api-error'
import { resourceArt, resourceFocal, resourceTypeText } from '../lib/resource-display'
import { safeExternalUrl } from '../lib/url-guard'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const { authenticated, user } = storeToRefs(auth)

const items = ref<ResourceItem[]>([])
const categories = ref<ResourceCategory[]>([])
const count = ref(0)
const totalCount = ref(0)
const page = ref(1)
const hasNext = ref(false)
const loading = ref(true)
const error = ref('')

const category = ref('')
const kind = ref<ResourceKind | ''>('')

const KINDS: { value: ResourceKind | ''; label: string }[] = [
  { value: '', label: '全部类型' },
  { value: 'file', label: '文件' },
  { value: 'link', label: '外链' },
]

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchResources({
      category: category.value,
      kind: kind.value,
      page: page.value,
    })
    items.value = data.results
    count.value = data.count
    hasNext.value = Boolean(data.next)
    if (!category.value && !kind.value) totalCount.value = data.count
  } catch (e) {
    error.value = errorText(e, '资源区暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await load()
  try {
    categories.value = (await fetchResourceCategories()).results
  } catch {
    // 分类清单拿不到就只显示「全部」，列表照常能看 —— 不为一条筛选条挡住整页。
    categories.value = []
  }
})

watch([category, kind], () => {
  page.value = 1
  void load()
})
watch(page, () => void load())

const empty = computed(() => !items.value.length)

const countText = computed(() => {
  const parts = ['共 ' + count.value + ' 条']
  if (category.value) parts.push('分类「' + category.value + '」')
  const picked = KINDS.find((k) => k.value === kind.value)
  if (kind.value && picked) parts.push('只看' + picked.label)
  parts.push('只显示已通过审核的条目')
  return parts.join(' · ')
})

/** 上传入口的门槛。 */
const canUpload = computed(() => user.value?.is_staff === true)

function pickCategory(value: string): void {
  category.value = category.value === value ? '' : value
}

function clearFilters(): void {
  category.value = ''
  kind.value = ''
}

function loginNext(id: number): string {
  return '/auth/login?next=' + encodeURIComponent('/resources/' + id)
}
</script>

<template>
  <div class="res u-rise">
    <PageHead
      eyebrow="Shared materials · 资源"
      title="资源"
      lead="这里收录空白人物卡、开团清单、规则书的正规获取渠道，以及线上线下都能使用的地图与工具。资源列表和说明对所有访客开放，下载文件需要先登录。资源的分类由上传者填写，与规则系统无关，因为同一份材料可能适用于多个规则系统。"
    />

    <div class="res-tools">
      <div class="c-chips" role="group" aria-label="按分类筛选">
        <CChip :active="!category" :count="totalCount" @click="pickCategory('')">全部</CChip>
        <CChip
          v-for="item in categories"
          :key="item.category"
          :active="category === item.category"
          :count="item.count"
          @click="pickCategory(item.category)"
        >
          {{ item.category }}
        </CChip>
      </div>
      <div class="c-chips res-tools__kind" role="group" aria-label="按类型筛选">
        <CChip
          v-for="option in KINDS"
          :key="option.value"
          :active="kind === option.value"
          @click="kind = option.value"
        >
          {{ option.label }}
        </CChip>
      </div>
    </div>

    <p class="u-small res-count">{{ countText }}</p>

    <!-- 有上传权限的人才看得到；上传表单本身还没有页面（见脚本注释） -->
    <div v-if="canUpload" class="res-upload">
      <div class="res-upload__txt">
        <AppIcon class="res-upload__icon" name="plus" :size="18" />
        <div>
          <p class="res-upload__title">你有上传资源的权限</p>
          <p class="u-small res-upload__note">
            上传的资源需要经站主审核，审核通过前只有你和站主能看到。程序文件和脚本文件出于安全原因无法上传。
          </p>
        </div>
      </div>
      <p class="u-small res-upload__todo">网站暂时还没有提供上传资源的页面，目前所有资源由站主统一录入。</p>
    </div>

    <LoadState
      :loading="loading"
      :error="error"
      :empty="empty"
      empty-title="暂时没有符合当前筛选条件的资源"
      empty-text="你可以换一个分类或类型，或者清除筛选条件查看全部资源。"
    >
      <template #empty-actions>
        <CButton variant="ghost" @click="clearFilters">清除筛选</CButton>
      </template>

      <div class="res-grid">
        <CCard
          v-for="(item, index) in items"
          :key="item.id"
          as="article"
          flush
          class="res-card"
        >
          <BlurStage
            class="res-card__thumb"
            :file="resourceArt(item.category)"
            :inset="16"
            :style="{ '--fg-pos': resourceFocal(index) }"
            alt=""
          >
            <span class="c-tag c-tag--dark res-card__kind">
              {{ item.kind === 'link' ? '链接' : '文件' }}
            </span>
          </BlurStage>

          <div class="res-card__body">
            <p class="res-card__top">
              <span v-if="item.category" class="c-tag">{{ item.category }}</span>
              <span class="u-small">{{ resourceTypeText(item) }}</span>
            </p>

            <h3 class="u-h-card res-card__title">
              <RouterLink :to="'/resources/' + item.id">{{ item.title }}</RouterLink>
            </h3>

            <p v-if="item.description" class="res-card__desc">{{ item.description }}</p>

            <p class="res-card__meta">
              <span>{{ new Date(item.created_at).toLocaleDateString('zh-CN') }}</span>
              <span>{{ item.kind === 'link' ? '外部网站，请自行判断是否可信' : '登录后可下载' }}</span>
            </p>

            <div class="res-card__foot">
              <span v-if="item.uploader" class="res-card__who">
                <img
                  v-if="item.uploader.avatar"
                  class="res-card__avatar"
                  :src="item.uploader.avatar"
                  alt=""
                />
                <span v-else class="res-card__avatar res-card__avatar--blank" aria-hidden="true" />
                <bdi>{{ item.uploader.nickname }}</bdi> 上传
              </span>
              <span v-else class="res-card__who">站主上传</span>

              <span class="res-card__act">
                <!-- 外链：BtnLink 内部过 safeExternalUrl()，不过白名单会退化成不可点的 span -->
                <BtnLink
                  v-if="item.kind === 'link'"
                  variant="ghost"
                  :href="safeExternalUrl(item.url)"
                >
                  打开链接 ↗
                </BtnLink>
                <!-- 文件：后端下发的鉴权下载路径（同源），游客先去登录再回这一页 -->
                <a
                  v-else-if="authenticated === true && item.download_url"
                  class="c-btn c-btn--ghost"
                  :href="item.download_url"
                >
                  <AppIcon name="download" :size="16" />
                  下载文件
                </a>
                <BtnLink
                  v-else-if="authenticated === false"
                  variant="ghost"
                  :to="loginNext(item.id)"
                >
                  登录后下载
                </BtnLink>
              </span>
            </div>
          </div>
        </CCard>
      </div>

      <div v-if="hasNext || page > 1" class="res-pager">
        <CButton variant="ghost" :disabled="page <= 1" @click="page -= 1">上一页</CButton>
        <span class="u-small res-pager__at">第 {{ page }} 页 · 共 {{ count }} 条</span>
        <CButton variant="ghost" :disabled="!hasNext" @click="page += 1">下一页</CButton>
      </div>
    </LoadState>

    <p class="u-small res-foot-note">
      没有找到需要的资源？请先查看
      <RouterLink class="u-tap" to="/guide">手册</RouterLink>
      ，也可以在团里向其他成员询问。站主会把经常被问到的材料陆续补充到这里。
    </p>
  </div>
</template>

<style scoped>
/* ===================================================================
   工具条（v2 .res-tools：分类 chip 一行，类型筛选跟在后面）
   =================================================================== */
.res-tools {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.res-count {
  margin: var(--sp-4) 0 0;
}

@media (min-width: 768px) {
  .res-tools {
    flex-direction: row;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--sp-5);
  }

  .res-tools__kind {
    flex: none;
    justify-content: flex-end;
  }
}

/* ===================================================================
   上传入口（v2 .res-upload：虚线框）
   =================================================================== */
.res-upload {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3) var(--sp-5);
  margin-top: var(--sp-5);
  padding: var(--sp-4) var(--sp-5);
  background: var(--white);
  border: 1px dashed var(--line-2);
  border-radius: var(--radius);
}

.res-upload__txt {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  min-width: 0;
}

.res-upload__icon {
  flex: none;
  margin-top: 2px;
  color: var(--brand-ink);
}

.res-upload__title {
  margin: 0;
  font-size: var(--fs-md);
  color: var(--ink);
}

.res-upload__note {
  margin: var(--sp-1) 0 0;
  max-width: 62ch;
}

.res-upload__todo {
  margin: 0;
  max-width: 34ch;
}

/* ===================================================================
   列表（v2 .res-list / .res-card：缩略图 + 正文两栏）
   手机一列 → ≥768 两列 → ≥1921 三列（版心此时固定 1440，两列会把卡拉得过宽）
   =================================================================== */
.res-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--sp-4);
  align-items: start;
  margin-top: var(--sp-5);
}

@media (min-width: 768px) {
  .res-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (min-width: 1921px) {
  .res-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.res-card {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: 148px auto;
}

.res-card__thumb {
  position: relative;
  min-width: 0;
}

/** 前景清晰图按 --fg-inset 内缩：`BlurStage` 只给了 `position:absolute; inset:var(--fg-inset)`， */
/* 同一分类的几张并排时换取景点，免得看起来是同一张（v2 object-position 轮换） */
.res-card__thumb :deep(.c-blur-stage__fg) {
  width: calc(100% - 2 * var(--fg-inset, 0px));
  height: calc(100% - 2 * var(--fg-inset, 0px));
  object-position: var(--fg-pos, center);
}

.res-card__kind {
  position: absolute;
  left: var(--sp-2);
  top: var(--sp-2);
}

.res-card__body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-4);
  min-width: 0;
}

.res-card__top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-3);
  margin: 0;
}

.res-card__title {
  margin: 0;
}

/** 标题链接同时是「整张卡的点击区」：伪元素铺满卡面（整卡可点，手机上好按）， */
.res-card__title a {
  display: block;
  min-height: 40px;
  padding: var(--sp-1) 0;
  color: var(--ink);
  text-decoration: none;
}

.res-card__title a::after {
  content: '';
  position: absolute;
  inset: 0;
}

.res-card__title a:hover {
  color: var(--brand-ink);
}

.res-card__desc {
  margin: 0;
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
  color: var(--ink-muted);
  /* 两行截断（v2 .desc），超出的在详情页看全 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.res-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-4);
  margin: 0;
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps-sm);
  color: var(--ink-faint);
}

.res-card__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2) var(--sp-3);
  margin-top: auto;
  padding-top: var(--sp-3);
}

.res-card__who {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 0;
  font-size: var(--fs-xs);
  color: var(--ink-muted);
}

.res-card__avatar {
  flex: none;
  width: 22px;
  height: 22px;
  border-radius: var(--radius-pill);
  object-fit: cover;
}

.res-card__avatar--blank {
  background: var(--avatar-bg);
}

.res-card__act {
  position: relative;
  z-index: 1;
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

@media (min-width: 768px) {
  .res-card {
    grid-template-columns: 138px minmax(0, 1fr);
    grid-template-rows: auto;
    min-height: 206px;
  }

  .res-card__body {
    padding: var(--sp-4) var(--sp-5);
  }
}

/* ===================================================================
   分页与页脚一句
   =================================================================== */
.res-pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3);
  margin-top: var(--sp-5);
}

.res-pager__at {
  flex: 1 1 auto;
  text-align: center;
}

.res-foot-note {
  margin-top: var(--sp-6);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--line);
}
</style>
