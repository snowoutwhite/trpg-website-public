<script setup lang="ts">
/** 业务界面遵循后端权限与隐私约束。 */
import { computed, ref } from 'vue'
import CButton from '../CButton.vue'
import CNotice from '../CNotice.vue'
import EditableChoice from './EditableChoice.vue'
import {
  fetchFeaturedCandidates,
  setPhotoFeatured,
  type AdminFeaturedCandidate,
} from '../../api/homeAdmin'
import { errorText } from '../../lib/api-error'
import { useAuthStore } from '../../stores/auth'
import { useEditStore } from '../../stores/edit'
import { useHomeStore } from '../../stores/home'

const edit = useEditStore()
const home = useHomeStore()
const auth = useAuthStore()

const acting = ref<number | null>(null)
const error = ref('')
const note = ref('')

// ---- 候选池（2026-09-22 后端补的 `home/admin/featured-photos/candidates/`）：全站已公开照片分页挑 ----
const PICK_PAGE_SIZE = 24
const pickOpen = ref(false)
const pickLoading = ref(false)
const pickError = ref('')
const pickPage = ref(1)
const pickCount = ref(0)
const candidates = ref<AdminFeaturedCandidate[]>([])
const pickPages = computed(() => Math.max(1, Math.ceil(pickCount.value / PICK_PAGE_SIZE)))

async function loadCandidates(page = 1): Promise<void> {
  pickLoading.value = true
  pickError.value = ''
  try {
    const data = await fetchFeaturedCandidates({ page, page_size: PICK_PAGE_SIZE })
    candidates.value = data.results
    pickCount.value = data.count
    pickPage.value = page
  } catch (e) {
    pickError.value = errorText(e, '候选照片暂时无法读取，请刷新后重试。')
  } finally {
    pickLoading.value = false
  }
}

function togglePick(): void {
  pickOpen.value = !pickOpen.value
  if (pickOpen.value && !candidates.value.length && !pickLoading.value) void loadCandidates(1)
}

/** 候选池里设 / 取消精选：立刻生效，然后同时刷首页、精选列表与当前候选页。 */
async function onPickToggle(photo: AdminFeaturedCandidate): Promise<void> {
  if (acting.value !== null) return
  acting.value = photo.id
  error.value = ''
  note.value = ''
  const next = !photo.is_featured
  try {
    await setPhotoFeatured(photo.id, next)
    note.value = next ? '已设为精选，首页「活动掠影」会显示这张。' : '已从首页取消这张照片。'
    await Promise.all([
      home.load(auth.authenticated, true),
      edit.loadFeatured(),
      loadCandidates(pickPage.value),
    ])
  } catch (e) {
    error.value = errorText(e, next ? '设为精选失败，请稍后再试。' : '取消精选失败，请稍后再试。')
  } finally {
    acting.value = null
  }
}
/** 缩略图取不到的那些 id（关掉开关时字节出口会 404）。 */
const broken = ref<number[]>([])

const enabled = computed(() => edit.configValue('featured_photos_enabled') === true)
const visibility = computed(() => edit.configValue('featured_photos_visibility') ?? 'members')

const VISIBILITY_OPTIONS = [
  { value: 'public', text: '所有人可见（含游客）' },
  { value: 'members', text: '仅登录成员可见' },
]

function onToggleEnabled(event: Event): void {
  edit.setConfig('featured_photos_enabled', (event.target as HTMLInputElement).checked)
}

async function onUnfeature(id: number): Promise<void> {
  if (acting.value !== null) return
  acting.value = id
  error.value = ''
  note.value = ''
  try {
    await setPhotoFeatured(id, false)
    note.value = '已从首页取消这张照片。'
    await Promise.all([home.load(auth.authenticated, true), edit.loadFeatured()])
  } catch (e) {
    error.value = errorText(e, '取消精选失败，请稍后再试。')
  } finally {
    acting.value = null
  }
}
</script>

