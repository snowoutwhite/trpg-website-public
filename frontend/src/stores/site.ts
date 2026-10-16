/** 站级配置 store：全站只拉一次，失败时用兜底值，保证页面仍能渲染。 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchSiteConfig, type SiteConfig } from '../api/site'

const FALLBACK: SiteConfig = {
  site_name: '跑团招募站',
  announcement: '',
  icp_beian: '',
  like_feature_enabled: true,
  invite_code_required: false,
  gallery_moderation_mode: 'public',
  rule_system_presets: [],
  like_level_publish_threshold: 10,
  review_window_days: 30,
  gallery_upload_window_days: 30,
  gm_auto_promote_threshold: 3,
}

export const useSiteStore = defineStore('site', () => {
  const config = ref<SiteConfig>({ ...FALLBACK })
  const loaded = ref(false)
  let inflight: Promise<void> | null = null

  async function load(): Promise<void> {
    if (loaded.value) return
    if (inflight) return inflight
    inflight = (async () => {
      try {
        config.value = await fetchSiteConfig()
      } catch {
        // 后端不可用时不阻断页面：保留兜底站名，导航与表单照常可用。
        config.value = { ...FALLBACK }
      } finally {
        loaded.value = true
        inflight = null
      }
    })()
    return inflight
  }

  return { config, loaded, load }
})
