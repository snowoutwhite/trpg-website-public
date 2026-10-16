<script setup lang="ts">
/**
 * 资源详情：**列表那张卡放大展开**（v2 没画这一页，按 `resources.html` 的卡片版式加宽加长）。
 * 说明不再两行截断，补上分类 / 类型 / 上传者 / 上传与更新时间四格事实。
 *
 * 下载要登录（后端 `ResourceDownloadView` 是 `IsAuthenticatedAndActive`）：
 * 游客看到一句说明 + 登录入口，登录后回到这一页。
 * 外链前后端各过一道协议白名单（`lib/url-guard.ts` 的 `safeExternalUrl`）——
 * 这条链接是点一下就跳的，不能只靠后端那一层。
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import AppIcon from '../components/AppIcon.vue'
import BlurStage from '../components/BlurStage.vue'
import BtnLink from '../components/BtnLink.vue'
import CCard from '../components/CCard.vue'
import CNotice from '../components/CNotice.vue'
import CPill from '../components/CPill.vue'
import LoadState from '../components/LoadState.vue'
import { fetchResource, type ResourceItem } from '../api/resources'
import { errorText } from '../lib/api-error'
import { resourceArt, resourceTypeText } from '../lib/resource-display'
import { safeExternalUrl } from '../lib/url-guard'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const auth = useAuthStore()
const { authenticated } = storeToRefs(auth)

const item = ref<ResourceItem | null>(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    item.value = await fetchResource(String(route.params.id ?? ''))
  } catch (e) {
    error.value = errorText(e, '这条资源暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
})

const loginLink = computed(() => '/auth/login?next=' + encodeURIComponent(route.fullPath))

function formatDateTime(value?: string): string {
  if (!value) return ''
  const at = new Date(value)
  return at.toLocaleDateString('zh-CN') + ' ' + at.toTimeString().slice(0, 5)
}
</script>

<template>
  <div class="l-narrow rd u-rise">
    <RouterLink class="c-back" to="/resources">
      <AppIcon name="back" :size="16" />
      资源
    </RouterLink>

    <LoadState :loading="loading" :error="error">
      <CCard v-if="item" as="article" flush class="rd-card">
        <BlurStage
          class="rd-card__stage"
          :file="resourceArt(item.category)"
          :inset="20"
          alt=""
        >
          <span class="c-tag c-tag--dark rd-card__kind">
            {{ item.kind === 'link' ? '链接' : '文件' }}
          </span>
        </BlurStage>

        <div class="rd-card__body">
          <p class="rd-card__top">
            <span v-if="item.category" class="c-tag">{{ item.category }}</span>
            <span class="u-small">{{ resourceTypeText(item) }}</span>
            <CPill v-if="!item.is_approved" tone="wait">待审核</CPill>
          </p>

          <h1 class="u-h-section rd-card__title">{{ item.title }}</h1>

          <p v-if="item.description" class="rd-card__desc">{{ item.description }}</p>

          <dl class="rd-facts">
            <div class="rd-facts__row">
              <dt class="u-small">分类</dt>
              <dd>{{ item.category || '暂未分类' }}</dd>
            </div>
            <div class="rd-facts__row">
              <dt class="u-small">条目类型</dt>
              <dd>{{ item.kind === 'link' ? '外部链接' : '站内文件' }}</dd>
            </div>
            <div class="rd-facts__row">
              <dt class="u-small">上传者</dt>
              <dd>
                <RouterLink v-if="item.uploader" :to="'/users/' + item.uploader.id">
                  {{ item.uploader.nickname }}
                </RouterLink>
                <span v-else>站主</span>
              </dd>
            </div>
            <div class="rd-facts__row">
              <dt class="u-small">上传时间</dt>
              <dd>{{ formatDateTime(item.created_at) }}</dd>
            </div>
            <div v-if="item.updated_at !== item.created_at" class="rd-facts__row">
              <dt class="u-small">最后更新</dt>
              <dd>{{ formatDateTime(item.updated_at) }}</dd>
            </div>
          </dl>

          <!-- 外链：地址没过 http/https 白名单时 BtnLink 退化成不可点的 span，再补一句说明 -->
          <template v-if="item.kind === 'link'">
            <div class="c-actions">
              <BtnLink :href="safeExternalUrl(item.url)">
                <AppIcon name="link" :size="18" />
                打开链接
              </BtnLink>
            </div>
            <CNotice v-if="!safeExternalUrl(item.url)" tone="warn" title="这条资源的链接无法直接打开">
              这条链接的地址格式不符合本站的安全要求，为了保护你的设备安全，本站没有把它显示为可点击的链接。如有需要，请联系站主确认这条资源。
            </CNotice>
            <p v-else class="u-small rd-note">这是一个外部网站，其内容不由本站负责，请自行判断是否可信。</p>
          </template>

          <!-- 文件：后端下发的鉴权下载路径（同源），游客先登录再回来 -->
          <template v-else>
            <div v-if="authenticated === true && item.download_url" class="c-actions">
              <a class="c-btn" :href="item.download_url">
                <AppIcon name="download" :size="18" />
                下载文件
              </a>
            </div>
            <CNotice v-else-if="authenticated === false" title="登录后才能下载资源文件">
              请先<RouterLink :to="loginLink">登录</RouterLink>
              ，登录后会自动回到本页面。
            </CNotice>
          </template>
        </div>
      </CCard>
    </LoadState>
  </div>
</template>

<style scoped>
.rd-card {
  margin-top: var(--sp-4);
}

.rd-card__stage {
  position: relative;
  height: 180px;
}

/** 前景清晰图按 --fg-inset 内缩：`BlurStage` 只给了 `position:absolute; inset:var(--fg-inset)`， */
.rd-card__stage :deep(.c-blur-stage__fg) {
  width: calc(100% - 2 * var(--fg-inset, 0px));
  height: calc(100% - 2 * var(--fg-inset, 0px));
}

.rd-card__kind {
  position: absolute;
  left: var(--sp-3);
  top: var(--sp-3);
}

.rd-card__body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-5) var(--sp-4);
}

.rd-card__top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2) var(--sp-3);
  margin: 0;
}

.rd-card__title {
  margin: 0;
}

.rd-card__desc {
  margin: 0;
  font-size: var(--fs-base);
  line-height: var(--lh-body);
  color: var(--ink-soft);
  /* 说明是站主手写的多段文字，换行照原样留着 */
  white-space: pre-wrap;
}

.rd-facts {
  display: grid;
  gap: var(--sp-3);
  margin: var(--sp-2) 0 0;
  padding: var(--sp-4) 0 0;
  border-top: 1px solid var(--line);
}

.rd-facts__row dt {
  margin: 0;
}

.rd-facts__row dd {
  margin: var(--sp-1) 0 0;
  font-size: var(--fs-md);
  color: var(--ink);
}

/** 业务界面遵循后端权限与隐私约束。 */
.rd-facts__row dd a {
  display: inline-block;
  min-height: 40px;
  padding: var(--sp-2) 0;
  line-height: 24px;
  color: var(--brand-ink);
}

.rd-note {
  margin: 0;
}

@media (min-width: 768px) {
  .rd-card__stage {
    height: 240px;
  }

  .rd-card__body {
    padding: var(--sp-6) var(--sp-6);
  }

  .rd-facts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--sp-4) var(--sp-5);
  }
}
</style>
