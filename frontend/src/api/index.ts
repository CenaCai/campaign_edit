/**
 * API 客户端：统一鉴权、错误处理、类型。
 * 用 fetch 而非 axios —— 少一个依赖，且错误语义要自己控制得更清楚。
 */
import type {
  BlockSpec, CommentItem, ContentItem, ContentSchema, ContentVersionItem,
  IntentResult, LintResult, PluginItem, PreviewPayload, ReviewTaskItem,
  TemplateItem, ThemeItem, TokenItem, DiffChange
} from '@/types'

const BASE = '/api/v1'

export class ApiError extends Error {
  status: number
  detail: any
  constructor(status: number, message: string, detail?: any) {
    super(message)
    this.status = status
    this.detail = detail
  }
  /** lint 阻断等场景：detail.lint 带完整结果 */
  get lint(): LintResult | null {
    return this.detail?.lint ?? this.detail?.detail?.lint ?? null
  }
}

let token: string | null = localStorage.getItem('ce_token')
export function setToken(t: string | null) {
  token = t
  if (t) localStorage.setItem('ce_token', t)
  else localStorage.removeItem('ce_token')
}
export function getToken() {
  return token
}

async function request<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> | undefined)
  }
  if (token) headers.Authorization = `Bearer ${token}`

  let resp: Response
  try {
    resp = await fetch(`${BASE}${path}`, { ...init, headers })
  } catch (e) {
    throw new ApiError(0, '无法连接后端服务，请确认 API 已启动（默认 127.0.0.1:8000）')
  }

  if (resp.status === 204) return undefined as T
  const text = await resp.text()
  let data: any = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }

  if (!resp.ok) {
    const detail = data?.detail
    let msg = `请求失败（HTTP ${resp.status}）`
    if (typeof detail === 'string') msg = detail
    else if (detail?.message) msg = detail.message
    else if (Array.isArray(detail) && detail[0]?.msg) msg = detail[0].msg
    throw new ApiError(resp.status, msg, detail)
  }
  return data as T
}

const get = <T = any>(p: string) => request<T>(p)
const post = <T = any>(p: string, body?: any) =>
  request<T>(p, { method: 'POST', body: body ? JSON.stringify(body) : undefined })
const patch = <T = any>(p: string, body?: any) =>
  request<T>(p, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined })
const del = <T = any>(p: string) => request<T>(p, { method: 'DELETE' })

