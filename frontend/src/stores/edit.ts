/** 业务界面遵循后端权限与隐私约束。 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  fetchAdminFeaturedPhotos,
  fetchAdminHome,
  patchHomeConfig,
  patchQuickEntry,
  patchRulePreset,
  uploadQuickEntryImage,
  uploadRulePresetImage,
  type AdminAnnouncement,
  type AdminFeaturedPhoto,
  type AdminHomeData,
  type HomeConfigWrite,
  type PresetPatch,
  type QuickPatch,
} from '../api/homeAdmin'
import { errorStatus, errorText, fieldText } from '../lib/api-error'
import { useAuthStore } from './auth'
import { useHomeStore } from './home'

/** 草稿：只存**动过**的键，没动过的键一律回落后端真值。 */
interface Draft {
  config: Partial<HomeConfigWrite>
  presets: Record<number, Partial<PresetPatch>>
  quick: Record<number, Partial<QuickPatch>>
}

function emptyDraft(): Draft {
  return { config: {}, presets: {}, quick: {} }
}

/** 字段级错误的键：`config.site_name` / `preset.1.title` / `quick.2.body`。 */
export function configKey(field: keyof HomeConfigWrite): string {
  return 'config.' + field
}
export function presetKey(id: number, field: keyof PresetPatch): string {
  return 'preset.' + id + '.' + field
}
export function quickKey(id: number, field: keyof QuickPatch): string {
  return 'quick.' + id + '.' + field
}

