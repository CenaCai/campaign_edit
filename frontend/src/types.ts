/**
 * 全局类型定义 —— 与后端 Block Schema 对齐。
 * 这是前端唯一的类型来源；改这里等于改契约。
 */

export type ContentKind = 'email' | 'form' | 'landing'
export type ContentStatus = 'draft' | 'in_review' | 'approved' | 'published' | 'archived'

export interface BlockNode {
  id: string
  type: string
  props: Record<string, any>
  style: Record<string, string>
  children: BlockNode[]
  name?: string
  hidden?: boolean
  behaviors?: Record<string, any>
  /** 后端 _dispatch 用：渲染器名（插件组件走 generic 渲染） */
  _renderer?: string
}

export interface DocMeta {
  key: string
  name: string
  locale: string
  subject: string
  preheader: string
  description: string
}

export interface ContentSchema {
  schema_version: string
  kind: ContentKind
  doc: DocMeta
  theme: { theme_id: string; token_overrides: Record<string, string> }
  root: BlockNode
  warnings?: string[]
}

export interface PropField {
  type: 'string' | 'number' | 'boolean' | 'array' | 'object'
  label: string
  default?: any
  required?: boolean
  enum?: any[]
  editor?: 'richtext' | 'json' | 'color'
  props?: Record<string, PropField>
  min?: number
  max?: number
  maxLength?: number
}

export interface BlockSpec {
  key: string
  name: string
  kind: ContentKind[]
  category: string
  is_container: boolean
  renderer: string
  props_schema: Record<string, PropField>
  style_defaults: Record<string, string>
  children_allowed?: string[] | null
  children_limit?: { min?: number; max?: number } | null
  source: string
  example?: Record<string, any>
}

export interface ContentItem {
  id: string
  key: string
  name: string
  kind: ContentKind
  status: ContentStatus
  locale: string
  project_id: string | null
  template_id: string | null
  theme_id: string | null
  intent_id: string | null
  current_version: number
  current_version_id: string | null
  owner_id: string | null
  lock_owner_id: string | null
  lock_expires_at: string | null
  lock_version: number
  published_version_id: string | null
  export_path: string | null
  mautic_asset_id: number | null
  meta: Record<string, any>
  created_at: string
  updated_at: string
}

export interface LintIssue {
  code: string
  severity: 'error' | 'warn' | 'info'
  message: string
  node_id: string
  fix: string
}

export interface LintResult {
  kind: string
  issues: LintIssue[]
  counts: Record<string, number>
  passed: boolean
  score: number
  html_size: number
}

export interface PreviewPayload {
  kind: ContentKind
  html: string
  lint: LintResult
  info: {
    name: string
    subject: string
    locale: string
    block_count: number
    text_chars: number
    link_count: number
    blocks: Array<{ id: string; type: string; depth: number; label: string }>
  }
}

export interface TemplateItem {
  id: string
  key: string
  name: string
  kind: ContentKind
  scenario: string
  locale: string
  channel: string
  description: string
  tags: string[]
  thumbnail: string
  usage_count: number
  is_active: boolean
  source_plugin: string | null
  created_at: string
}

export interface ThemeItem {
  id: string
  key: string
  name: string
  kind_scope: string
  tokens: Record<string, string>
  is_builtin: boolean
  source_plugin: string | null
}

export interface IntentPlanAsset {
  kind: ContentKind
  role: string
  purpose: string
  scenario: string
  locale: string
  slots: Record<string, any>
  depends_on: string[]
  template_id: string | null
  template_name?: string
  template_score: number
  template_candidates: Array<{
    template_id: string
    template_key: string
    name: string
    score: number
    scenario: string
    description: string
  }>
  component_hints: string[]
  followups: Array<{ slot: string; question: string; required: boolean; options: string[] }>
}

export interface IntentResult {
  id?: string | null
  ok: boolean
  engine: 'rule' | 'llm' | 'hybrid'
  raw_text: string
  content_type: ContentKind | null
  confidence: number
  scenario: string
  locale: string
  slots: Record<string, any>
  plan: IntentPlanAsset[]
  candidates: Array<{ kind: string; score: number }>
  rule_scores: Record<string, number>
  rule_evidence: Array<{ layer: string; keyword: string; kind: string; weight: number }>
  explanation: {
    agreed?: boolean
    arbiter?: string
    note?: string
    reasoning?: string
    degraded?: boolean
    scenarios?: string[]
    channels?: string[]
    tones?: string[]
    auto_create_blocked?: string
    channels_detail?: Record<string, any>
  }
  needs_confirm: boolean
  conflicts: string[]
  warnings: string[]
  latency_ms: number
  degraded: boolean
  llm_error: string
  created_contents: Array<{ id: string; key: string; kind: string; name: string; status: string; url: string }>
}

export interface ContentVersionItem {
  id: string
  content_id: string
  version: number
  version_meta: Record<string, any>
  diff: { summary?: Record<string, number>; changes?: any[] }
  author_name: string
  created_at: string
}

export interface CommentItem {
  id: string
  content_id: string
  block_id: string | null
  body: string
  resolved: boolean
  author_id: string | null
  author_name: string
  created_at: string
}

export interface ReviewTaskItem {
  id: string
  content_id: string
  version_id: string | null
  from_status: string
  to_status: string
  reason: string
  state: string
  assignee_id: string | null
  decided_by: string | null
  decided_at: string | null
  created_at: string
}

export interface PluginItem {
  id: string
  key: string
  name: string
  version: string
  kind: string
  description: string
  author: string
  status: string
  capabilities: string[]
  permissions: string[]
  registry: Record<string, any>
  install_path: string | null
  created_at: string
  updated_at: string
}

export interface TokenItem {
  value: string
  label: string
  type: string
  default: string
}

export interface DiffChange {
  op: 'add' | 'remove' | 'replace' | 'type_change' | 'move' | 'reorder'
  path: string
  old?: any
  new?: any
  type?: string
}