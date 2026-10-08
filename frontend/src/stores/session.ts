import { defineStore } from 'pinia'
import { ref } from 'vue'
import api, { ApiError, setToken, getToken } from '@/api'

/**
 * 会话与系统配置。
 * 本地开发策略：启动时用演示账号静默登录，失败不阻塞（后端可能开了 AUTH_DISABLED）。
 */
export const useSessionStore = defineStore('session', () => {
  const user = ref<any>(null)
  const config = ref<any>(null)
  const blocks = ref<Record<string, any[]>>({ email: [], form: [], landing: [] })
  const ready = ref(false)
  const authError = ref('')

  async function loadSession() {
    try {
      config.value = await api.config()
      if (getToken()) {
        try {
          user.value = await api.me()
        } catch {
          user.value = null
        }
      }
      if (!user.value && !(config.value?.auth_disabled)) {
        await silentLogin()
      }
      if (user.value) {
        await loadBlocks()
      }
    } catch (e: any) {
      authError.value = e instanceof ApiError ? e.message : String(e)
    } finally {
      ready.value = true
    }
  }

  async function silentLogin() {
    const demos = [
      ['admin@csts.dev', 'admin12345'],
      ['ops@csts.dev', 'ops12345']
    ]
    for (const [email, pwd] of demos) {
      try {
        const r = await api.login(email, pwd)
        setToken(r.access_token)
        user.value = r.user
        return true
      } catch {
        /*试下一个*/
      }
    }
    return false
  }

  async function login(email: string, password: string) {
    const r = await api.login(email, password)
    setToken(r.access_token)
    user.value = r.user
    await loadBlocks()
    return r.user
  }

  function logout() {
    setToken(null)
    user.value = null
  }

  async function loadBlocks() {
    const [e, f, l] = await Promise.all([
      api.blocks('email').catch(() => []),
      api.blocks('form').catch(() => []),
      api.blocks('landing').catch(() => [])
    ])
    blocks.value = { email: e, form: f, landing: l }
  }

  /** 插件启停后需要刷新组件表 */
  async function reloadBlocks() {
    await loadBlocks()
  }

  const llmReady = () => !!(config.value?.llm?.configured)
  const kindLabel = (k: string) =>
    ({ email: 'HTML 邮件', form: '表单', landing: '着陆页 / 活动站点' }[k] || k)

  return {
    user, config, blocks, ready, authError,
    loadSession, login, logout, loadBlocks, reloadBlocks,
    llmReady, kindLabel
  }
})