export const api = {
  // ---------- system ----------
  health: () => get('/health'),
  config: () => get<any>('/config'),
  tokens: () => get<{ tokens: Record<string, TokenItem> }>('/tokens'),
  statusMap: () => get<{ labels: Record<string, string>; transitions: Record<string, string[]> }>('/status-map'),
  deepHealth: () => get<any>('/health/deep'),

  // ---------- auth ----------
  login: (email: string, password: string) =>
    post<{ access_token: string; user: any }>('/auth/login', { email, password }),
  me: () => get<any>('/auth/me'),

  // ---------- blocks ----------
  blocks: (kind?: string) => get<BlockSpec[]>(`/blocks${kind ? `?kind=${kind}` : ''}`),
  blockCategories: (kind: string) => get<any[]>(`/blocks/categories?kind=${kind}`),
  blockPreview: (type: string, props: any, style: any = {}) =>
    post<{ html: string }>('/blocks/preview', { type, props, style }),

  // ---------- intent ----------
  recognize: (text: string, opts: { use_llm?: boolean; auto_create?: boolean; project_id?: string } = {}) =>
    post<IntentResult>('/intents', { text, use_llm: opts.use_llm ?? true, auto_create: opts.auto_create ?? false, project_id: opts.project_id }),
  intentHistory: (limit = 30) => get<{ items: any[] }>(`/intents/history?limit=${limit}`),
  lexicon: () => get<any>('/intents/lexicon'),

  // ---------- contents ----------
  contents: (params: Record<string, any> = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.append(k, String(v))
    })
    return get<ContentItem[]>(`/contents${qs.toString() ? `?${qs}` : ''}`)
  },
  content: (id: string) => get<ContentItem>(`/contents/${id}`),
  contentStats: () => get<any>('/contents/stats'),
  createContent: (body: any) => post<ContentItem>('/contents', body),
  contentSchema: (id: string, version?: number) =>
    get<{ schema: ContentSchema; version: number; lint: LintResult }>(
      `/contents/${id}/schema${version ? `?version=${version}` : ''}`
    ),
  contentPreview: (id: string, version?: number) =>
    get<PreviewPayload>(`/contents/${id}/preview${version ? `?version=${version}` : ''}`),
  contentStructure: (id: string, version?: number) =>
    get<PreviewPayload['info']>(`/contents/${id}/structure${version ? `?version=${version}` : ''}`),
  updateContent: (id: string, body: any) => patch<ContentItem>(`/contents/${id}`, body),
  saveContent: (id: string, body: any) => post<ContentItem>(`/contents/${id}/save`, body),
  deleteContent: (id: string) => del(`/contents/${id}`),
  duplicateContent: (id: string, name?: string) => post<ContentItem>(`/contents/${id}/duplicate`, name ? { name } : {}),

  // ---------- versions ----------
  versions: (id: string) => get<ContentVersionItem[]>(`/contents/${id}/versions`),
  versionDetail: (id: string, v: number) =>
    get<any>(`/contents/${id}/versions/${v}`),
  restoreVersion: (id: string, v: number, message = '') =>
    post<ContentItem>(`/contents/${id}/versions/${v}/restore${message ? `?message=${encodeURIComponent(message)}` : ''}`),
  diffVersions: (id: string, from: number, to: number) =>
    get<{ changes: DiffChange[]; summary: Record<string, number> }>(
      `/contents/${id}/diff?from_version=${from}&to_version=${to}`
    ),

  // ---------- collaboration ----------
  lock: (id: string, action: 'acquire' | 'release' | 'heartbeat', ttl = 300) =>
    post<any>(`/contents/${id}/lock`, { action, ttl_seconds: ttl }),
  comments: (id: string, unresolvedOnly = false) =>
    get<CommentItem[]>(`/contents/${id}/comments${unresolvedOnly ? '?unresolved_only=true' : ''}`),
  addComment: (id: string, body: string, blockId?: string) =>
    post<CommentItem>(`/contents/${id}/comments`, { body, block_id: blockId }),
  resolveComment: (id: string, cid: string) => post<CommentItem>(`/contents/${id}/comments/${cid}/resolve`),
  reviews: (id: string) => get<ReviewTaskItem[]>(`/contents/${id}/reviews`),
  review: (id: string, to_status: string, reason = '', assignee_id?: string) =>
    post<any>(`/contents/${id}/review`, { to_status, reason, assignee_id }),

  // ---------- export ----------
  exportContent: (id: string, body: any) => post<any>(`/contents/${id}/export`, body),
  exportJob: (jid: string) => get<any>(`/contents/export/jobs/${jid}`),
  downloadUrl: (id: string, version?: number) =>
    `${BASE}/contents/${id}/download${version ? `?version=${version}` : ''}`,

  // ---------- templates / themes ----------
  templates: (kind?: string) => get<TemplateItem[]>(`/templates${kind ? `?kind=${kind}` : ''}`),
  scenarios: () => get<{ scenarios: string[] }>('/templates/scenarios'),
  templatePreview: (id: string) => get<{ html: string }>(`/templates/${id}/preview`),
  instantiateTemplate: (id: string, name: string, locale = 'zh-CN') =>
    post<ContentItem>(`/templates/${id}/instantiate?name=${encodeURIComponent(name)}&locale=${locale}`),
  themes: (kind?: string) => get<ThemeItem[]>(`/themes${kind ? `?kind=${kind}` : ''}`),
  themeTokens: (themeId?: string) =>
    get<{ tokens: Record<string, TokenItem>; css: string }>(
      `/themes/tokens${themeId ? `?theme_id=${themeId}` : ''}`
    ),

  // ---------- plugins ----------
  plugins: () => get<PluginItem[]>('/plugins'),
  scanPlugins: () => get<any>('/plugins/scan'),
  scaffoldPlugin: (dir: string, key: string, name: string) =>
    get<any>(`/plugins/scaffold?directory=${encodeURIComponent(dir)}&key=${key}&name=${encodeURIComponent(name)}`),
  installPlugin: (body: { path?: string; zip_path?: string; url?: string; activate?: boolean }) =>
    post<any>('/plugins/install', body),
  activatePlugin: (key: string) => post<PluginItem>(`/plugins/${key}/activate`),
  disablePlugin: (key: string) => post<PluginItem>(`/plugins/${key}/disable`),
  uninstallPlugin: (key: string, purge = false) => del(`/plugins/${key}?purge=${purge}`),
  mcpServers: () => get<any[]>('/plugins/mcp/servers'),
  mcpProbe: (config: any) => post<any>('/plugins/mcp/probe', { config }),
  mcpCall: (config: any, tool: string, args: any = {}) =>
    post<any>('/plugins/mcp/call', { config, tool, arguments: args }),

  // ---------- projects ----------
  projects: () => get<any[]>('/projects'),
  createProject: (body: any) => post<any>('/projects', body)
}

export default api