<template>
  <section class="fp" aria-label="精选照片（编辑）">
    <h2 class="fp__h">活动掠影（精选照片）</h2>
    <p class="fp__sub">
      开关与可见范围是站级设置，改完要点底部的「保存」；下面的「取消精选」是立刻生效的。
      新增精选可以在下方「从全站照片里挑选」，也可以去团页的相册标签在照片上点「设为精选」。
    </p>

    <CNotice v-if="error" tone="danger">{{ error }}</CNotice>
    <CNotice v-else-if="note" tone="ok">{{ note }}</CNotice>

    <div class="fp__controls">
      <label class="fp__switch">
        <input
          data-edit
          type="checkbox"
          :checked="enabled"
          aria-label="首页显示活动掠影这一段"
          @change="onToggleEnabled"
        />
        <span>首页显示「活动掠影」这一段</span>
      </label>

      <EditableChoice
        :value="visibility"
        label="活动掠影的可见范围"
        :options="VISIBILITY_OPTIONS"
        :error="edit.fieldErrors['config.featured_photos_visibility'] ?? ''"
        @update:value="edit.setConfig('featured_photos_visibility', $event as 'public' | 'members')"
      />
    </div>

    <p v-if="edit.fieldErrors['config.featured_photos_enabled']" class="fp__err">
      {{ edit.fieldErrors['config.featured_photos_enabled'] }}
    </p>

    <h3 class="fp__h3">当前精选（{{ edit.featured.length }} 张）</h3>
    <p v-if="!edit.featured.length" class="fp__empty">
      还没有精选照片。去任意已结团的团页 → 相册，点开一张已公开的照片，选「设为精选」。
    </p>
    <ul v-else class="fp__grid">
      <li v-for="photo in edit.featured" :key="photo.id" class="fp__cell">
        <img
          v-if="!broken.includes(photo.id)"
          class="fp__img"
          :src="photo.thumbnail_url"
          :alt="photo.caption || photo.game_title"
          loading="lazy"
          decoding="async"
          @error="broken = [...broken, photo.id]"
        />
        <span v-else class="fp__img fp__img--gone">图片取不到</span>
        <span class="fp__cap">{{ photo.game_title }}</span>
        <CButton
          class="fp__btn"
          variant="ghost"
          :disabled="acting !== null"
          @click="onUnfeature(photo.id)"
        >
          取消精选
        </CButton>
      </li>
    </ul>
    <p v-if="broken.length" class="fp__sub">
      有缩略图取不到：精选段当前是关闭的时候，照片的字节出口也会一并关掉。先保存「显示这一段」再看。
    </p>

    <!-- ===== 候选池：从全站已公开照片里挑（不进草稿，点了立刻生效） ===== -->
    <div class="fp__pick">
      <CButton
        class="fp__btn"
        variant="ghost"
        :aria-expanded="pickOpen ? 'true' : 'false'"
        aria-controls="fp-candidates"
        @click="togglePick"
      >
        {{ pickOpen ? '收起候选照片' : '从全站照片里挑选' }}
      </CButton>
      <div v-if="pickOpen" id="fp-candidates" class="fp__pickbody">
        <p class="fp__sub">
          这里列的是全站已公开的照片，最新在前；每张点一下就设为或取消精选，立刻生效。
          {{ pickCount ? '共 ' + pickCount + ' 张，第 ' + pickPage + ' / ' + pickPages + ' 页。' : '' }}
        </p>
        <CNotice v-if="pickError" tone="danger">{{ pickError }}</CNotice>
        <p v-else-if="pickLoading && !candidates.length" class="fp__empty">正在读取候选照片…</p>
        <p v-else-if="!candidates.length" class="fp__empty">还没有已公开的照片。</p>
        <ul v-else class="fp__grid">
          <li v-for="photo in candidates" :key="photo.id" class="fp__cell">
            <img
              class="fp__img"
              :class="{ 'fp__img--on': photo.is_featured }"
              :src="photo.thumbnail_url"
              :alt="photo.caption || photo.game_title"
              loading="lazy"
              decoding="async"
            />
            <span class="fp__cap">{{ photo.game_title }}</span>
            <CButton
              class="fp__btn"
              :variant="photo.is_featured ? 'ghost' : 'primary'"
              :disabled="acting !== null"
              :aria-pressed="photo.is_featured ? 'true' : 'false'"
              @click="onPickToggle(photo)"
            >
              {{ photo.is_featured ? '取消精选' : '设为精选' }}
            </CButton>
          </li>
        </ul>
        <div v-if="pickPages > 1" class="fp__pager">
          <CButton
            class="fp__btn"
            variant="ghost"
            :disabled="pickLoading || pickPage <= 1"
            @click="loadCandidates(pickPage - 1)"
          >
            上一页
          </CButton>
          <CButton
            class="fp__btn"
            variant="ghost"
            :disabled="pickLoading || pickPage >= pickPages"
            @click="loadCandidates(pickPage + 1)"
          >
            下一页
          </CButton>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.fp {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-4);
  background: var(--white);
  border: 1px dashed var(--brand-ink);
  border-radius: var(--radius-lg);
}

.fp__h {
  margin: 0;
  font-size: var(--fs-xl);
  line-height: var(--lh-card);
  color: var(--ink);
}

.fp__h3 {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-sm);
  letter-spacing: var(--ls-wide);
  color: var(--ink-soft);
}

.fp__sub,
.fp__empty,
.fp__cap {
  margin: 0;
  font-size: var(--fs-2xs);
  letter-spacing: var(--ls-caps-sm);
  line-height: 1.6;
  color: var(--ink-muted);
}

.fp__err {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--danger);
}

.fp__controls {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--sp-4);
}

.fp__switch {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-height: 44px;
  font-size: var(--fs-xs);
  color: var(--ink-soft);
}

.fp__switch input {
  width: 18px;
  height: 18px;
  accent-color: var(--brand);
}

.fp__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: var(--sp-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.fp__cell {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  min-width: 0;
}

.fp__img {
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
  background: var(--thumb-bg);
  border-radius: var(--radius);
}

.fp__img--gone {
  display: grid;
  place-items: center;
  font-size: var(--fs-2xs);
  color: var(--ink-muted);
}

.fp__cap {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fp__btn {
  min-height: 44px;
}

/* 候选池：折叠区 + 已精选的缩略图描一圈品牌色 */
.fp__pick {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding-top: var(--sp-3);
  border-top: 1px dashed var(--line-2);
}

.fp__pickbody {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.fp__img--on {
  outline: 3px solid var(--brand);
  outline-offset: -3px;
}

.fp__pager {
  display: flex;
  gap: var(--sp-2);
}
</style>