export const useEditStore = defineStore('edit', () => {
  /** 编辑态开关。非 staff 永远是 false。 */
  const active = ref(false)
  /** 后端真值（`GET /home/admin/`），也是草稿的对照基准。 */
  const data = ref<AdminHomeData | null>(null)
  const draft = ref<Draft>(emptyDraft())
  const loading = ref(false)
  /** 进入编辑态时拉不到 admin 数据（含 403）时的一句话。 */
  const loadError = ref('')
  const saving = ref(false)
  /** 保存条上的整体错误。 */
  const error = ref('')
  /** 字段级错误，键见 `configKey` / `presetKey` / `quickKey`。 */
  const fieldErrors = ref<Record<string, string>>({})
  /** 保存成功后的一句话，下一次改动即清。 */
  const saved = ref('')

  /** 正在上传的图片键（`preset-1` / `quick-3`），同时只允许一张在飞。 */
  const uploading = ref('')
  /**
   * 正在被聚焦的那一格（原地编辑 2026-09-23）：`EditableText` 聚焦时登记、失焦时清空，
   * 底部保存条据此显示「正在改：格子名 · 字数」。信息放在保存条而不是浮在字旁边，
   * 是因为浮动角标怎么放都会压到相邻的一行（视觉评审两轮都命中）。
   */
  const focusField = ref<{ label: string; length: number; max: number } | null>(null)
  /** 图片相关的错误，键同上。 */
  const imageErrors = ref<Record<string, string>>({})

  /** 精选照片列表（站主视角，后端同样截断到 12 张）。 */
  const featured = ref<AdminFeaturedPhoto[]>([])

  /** 「退出编辑态」的二次确认（有未保存改动时）。 */
  const exitAsk = ref(false)
  /** 被守卫拦下的目标路径；非空时保存条上问一次「确认离开」。 */
  const pendingLeave = ref('')
  /** 保存时撞到 401/403（会话过期 / 被撤掉 staff）：草稿留在本页，保存条给「去登录」出口， */
  const authLost = ref(false)
  /** 「放弃」的二次确认。 */
  const discardAsk = ref(false)

  const announcements = computed<AdminAnnouncement[]>(() => data.value?.announcements ?? [])

  // ------------------------------------------------------------------
  // 原始值：把读序列化器的形状摊平成可写字段
  // ------------------------------------------------------------------

  /** 规则预设的写字段原始值。读序列化器把三段介绍嵌成 `intro:{hero,body,fit}`，这里摊平。 */
  function presetOriginal(id: number): PresetPatch | null {
    const row = data.value?.rule_presets.find((p) => p.id === id)
    if (!row) return null
    return {
      name: row.name,
      kicker: row.kicker,
      title: row.title,
      tagline: row.tagline,
      intro_hero: row.intro.hero,
      intro_body: row.intro.body,
      intro_fit: row.intro.fit,
      official_url: row.official_url,
      image_alt: row.image_alt,
      tone: row.tone,
      sort: row.sort,
    }
  }

  function quickOriginal(id: number): QuickPatch | null {
    const row = data.value?.quick_entries.find((q) => q.id === id)
    if (!row) return null
    return {
      key: row.key,
      label: row.label,
      description: row.description,
      icon: row.icon,
      kicker: row.kicker,
      title: row.title,
      body: row.body,
      button_text: row.button_text,
      route: row.route,
      image_alt: row.image_alt,
      sort: row.sort,
    }
  }

  // ------------------------------------------------------------------
  // 取值 / 设值（组件只经这三对函数碰草稿）
  // ------------------------------------------------------------------

  function configValue<K extends keyof HomeConfigWrite>(field: K): HomeConfigWrite[K] | undefined {
    const own = draft.value.config[field]
    if (own !== undefined) return own as HomeConfigWrite[K]
    return data.value?.config[field]
  }

  function setConfig<K extends keyof HomeConfigWrite>(field: K, value: HomeConfigWrite[K]): void {
    draft.value.config[field] = value
    touch(configKey(field))
  }

  function presetValue<K extends keyof PresetPatch>(id: number, field: K): PresetPatch[K] | undefined {
    const own = draft.value.presets[id]?.[field]
    if (own !== undefined) return own as PresetPatch[K]
    return presetOriginal(id)?.[field]
  }

  function setPreset<K extends keyof PresetPatch>(id: number, field: K, value: PresetPatch[K]): void {
    const bag = draft.value.presets[id] ?? (draft.value.presets[id] = {})
    bag[field] = value
    touch(presetKey(id, field))
  }

  function quickValue<K extends keyof QuickPatch>(id: number, field: K): QuickPatch[K] | undefined {
    const own = draft.value.quick[id]?.[field]
    if (own !== undefined) return own as QuickPatch[K]
    return quickOriginal(id)?.[field]
  }

  function setQuick<K extends keyof QuickPatch>(id: number, field: K, value: QuickPatch[K]): void {
    const bag = draft.value.quick[id] ?? (draft.value.quick[id] = {})
    bag[field] = value
    touch(quickKey(id, field))
  }

  /** 动了某一格：清掉它上一次的字段错误与「已保存」提示。 */
  function touch(key: string): void {
    saved.value = ''
    if (fieldErrors.value[key]) {
      const next = { ...fieldErrors.value }
      delete next[key]
      fieldErrors.value = next
    }
  }

  // ------------------------------------------------------------------
  // 改动计数
  // ------------------------------------------------------------------

  /** 一个键在草稿里且与原始值不同，才算一处改动（改回原样等于没改）。 */
  function dirtyOf<T extends object>(bag: Partial<T> | undefined, origin: T | null): (keyof T)[] {
    if (!bag || !origin) return []
    return (Object.keys(bag) as (keyof T)[]).filter((k) => bag[k] !== origin[k])
  }

  const dirtyConfig = computed<(keyof HomeConfigWrite)[]>(() =>
    data.value ? dirtyOf(draft.value.config, data.value.config) : [],
  )

  const dirtyPresets = computed<{ id: number; fields: (keyof PresetPatch)[] }[]>(() =>
    Object.keys(draft.value.presets)
      .map((raw) => {
        const id = Number(raw)
        return { id, fields: dirtyOf(draft.value.presets[id], presetOriginal(id)) }
      })
      .filter((row) => row.fields.length > 0),
  )

  const dirtyQuick = computed<{ id: number; fields: (keyof QuickPatch)[] }[]>(() =>
    Object.keys(draft.value.quick)
      .map((raw) => {
        const id = Number(raw)
        return { id, fields: dirtyOf(draft.value.quick[id], quickOriginal(id)) }
      })
      .filter((row) => row.fields.length > 0),
  )

  const dirtyCount = computed(
    () =>
      dirtyConfig.value.length +
      dirtyPresets.value.reduce((n, row) => n + row.fields.length, 0) +
      dirtyQuick.value.reduce((n, row) => n + row.fields.length, 0),
  )

  const dirty = computed(() => dirtyCount.value > 0)

  // ------------------------------------------------------------------
  // 进 / 出
  // ------------------------------------------------------------------

  /** 拉一次 admin 全量视图（原始值 + 公告列表），顺带拉精选列表。 */
  async function reload(): Promise<void> {
    loading.value = true
    loadError.value = ''
    try {
      data.value = await fetchAdminHome()
    } catch (e) {
      data.value = null
      loadError.value = errorText(e, '站点内容暂时无法读取，请刷新后重试。')
    } finally {
      loading.value = false
    }
    await loadFeatured()
  }

  async function loadFeatured(): Promise<void> {
    try {
      featured.value = await fetchAdminFeaturedPhotos()
    } catch {
      // 精选列表拿不到不该拦住整个编辑态；面板自己显示空列表。
      featured.value = []
    }
  }

  /** 进入编辑态。**非站主直接返回**（`is_staff !== true` 一律不给）。 */
  async function enter(): Promise<void> {
    const auth = useAuthStore()
    if (auth.user?.is_staff !== true) return
    if (active.value) return
    active.value = true
    resetFlags()
    draft.value = emptyDraft()
    await reload()
  }

  function resetFlags(): void {
    error.value = ''
    fieldErrors.value = {}
    saved.value = ''
    exitAsk.value = false
    pendingLeave.value = ''
    discardAsk.value = false
    imageErrors.value = {}
    authLost.value = false
  }

  /** 退出编辑态。有未保存改动时不直接退，改为要一次确认；返回是否真的退了。 */
  function exit(): boolean {
    if (dirty.value) {
      exitAsk.value = true
      return false
    }
    leave()
    return true
  }

  /** 丢掉草稿并退出（二次确认之后才调）。 */
  function leave(): void {
    active.value = false
    draft.value = emptyDraft()
    data.value = null
    featured.value = []
    resetFlags()
  }

  /** 「放弃」：只清草稿，留在编辑态。 */
  function discard(): void {
    draft.value = emptyDraft()
    resetFlags()
  }

  // ------------------------------------------------------------------
  // 保存
  // ------------------------------------------------------------------

  /**
   * 对比草稿与原始值，只 PATCH 变了的对象。
   *
   * 顺序：config → 各预设 → 各快速选择。全部成功 → 清草稿 + 强刷 `stores/home.ts`；
   * 任一失败 → **已成功的那部分不回滚**，失败的键留在草稿里，错误落到对应的格子旁。
   */
  async function save(): Promise<void> {
    if (saving.value || !dirty.value || !data.value) return
    saving.value = true
    error.value = ''
    fieldErrors.value = {}
    saved.value = ''
    authLost.value = false

    const failures: string[] = []
    const errors: Record<string, string> = {}
    /** 401/403 一律记下：后面的请求还会照样失败，但草稿要留住、保存条要给「去登录」。 */
    function noteAuth(e: unknown): void {
      const status = errorStatus(e)
      if (status === 401 || status === 403) authLost.value = true
    }

    // ---- config ----
    const configFields = dirtyConfig.value
    if (configFields.length) {
      const patch: Partial<HomeConfigWrite> = {}
      let blankSiteName = false
      for (const field of configFields) {
        const value = draft.value.config[field]
        // 站名不许是空串（后端没有 allow_blank）：不发必 400 的请求，但要**当作一次失败**
        if (field === 'site_name' && typeof value === 'string' && value.trim() === '') {
          blankSiteName = true
          continue
        }
        Object.assign(patch, { [field]: value })
      }
      if (blankSiteName) {
        failures.push('站级文案')
        errors['config.site_name'] = '站名不能为空，请填写。'
      }
      if (Object.keys(patch).length) {
        try {
          await patchHomeConfig(patch)
          for (const field of Object.keys(patch) as (keyof HomeConfigWrite)[]) {
            delete draft.value.config[field]
          }
        } catch (e) {
          noteAuth(e)
          if (!blankSiteName) failures.push('站级文案')
          for (const [field, message] of Object.entries(fieldText(e))) {
            errors['config.' + field] = message
          }
          if (!Object.keys(fieldText(e)).length) {
            errors['config.__form__'] = errorText(e, '保存失败，请稍后再试。')
          }
        }
      }
    }

    // ---- 规则预设 ----
    for (const row of [...dirtyPresets.value]) {
      const patch: Partial<PresetPatch> = {}
      for (const field of row.fields) Object.assign(patch, { [field]: draft.value.presets[row.id]?.[field] })
      try {
        await patchRulePreset(row.id, patch)
        delete draft.value.presets[row.id]
      } catch (e) {
        noteAuth(e)
        failures.push('规则「' + (presetOriginal(row.id)?.name ?? row.id) + '」')
        for (const [field, message] of Object.entries(fieldText(e))) {
          errors['preset.' + row.id + '.' + field] = message
        }
        if (!Object.keys(fieldText(e)).length) {
          errors['preset.' + row.id + '.__form__'] = errorText(e, '保存失败，请稍后再试。')
        }
      }
    }

    // ---- 快速选择 ----
    for (const row of [...dirtyQuick.value]) {
      const patch: Partial<QuickPatch> = {}
      for (const field of row.fields) Object.assign(patch, { [field]: draft.value.quick[row.id]?.[field] })
      try {
        await patchQuickEntry(row.id, patch)
        delete draft.value.quick[row.id]
      } catch (e) {
        noteAuth(e)
        failures.push('入口「' + (quickOriginal(row.id)?.label ?? row.id) + '」')
        for (const [field, message] of Object.entries(fieldText(e))) {
          errors['quick.' + row.id + '.' + field] = message
        }
        if (!Object.keys(fieldText(e)).length) {
          errors['quick.' + row.id + '.__form__'] = errorText(e, '保存失败，请稍后再试。')
        }
      }
    }

    fieldErrors.value = errors
    if (authLost.value) {
      error.value =
        '登录状态已失效，这次没有保存。改动已保留在本页：请在新标签页重新登录后回到这里再点「保存」。'
    } else if (failures.length) {
      error.value = '有 ' + failures.length + ' 处没有保存成功（' + failures.join('、') + '），已保留你的改动，请修正后再保存。'
    } else {
      saved.value = '已保存。'
    }

    // 成功的部分必须落到页面上：强刷公开读 + 重新取一次原始值
    const auth = useAuthStore()
    const home = useHomeStore()
    await home.load(auth.authenticated, true)
    try {
      data.value = await fetchAdminHome()
    } catch {
      // 原始值刷不回来不影响已保存的结果；草稿里剩下的键仍以上一份原始值为基准。
    }
    saving.value = false
  }

  // ------------------------------------------------------------------
  // 图片（不进草稿：选好即上传）
  // ------------------------------------------------------------------

  /** 上传一张图并立刻强刷公开读。`kind` 决定打哪个接口。 */
  async function uploadImage(kind: 'preset' | 'quick', id: number, file: File): Promise<boolean> {
    const key = kind + '-' + id
    if (uploading.value) return false
    uploading.value = key
    const next = { ...imageErrors.value }
    delete next[key]
    imageErrors.value = next
    try {
      if (kind === 'preset') await uploadRulePresetImage(id, file)
      else await uploadQuickEntryImage(id, file)
      const auth = useAuthStore()
      const home = useHomeStore()
      await home.load(auth.authenticated, true)
      try {
        data.value = await fetchAdminHome()
      } catch {
        // 同上：原始值刷不回来不影响图已经换上去了
      }
      return true
    } catch (e) {
      imageErrors.value = {
        ...imageErrors.value,
        [key]: errorText(e, '图片上传失败，请稍后再试。'),
      }
      return false
    } finally {
      uploading.value = ''
    }
  }

  return {
    active,
    data,
    loading,
    loadError,
    saving,
    error,
    fieldErrors,
    saved,
    uploading,
    focusField,
    imageErrors,
    featured,
    announcements,
    exitAsk,
    pendingLeave,
    authLost,
    discardAsk,
    dirty,
    dirtyCount,
    configValue,
    setConfig,
    presetValue,
    setPreset,
    quickValue,
    setQuick,
    enter,
    exit,
    leave,
    discard,
    reload,
    loadFeatured,
    save,
    uploadImage,
  }
})
