<script setup lang="ts">
/** 我的记录 · 举报（v2 `me.html` 的 `#sp-reports`）。 */
import { onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import CNotice from '../CNotice.vue'
import CPill from '../CPill.vue'
import LoadState from '../LoadState.vue'
import PagerBar from '../PagerBar.vue'
import MeRow from './MeRow.vue'
import { fetchMyPhotoReports, type MyPhotoReport } from '../../api/gallery'
import { errorText } from '../../lib/api-error'
import { formatDateTime } from '../../lib/datetime'

const items = ref<MyPhotoReport[]>([])
const count = ref(0)
const page = ref(1)
const hasNext = ref(false)
const loading = ref(true)
const error = ref('')

/** 处理结果 → 胶囊色档；文案一律用后端 `result_display` / `reason_display`。 */
function toneOf(item: MyPhotoReport): 'ok' | 'wait' | 'off' {
  if (item.status !== 'handled') return 'wait'
  return item.result === 'taken_down' ? 'ok' : 'off'
}

function metaOf(item: MyPhotoReport): string[] {
  const meta = ['照片举报', '提交于 ' + formatDateTime(item.created_at)]
  meta.push('理由：' + item.reason_display)
  if (item.handled_at) meta.push('处理于 ' + formatDateTime(item.handled_at))
  return meta
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchMyPhotoReports({ page: page.value })
    items.value = data.results
    count.value = data.count
    hasNext.value = Boolean(data.next)
  } catch (e) {
    error.value = errorText(e, '举报记录暂时无法读取，请刷新后重试。')
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(page, load)
</script>

<template>
  <section aria-labelledby="abuse-head">
    <div class="head">
      <h2 id="abuse-head" class="u-h-card">我的举报</h2>
      <span class="u-small">你对照片提出的下架诉求及其处理进度</span>
    </div>

    <CNotice title="照片中被拍到的人可以申请下架">
      如果团相册里有你不希望公开的照片，请点开那张照片并提交下架诉求。站主处理后，结果会通过站内通知告诉你，同时也会显示在本页。你对战报提交的举报目前不会显示在本页。
    </CNotice>

    <LoadState
      :loading="loading"
      :error="error"
      :empty="!items.length"
      empty-title="你暂时没有提交过举报"
      empty-text="如果你在团相册里看到不应公开的照片，请点开那张照片并提交下架诉求。提交后的记录会显示在此处。"
    >
      <MeRow
        v-for="item in items"
        :key="item.id"
        noimg
        :title="item.reason_text || item.reason_display"
        :meta="metaOf(item)"
        :sub="item.result_note ? '站主说明：' + item.result_note : ''"
      >
        <template #marks>
          <CPill :tone="toneOf(item)">
            {{ item.status === 'handled' ? item.result_display || '已处理' : '待处理' }}
          </CPill>
        </template>
        <template #act>
          <RouterLink class="c-textlink" :to="'/games/' + item.game_id + '#photos'">
            去此团的相册 →
          </RouterLink>
        </template>
      </MeRow>

      <PagerBar :page="page" :count="count" :has-next="hasNext" @go="page = $event" />
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
  margin-bottom: var(--sp-3);
}

.head h2 {
  margin: 0;
}
</style>
