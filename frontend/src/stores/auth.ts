/**
 * 会话 store。
 *
 * 会话状态的唯一真相是后端 Cookie —— 本 store 只缓存查询结果，
 * 不在 localStorage / sessionStorage 里存任何 token 或用户数据。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as authApi from '../api/auth'
import { fetchCurrentUser, type CurrentUser } from '../api/site'

export const useAuthStore = defineStore('auth', () => {
  /** null = 尚未查询过；true/false = 已知结果。 */
  const authenticated = ref<boolean | null>(null)
  const user = ref<CurrentUser | null>(null)
  /** 注册/登录后待完成的邮箱验证流程。 */
  const pendingEmailVerification = ref(false)
  const ready = ref(false)

  let inflight: Promise<void> | null = null

  const isGm = computed(() => user.value?.is_gm === true)
  const displayName = computed(() => user.value?.nickname ?? '')

  function clear(): void {
    authenticated.value = false
    user.value = null
  }

  /** 拉取会话状态；已登录时顺带取本站用户资料。 */
  async function refresh(force = false): Promise<void> {
    if (!force && ready.value) return
    if (inflight) return inflight
    inflight = (async () => {
      try {
        const envelope = await authApi.fetchSession()
        const ok = envelope.status === 200 && Boolean(envelope.data?.user)
        authenticated.value = ok
        pendingEmailVerification.value = authApi.hasPendingFlow(envelope, 'verify_email')
        if (ok) {
          try {
            user.value = await fetchCurrentUser()
          } catch {
            // 本站 me 接口暂不可用时不推翻会话判断，只是拿不到昵称头像。
            user.value = null
          }
        } else {
          user.value = null
        }
      } catch {
        clear()
      } finally {
        ready.value = true
        inflight = null
      }
    })()
    return inflight
  }

  /** 登录成功返回 true；返回 false 表示还有待完成流程（如待验邮箱）。 */
  async function login(email: string, password: string): Promise<boolean> {
    const envelope = await authApi.login(email, password)
    return applyEnvelope(envelope)
  }

  async function signup(payload: authApi.SignupPayload): Promise<boolean> {
    const envelope = await authApi.signup(payload)
    // 409 = 这个浏览器已经登录着（allauth 不抛错、原样返回信封，缺陷 F2）：
    // 不能按信封判成「未登录」，要重新拉一次会话，以真实会话为准。
    if (envelope.status === 409) {
      await refresh(true)
      return authenticated.value === true
    }
    return applyEnvelope(envelope)
  }

  async function verifyEmail(key: string): Promise<boolean> {
    const envelope = await authApi.verifyEmail(key)
    return applyEnvelope(envelope)
  }

  async function resetPassword(key: string, password: string): Promise<boolean> {
    const envelope = await authApi.resetPassword(key, password)
    return applyEnvelope(envelope)
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } finally {
      clear()
      pendingEmailVerification.value = false
      ready.value = true
    }
  }

  async function applyEnvelope(envelope: authApi.SessionEnvelope): Promise<boolean> {
    pendingEmailVerification.value = authApi.hasPendingFlow(envelope, 'verify_email')
    const ok = envelope.status === 200 && Boolean(envelope.data?.user)
    authenticated.value = ok
    ready.value = true
    if (ok) {
      try {
        user.value = await fetchCurrentUser()
      } catch {
        user.value = null
      }
    } else {
      user.value = null
    }
    return ok
  }

  return {
    authenticated,
    user,
    ready,
    isGm,
    displayName,
    pendingEmailVerification,
    refresh,
    login,
    signup,
    verifyEmail,
    resetPassword,
    logout,
  }
})
