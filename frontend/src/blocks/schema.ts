/**
 * Block Schema 本地操作 —— 与后端 blocks/schema.py 语义一致。
 *
 * 关键约束（编辑器必须遵守，否则保存会被后端规范化掉）：
 * 1. props 只允许 props_schema 声明过的字段；
 * 2. style 只允许白名单CSS 属性；
 * 3. 节点 id 全局唯一且稳定（评论锚点/协作依赖）。
 */
import type { BlockNode, BlockSpec, ContentSchema, PropField } from '@/types'

export const ALLOWED_STYLE_KEYS = [
  'display', 'width', 'max_width', 'min_height', 'height',
  'margin', 'margin_top', 'margin_bottom', 'margin_left', 'margin_right',
  'padding', 'padding_top', 'padding_bottom', 'padding_left', 'padding_right',
  'background', 'background_color', 'background_image', 'background_size',
  'background_position', 'background_repeat', 'border', 'border_radius',
  'border_color', 'border_width', 'border_style', 'box_shadow',
  'color', 'font_size', 'font_weight', 'font_family', 'line_height',
  'letter_spacing', 'text_align', 'text_transform', 'text_decoration',
  'vertical_align', 'opacity', 'overflow', 'position', 'top', 'left', 'gap'
] as const

export const EMAIL_UNSAFE_STYLE_KEYS = new Set([
  'position', 'top', 'left', 'gap', 'min_height', 'box_shadow', 'overflow'
])

/** CSS 属性名 → schema.style 键名（schema 用下划线） */
export const CSS_TO_SCHEMA_STYLE: Record<string, string> = Object.fromEntries(
  ALLOWED_STYLE_KEYS.map((k) => [k.replace(/_/g, '-'), k])
)
export const SCHEMA_TO_CSS_STYLE: Record<string, string> = Object.fromEntries(
  ALLOWED_STYLE_KEYS.map((k) => [k, k.replace(/_/g, '-')])
)

export function newId(prefix = 'b'): string {
  const rand = Math.random().toString(36).slice(2, 12)
  return `${prefix}_${rand}`
}

export function clone<T>(v: T): T {
  return typeof v === 'object' && v !== null ? JSON.parse(JSON.stringify(v)) : v
}

/** 深度遍历 */
export function walk(node: BlockNode, fn: (n: BlockNode, parent: BlockNode | null) => void,
                      parent: BlockNode | null = null) {
  fn(node, parent)
  for (const c of node.children || []) walk(c, fn, node)
}

export function findNode(root: BlockNode, id: string): BlockNode | null {
  let found: BlockNode | null = null
  walk(root, (n) => {
    if (n.id === id) found = n
  })
  return found
}

export function findParent(root: BlockNode, id: string): BlockNode | null {
  let found: BlockNode | null = null
  walk(root, (n) => {
    for (const c of n.children || []) {
      if (c.id === id) found = n
    }
  })
  return found
}

/** 节点在树中的路径（从 root 起的 index 序列），用于定位与移动 */
export function nodePath(root: BlockNode, id: string): number[] | null {
  const dfs = (node: BlockNode, path: number[]): number[] | null => {
    if (node.id === id) return path
    for (let i = 0; i < (node.children || []).length; i++) {
      const r = dfs(node.children[i], [...path, i])
      if (r) return r
    }
    return null
  }
  return dfs(root, [])
}

/** 由 props_schema 生成默认值 */
export function defaultProps(spec: BlockSpec): Record<string, any> {
  const out: Record<string, any> = {}
  for (const [key, meta] of Object.entries(spec.props_schema || {})) {
    if (meta.default !== undefined) out[key] = clone(meta.default)
    else if (meta.type === 'object' && meta.props) {
      const sub: Record<string, any> = {}
      for (const [k, m] of Object.entries(meta.props)) {
        sub[k] = m.default !== undefined ? clone(m.default) : ''
      }
      out[key] = sub
    } else out[key] = meta.type === 'boolean' ? false : meta.type === 'array' ? [] : ''
  }
  return out
}

/** 创建节点：props 合并默认值 + style_defaults 预填 */
export function makeNode(spec: BlockSpec, props: Record<string, any> = {}, id?: string): BlockNode {
  const merged = { ...defaultProps(spec), ...props }
  const style: Record<string, string> = {}
  for (const [k, v] of Object.entries(spec.style_defaults || {})) {
    if (v !== null && v !== undefined && v !== '') style[k] = String(v)
  }
  return {
    id: id || newId(),
    type: spec.key,
    props: merged,
    style,
    children: spec.is_container ? [] : [],
    _renderer: spec.renderer
  }
}

