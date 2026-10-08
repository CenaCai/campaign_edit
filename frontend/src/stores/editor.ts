import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api, { ApiError } from '@/api'
import type { BlockNode, BlockSpec, ContentItem, ContentSchema, LintResult, PreviewPayload } from '@/types'
import {
  clone, findNode, findParent, insertNode, makeNode, moveNode, newId,
  removeNode, walk
} from '@/blocks/schema'

/**
 * 编辑器状态中枢。
 *
 * 设计原则：**本地编辑所见即所得，保存时才发请求**。
 * 预览 HTML 由后端渲染（保证与导出产物一致——这是本系统的关键取舍：
 * 前端不复刻渲染逻辑，否则编辑器所见与交付物必然漂移）。
 * 代价是每次结构变更都要打一次 /preview，因此做了 400ms 防抖。
 */
export const useEditorStore = defineStore('editor', () => {
  const content = ref<ContentItem | null>(null)
  const schema = ref<ContentSchema | null>(null)
  const baseVersion = ref<number>(0)
  const lockVersion = ref(0)
  const dirty = ref(false)
  const saving = ref(false)
  const loading = ref(false)

  const selectedId = ref<string>('')
  const hoveredId = ref<string>('')
  const previewHtml = ref('')
  const lint = ref<LintResult | null>(null)
  const info = ref<PreviewPayload['info'] | null>(null)
  const previewing = ref(false)

  const specs = ref<Record<string, BlockSpec>>({})
  const previewMode = ref<'desktop' | 'tablet' | 'mobile'>('desktop')
  const outlineOpen = ref(true)
  const panelTab = ref<'props' | 'style' | 'doc' | 'comments'>('props')
  const comments = ref<any[]>([])
  const reviews = ref<any[]>([])
  const versions = ref<any[]>([])
  const lockInfo = ref<any>(null)

  let previewTimer: number | undefined
  let lockTimer: number | undefined

  const kind = computed(() => schema.value?.kind || content.value?.kind || 'landing')
  const root = computed(() => schema.value?.root || null)

  const selected = computed<BlockNode | null>(() => {
    if (!root.value || !selectedId.value) return null
    return findNode(root.value, selectedId.value)
  })

  const selectedSpec = computed<BlockSpec | null>(() => {
    if (!selected.value) return null
    return specs.value[selected.value.type] || null
  })

  const selectedParent = computed<BlockNode | null>(() => {
    if (!root.value || !selectedId.value) return null
    return findParent(root.value, selectedId.value)
  })

  const blockCount = computed(() => {
    let n = 0
    if (root.value) walk(root.value, (x) => { if (!x.type.endsWith('.root')) n++ })
    return n
  })

  const canUndo = ref(false)
  const undoStack: ContentSchema[] = []
  const redoStack: ContentSchema[] = []

  // ---------------------------------------------------------- 载入

  async function load(id: string) {
    loading.value = true
    try {
      const [c, s, cms, rvs, vrs] = await Promise.all([
        api.content(id),
        api.contentSchema(id),
        api.comments(id).catch(() => []),
        api.reviews(id).catch(() => []),
        api.versions(id).catch(() => [])
      ])
      content.value = c
      schema.value = s.schema as ContentSchema
      baseVersion.value = s.version
      lockVersion.value = c.lock_version
      comments.value = cms
      reviews.value = rvs
      versions.value = vrs
      dirty.value = false
      undoStack.length = 0
      redoStack.length = 0
      canUndo.value = false
      const first = (schema.value.root.children || [])[0]
      selectedId.value = first?.id || ''
      // 抢草稿锁（失败不阻塞，只提示）
      api.lock(id, 'acquire', 300).then((r) => (lockInfo.value = r)).catch(() => {})
      startLockHeartbeat(id)
      await refreshPreview(true)
    } finally {
      loading.value = false
    }
  }

  function unload() {
    stopLockHeartbeat()
    if (content.value) {
      api.lock(content.value.id, 'release').catch(() => {})
    }
    content.value = null
    schema.value = null
    selectedId.value = ''
    previewHtml.value = ''
    lint.value = null
    lockInfo.value = null
  }

  function startLockHeartbeat(id: string) {
    stopLockHeartbeat()
    lockTimer = window.setInterval(() => {
      api.lock(id, 'heartbeat', 300).then((r) => (lockInfo.value = r)).catch(() => {})
    }, 90_000)
  }
  function stopLockHeartbeat() {
    if (lockTimer) { clearInterval(lockTimer); lockTimer = undefined }
  }

  // ---------------------------------------------------------- 撤销/重做

  function snapshot() {
    if (!schema.value) return
    undoStack.push(clone(schema.value))
    if (undoStack.length > 60) undoStack.shift()
    redoStack.length = 0
    canUndo.value = true
    dirty.value = true
  }

  function undo() {
    if (!undoStack.length) return
    const prev = undoStack.pop()
    if (schema.value) redoStack.push(clone(schema.value))
    if (prev) schema.value = prev
    canUndo.value = undoStack.length > 0
    dirty.value = true
    schedulePreview()
  }

  function redo() {
    if (!redoStack.length) return
    const next = redoStack.pop()
    if (schema.value) undoStack.push(clone(schema.value))
    if (next) schema.value = next
    canUndo.value = true
    dirty.value = true
    schedulePreview()
  }

  // ---------------------------------------------------------- 编辑操作

  function addBlock(type: string, parentId?: string, index?: number) {
    const spec = specs.value[type]
    if (!spec || !root.value) return null
    const target = parentId || findContainerFor(type)
    if (!target) return null

    const parentNode = findNode(root.value, target)
    const parentSpec = parentNode ? specs.value[parentNode.type] : undefined
    if (parentSpec) {
      const allowed = parentSpec.children_allowed
      if (allowed?.length && !allowed.includes(type)) {
        ElMessage.warning(`「${parentSpec.name}」只允许放入：${allowed.join('、')}`)
        return null
      }
      const max = parentSpec.children_limit?.max
      if (max && (parentNode?.children || []).length >= max) {
        ElMessage.warning(`「${parentSpec.name}」最多 ${max} 个子组件`)
        return null
      }
    }

    snapshot()
    const node = makeNode(spec, spec.example || {})
    insertNode(root.value, target, node, index)
    selectedId.value = node.id
    panelTab.value = 'props'
    schedulePreview()
    return node
  }

  /** 自动找一个能放该组件的父节点 */
  function findContainerFor(type: string): string | null {
    if (!root.value) return null
    // 优先已选中节点的父节点（就近插入），其次根节点
    if (selectedId.value) {
      const p = findParent(root.value, selectedId.value)
      if (p) {
        const ps = specs.value[p.type]
        if (ps && (!ps.children_allowed?.length || ps.children_allowed.includes(type))) return p.id
      }
    }
    return root.value.id
  }

  function removeSelected() {
    if (!root.value || !selectedId.value) return
    if (selectedId.value === root.value.id) return
    snapshot()
    const parent = findParent(root.value, selectedId.value)
    removeNode(root.value, selectedId.value)
    selectedId.value = parent?.id || root.value.id
    schedulePreview()
  }

  function duplicateSelected() {
    if (!root.value || !selected.value) return
    const parent = findParent(root.value, selected.value.id)
    if (!parent) return
    snapshot()
    const copy = clone(selected.value)
    const reid = (n: BlockNode) => { n.id = newId(); (n.children || []).forEach(reid) }
    reid(copy)
    const idx = (parent.children || []).findIndex((c) => c.id === selectedId.value)
    parent.children.splice(idx + 1, 0, copy)
    selectedId.value = copy.id
    schedulePreview()
  }

  function moveSelected(newParentId: string, index?: number) {
    if (!root.value || !selected.value) return
    snapshot()
    if (moveNode(root.value, selected.value.id, newParentId, index)) {
      schedulePreview()
    }
  }

  function setProp(key: string, value: any) {
    if (!selected.value) return
    if (!dirty.value) snapshot()
    selected.value.props = selected.value.props || {}
    selected.value.props[key] = value
    dirty.value = true
    schedulePreview()
  }

  function setStyle(key: string, value: string) {
    if (!selected.value) return
    if (!dirty.value) snapshot()
    selected.value.style = selected.value.style || {}
    if (value === '' || value === null) delete selected.value.style[key]
    else selected.value.style[key] = value
    dirty.value = true
    schedulePreview()
  }

  function setDoc(key: string, value: string) {
    if (!schema.value) return
    if (!dirty.value) snapshot()
    ;(schema.value.doc as any)[key] = value
    dirty.value = true
    schedulePreview()
  }

  function setToken(key: string, value: string) {
    if (!schema.value) return
    if (!dirty.value) snapshot()
    schema.value.theme.token_overrides = schema.value.theme.token_overrides || {}
    schema.value.theme.token_overrides[key] = value
    dirty.value = true
    schedulePreview()
  }

  function resetToken(key: string) {
    if (!schema.value) return
    snapshot()
    delete schema.value.theme.token_overrides[key]
    dirty.value = true
    schedulePreview()
  }

  function toggleHidden() {
    if (!selected.value) return
    snapshot()
    selected.value.hidden = !selected.value.hidden
    schedulePreview()
  }

  // ---------------------------------------------------------- 预览与保存

  function schedulePreview(delay = 400) {
    if (previewTimer) clearTimeout(previewTimer)
    previewTimer = window.setTimeout(() => refreshPreview(), delay)
  }

  async function refreshPreview(immediate = false) {
    if (!content.value || !schema.value) return
    previewing.value = true
    try {
      if (immediate && dirty.value) {
        // 首次进入时直接取当前已保存版本的预览，避免把未保存内容发上去
        const pv = await api.contentPreview(content.value.id, baseVersion.value)
        applyPreview(pv)
        return
      }
      const pv = await api.contentPreview(content.value.id)
      applyPreview(pv)
    } catch {
      /* 预览失败不阻塞编辑 */
    } finally {
      previewing.value = false
    }
  }

  /** 本地临时渲染（未保存改动时的即时反馈，仅标记结构） */
  function localHint() {
    if (dirty.value && !previewing.value) {
      // 后端预览还没回来；用轻量提示代替，避免用户以为卡住
      return true
    }
    return false
  }

  function applyPreview(pv: any) {
    previewHtml.value = pv.html || ''
    lint.value = pv.lint || null
    info.value = pv.info || null
  }

  async function save(message = '') {
    if (!content.value || !schema.value) return null
    saving.value = true
    try {
      const r = await api.saveContent(content.value.id, {
        schema: schema.value,
        message,
        create_version: true,
        lint_gate: false,
        lock_version: lockVersion.value
      })
      content.value = r
      lockVersion.value = r.lock_version
      baseVersion.value = r.current_version
      dirty.value = false
      undoStack.length = 0
      canUndo.value = false
      versions.value = await api.versions(content.value.id).catch(() => [])
      await refreshPreview(true)
      return r
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 422 && e.lint) {
          ElMessage.warning(`保存被可投递性检查拦截：${e.lint.counts?.error || 0} 个 error，请修复后再存`)
        } else if (e.status === 409) {
          ElMessage.warning('保存失败：内容已被他人更新，请刷新后重试')
        } else {
          ElMessage.warning(e.message)
        }
      }
      throw e
    } finally {
      saving.value = false
    }
  }

  // ---------------------------------------------------------- 协作

  async function addComment(body: string) {
    if (!content.value || !body.trim()) return
    const c = await api.addComment(content.value.id, body.trim(), selectedId.value || undefined)
    comments.value.push(c)
  }

  async function resolveComment(id: string) {
    if (!content.value) return
    const c = await api.resolveComment(content.value.id, id)
    const i = comments.value.findIndex((x) => x.id === id)
    if (i >= 0) comments.value[i] = c
  }

  const unresolvedComments = computed(
    () => comments.value.filter((c) => !c.resolved)
  )

  function commentsForBlock(blockId: string) {
    return comments.value.filter((c) => c.block_id === blockId && !c.resolved)
  }

  // ---------------------------------------------------------- 状态机

  async function transition(to: string, reason = '') {
    if (!content.value) return
    const r = await api.review(content.value.id, to, reason)
    content.value = { ...content.value, status: r.content.status }
    reviews.value = await api.reviews(content.value.id).catch(() => [])
    return r
  }

  const statusLabel: Record<string, string> = {
    draft: '草稿', in_review: '审核中', approved: '已通过',
    published: '已发布', archived: '已归档'
  }
  const transitions: Record<string, string[]> = {
    draft: ['in_review', 'archived'],
    in_review: ['approved', 'draft', 'archived'],
    approved: ['published', 'draft', 'archived'],
    published: ['archived', 'draft'],
    archived: ['draft']
  }
  const statusTagType: Record<string, any> = {
    draft: 'info', in_review: 'warning', approved: 'primary',
    published: 'success', archived: 'info'
  }

  function loadSpecs(all: Record<string, any[]>) {
    const map: Record<string, BlockSpec> = {}
    for (const kindKey of Object.keys(all)) {
      for (const b of all[kindKey]) map[b.key] = b as BlockSpec
    }
    specs.value = map
  }

  return {
    content, schema, baseVersion, lockVersion, dirty, saving, loading,
    selectedId, hoveredId, previewHtml, lint, info, previewing,
    specs, previewMode, outlineOpen, panelTab,
    comments, reviews, versions, lockInfo,
    kind, root, selected, selectedSpec, selectedParent, blockCount,
    canUndo, unresolvedComments,
    load, unload, snapshot, undo, redo,
    addBlock, removeSelected, duplicateSelected, moveSelected,
    setProp, setStyle, setDoc, setToken, resetToken, toggleHidden,
    schedulePreview, refreshPreview, save, localHint,
    addComment, resolveComment, commentsForBlock,
    transition, statusLabel, transitions, statusTagType,
    loadSpecs
  }
})