/** 插入子节点；受 children_allowed / children_limit 约束 */
export function canInsert(parent: BlockSpec, childType: string,
                         parentNode?: BlockNode): { ok: boolean; reason?: string } {
  if (!parent.is_container) return { ok: false, reason: `组件「${parent.name}」不是容器` }
  const allowed = parent.children_allowed
  if (allowed && allowed.length && !allowed.includes(childType)) {
    return {
      ok: false,
      reason: `「${parent.name}」只允许放入：${allowed.join('、')}`
    }
  }
  const max = parent.children_limit?.max
  if (max && parentNode && (parentNode.children || []).length >= max) {
    return { ok: false, reason: `「${parent.name}」最多 ${max} 个子组件` }
  }
  return { ok: true }
}

export function insertNode(root: BlockNode, parentId: string, node: BlockNode, index?: number): boolean {
  const parent = findNode(root, parentId)
  if (!parent) return false
  parent.children = parent.children || []
  if (index === undefined || index < 0 || index > parent.children.length) {
    parent.children.push(node)
  } else {
    parent.children.splice(index, 0, node)
  }
  return true
}

export function removeNode(root: BlockNode, id: string): boolean {
  const parent = findParent(root, id)
  if (!parent) return false
  const i = (parent.children || []).findIndex((c) => c.id === id)
  if (i < 0) return false
  parent.children.splice(i, 1)
  return true
}

export function moveNode(root: BlockNode, id: string, newParentId: string, index?: number): boolean {
  const node = findNode(root, id)
  const newParent = findNode(root, newParentId)
  if (!node || !newParent) return false
  // 禁止把父节点拖进自己的子树
  let inSubtree = false
  walk(node, (n) => {
    if (n.id === newParentId) inSubtree = true
  })
  if (inSubtree) return false
  removeNode(root, id)
  newParent.children = newParent.children || []
  if (index === undefined || index < 0) newParent.children.push(node)
  else newParent.children.splice(Math.min(index, newParent.children.length), 0, node)
  return true
}

export function duplicateNode(specs: Map<string, BlockSpec>, root: BlockNode, id: string): BlockNode | null {
  const node = findNode(root, id)
  if (!node) return null
  const copy = clone(node)
  const reid = (n: BlockNode) => {
    n.id = newId()
    for (const c of n.children || []) reid(c)
  }
  reid(copy)
  insertNode(root, node.id, copy, 1)
  return copy
}

/** schema → CSS 文本（预览用，样式编辑面板用） */
export function nodeStyle(node: BlockNode, kind: string): string {
  const email = kind === 'email'
  const parts: string[] = []
  for (const [k, v] of Object.entries(node.style || {})) {
    if (v === null || v === undefined || v === '') continue
    const cssKey = SCHEMA_TO_CSS_STYLE[k]
    if (!cssKey) continue
    if (email && EMAIL_UNSAFE_STYLE_KEYS.has(k)) continue
    parts.push(`${cssKey}:${v}`)
  }
  return parts.join(';')
}

/** 统计大纲 */
export function outline(schema: ContentSchema) {
  const out: Array<{ id: string; type: string; label: string; depth: number }> = []
  const labelOf = (n: BlockNode) => {
    const p = n.props || {}
    const raw = p.text || p.label || p.title || p.name || p.form_name || p.event_name
    const text = String(raw ?? '')
      .replace(/<[^>]+>/g, ' ')
      .trim()
    return text.slice(0, 40) || n.type
  }
  walk(schema.root, (n, parent) => {
    if (n.type.endsWith('.root')) return
    let depth = 0
    let p: BlockNode | null = parent
    while (p && !p.type.endsWith('.root')) {
      depth++
      p = findParent(schema.root, p.id)
    }
    out.push({ id: n.id, type: n.type, label: labelOf(n), depth })
  })
  return out
}

export const KIND_LABEL: Record<string, string> = {
  email: 'HTML 邮件',
  form: '表单',
  landing: '着陆页 / 活动站点'
}

export const STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  in_review: '审核中',
  approved: '已通过',
  published: '已发布',
  archived: '已归档'
}

export const CATEGORY_LABEL: Record<string, string> = {
  layout: '布局',
  layout_only: '容器',
  hero: '首屏',
  text: '文本',
  media: '图片 / 视频',
  action: '按钮 / 行动点',
  form: '表单控件',
  social: '社交 / 分享',
  commerce: '票务 / 商品',
  trust: '信任背书',
  basic: '基础',
  plugin: '插件组件'
}

export function propsLabel(spec: BlockSpec, key: string, meta?: PropField): string {
  return meta?.label || key
}