<script setup lang="ts">
/**
 * 编辑器视图（三栏）。
 *
 * 预览 iframe 用 srcdoc 承载后端渲染的 HTML —— 所见即所得，且与导出产物完全一致。
 * 组件面板按 props_schema 自动生成表单，新增组件无需改前端代码。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'
import { useEditorStore } from '@/stores/editor'
import { useSessionStore } from '@/stores/session'
import { CATEGORY_LABEL, KIND_LABEL, outline } from '@/blocks/schema'

const route = useRoute()
const router = useRouter()
const ed = useEditorStore()
const session = useSessionStore()

const frameRef = ref<HTMLIFrameElement | null>(null)
const searchBlocks = ref('')
const collapsed = ref<Record<string, boolean>>({})
const saveMsg = ref('')
const exportVisible = ref(false)
const exportTarget = ref<'single_html' | 'bundle' | 'scaffold' | 'mautic'>('bundle')
const exporting = ref(false)
const exportResult = ref<any>(null)
const diffVisible = ref(false)
const diffFrom = ref<number>(1)
const diffTo = ref<number>(1)
const diffData = ref<any>(null)

const FRAME_W = { desktop: '100%', tablet: '820px', mobile: '390px' } as const

const frameWidth = computed(() => FRAME_W[ed.previewMode])
const kindKey = computed(() => ed.kind)

/** 按分类分组的组件（带搜索过滤） */
const blockGroups = computed(() => {
  const all = session.blocks[kindKey.value] || []
  const kw = searchBlocks.value.trim().toLowerCase()
  const filtered = kw
    ? all.filter((b) =>
        b.name.toLowerCase().includes(kw) ||
        b.key.toLowerCase().includes(kw) ||
        (b.props_schema ? Object.keys(b.props_schema).join(' ').toLowerCase().includes(kw) : false))
    : all
  const g: Record<string, any[]> = {}
  for (const b of filtered) {
    const c = b.category || 'basic'
    ;(g[c] = g[c] || []).push(b)
  }
  return g
})

const outlineTree = computed(() => {
  if (!ed.schema) return []
  return outline(ed.schema)
})

const selectedProps = computed(() => {
  const spec = ed.selectedSpec
  if (!spec) return []
  return Object.entries(spec.props_schema || {}).map(([key, meta]: [string, any]) => ({
    key, meta
  }))
})

const styleKeys = computed(() => {
  const st = ed.selected?.style || {}
  return Object.keys(st)
})

/** 主题 token 列表（供 style 面板用） */
const tokenDefs = ref<Record<string, any>>({})

async function loadTokens() {
  try {
    const r = await api.themeTokens(ed.content?.theme_id || undefined)
    tokenDefs.value = r.tokens || {}
  } catch { tokenDefs.value = {} }
}

function onPick(type: string) {
  ed.addBlock(type)
}

function onSelect(id: string) {
  ed.selectedId = id
}

function onFrameLoad() {
  // iframe 内容注入后，把 hover 高亮与点击选中打进去
  injectSelectionBridge()
}

/**
 * 在预览 iframe 里注入选中/悬停高亮。
 * 用 postMessage 而非直接同源访问：更稳，且 iframe 内嵌自有脚本不受 CSP 影响。
 */
function injectSelectionBridge() {
  const doc = frameRef.value?.contentDocument
  if (!doc) return
  const style = doc.createElement('style')
  style.textContent = `
    [data-ce-node]{position:relative;cursor:pointer;outline:1px dashed transparent;transition:outline-color .1s}
    [data-ce-node]:hover{outline-color:#c8102e}
    [data-ce-node].ce-selected{outline:2px solid #c8102e}
    .ce-node-tag{position:absolute;top:0;left:0;background:#c8102e;color:#fff;
      font:10px/1.6 monospace;padding:0 5px;z-index:9999;pointer-events:none;display:none}
    [data-ce-node].ce-selected > .ce-node-tag{display:block}
  `
  doc.head.appendChild(style)

  // 遍历 body 子节点给它们编号；由于后端渲染是树形的 DOM 嵌套，
  // 用深度优先的顺序与 schema 节点顺序对齐。
  const ids = outlineTree.value.map((o) => o.id)
  const walkDom = (node: Element, idx: { v: number }) => {
    for (const child of Array.from(node.children)) {
      const id = ids[idx.v]
      if (id) {
        child.setAttribute('data-ce-node', id)
        const tag = doc.createElement('span')
        tag.className = 'ce-node-tag'
        tag.textContent = id
        child.appendChild(tag)
        idx.v++
      }
      walkDom(child, idx)
    }
  }
  walkDom(doc.body, { v: 0 })

  doc.addEventListener('click', (e) => {
    const el = (e.target as Element)?.closest?.('[data-ce-node]') as HTMLElement | null
    if (el?.getAttribute('data-ce-node')) {
      e.preventDefault()
      e.stopPropagation()
      onSelect(el.getAttribute('data-ce-node')!)
    }
  })
  doc.addEventListener('mouseover', (e) => {
    const el = (e.target as Element)?.closest?.('[data-ce-node]') as HTMLElement | null
    ed.hoveredId = el?.getAttribute('data-ce-node') || ''
  })
}

watch(
  () => ed.previewHtml,
  async () => {
    await nextTick()
    // 内容变了，重新注入高亮桥
    window.setTimeout(injectSelectionBridge, 60)
  }
)

watch(() => ed.selectedId, () => {
  const doc = frameRef.value?.contentDocument
  if (!doc) return
  doc.querySelectorAll('.ce-selected').forEach((el) => el.classList.remove('ce-selected'))
  const el = doc.querySelector(`[data-ce-node="${ed.selectedId}"]`)
  el?.classList.add('ce-selected')
  el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
})

async function doSave() {
  try {
    const r = await ed.save(saveMsg.value || '手动保存')
    if (r) ElMessage.success(`已保存为 v${r.current_version}`)
    saveMsg.value = ''
  } catch (e: any) {
    if (e?.status !== 409 && e?.status !== 422) ElMessage.error(e?.message || '保存失败')
  }
}

async function doTransition(to: string) {
  const label = ed.statusLabel[to] || to
  try {
    await ElMessageBox.confirm(`确认将内容流转到「${label}」状态？`, '状态流转', {
      type: to === 'archived' ? 'warning' : 'info'
    })
  } catch {
    return
  }
  try {
    await ed.transition(to, '编辑器手动流转')
    ElMessage.success(`已流转到 ${label}`)
  } catch (e: any) {
    const allowed = e?.detail?.allowed
    ElMessage.error(
      allowed
        ? `不允许的流转。当前可选：${allowed.join('、')}`
        : e?.message || '流转失败'
    )
  }
}

async function doExport() {
  if (!ed.content) return
  exporting.value = true
  exportResult.value = null
  try {
    if (ed.dirty) await ed.save('导出前自动保存')
    exportResult.value = await api.exportContent(ed.content.id, {
      target: exportTarget.value,
      allow_lint_error: false
    })
    ElMessage.success('导出完成')
  } catch (e: any) {
    if (e?.lint) {
      ElMessage.error(`可投递性检查未通过：${e.lint.counts?.error || 0} 个 error，导出被阻断`)
    } else {
      ElMessage.error(e?.message || '导出失败')
    }
  } finally {
    exporting.value = false
  }
}

function downloadHtml() {
  if (!ed.content) return
  window.open(api.downloadUrl(ed.content.id), '_blank')
}

async function loadDiff() {
  if (!ed.content) return
  const vs = ed.versions
  if (vs.length >= 2) {
    diffFrom.value = vs[1].version
    diffTo.value = vs[0].version
  }
  try {
    diffData.value = await api.diffVersions(ed.content.id, diffFrom.value, diffTo.value)
    diffVisible.value = true
  } catch (e: any) {
    ElMessage.error(e?.message || '对比失败')
  }
}

async function restore(v: number) {
  try {
    await ElMessageBox.confirm(
      `回滚到 v${v}？会以新版本追加，历史不会被删除。`, '版本回滚',
      { type: 'warning' }
    )
  } catch {
    return
  }
  if (!ed.content) return
  try {
    const r = await api.restoreVersion(ed.content.id, v, `回滚到 v${v}`)
    ElMessage.success(`已回滚，当前 v${r.current_version}`)
    await ed.load(ed.content.id)
  } catch (e: any) {
    ElMessage.error(e?.message || '回滚失败')
  }
}

const commentDraft = ref('')

async function submitComment() {
  if (!commentDraft.value.trim()) return
  try {
    await ed.addComment(commentDraft.value)
    commentDraft.value = ''
  } catch (e: any) {
    ElMessage.error(e?.message || '评论失败')
  }
}

function onKeyDown(e: KeyboardEvent) {
  const mod = e.ctrlKey || e.metaKey
  if (!mod) return
  if (e.key === 's') {
    e.preventDefault()
    doSave()
  } else if (e.key === 'z' && !e.shiftKey) {
    e.preventDefault()
    ed.undo()
  } else if ((e.key === 'z' && e.shiftKey) || e.key === 'y') {
    e.preventDefault()
    ed.redo()
  }
}

onMounted(async () => {
  await session.loadBlocks()
  ed.loadSpecs(session.blocks as any)
  await loadTokens()
  const id = route.params.id as string
  if (id) await ed.load(id)
  window.addEventListener('keydown', onKeyDown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown)
  ed.unload()
})
</script>

<template>
  <div v-if="ed.loading" class="ce-page">
    <el-skeleton :rows="8" animated />
  </div>

  <div v-else-if="!ed.content" class="ce-page">
    <el-empty description="内容不存在或已删除">
      <el-button type="primary" @click="router.push('/contents')">返回内容库</el-button>
    </el-empty>
  </div>

  <div v-else class="ce-editor">
    <!-- ============ 左栏：组件 + 大纲 ============ -->
    <aside class="ce-pane">
      <el-tabs model-value="palette" class="ce-pane-head" style="padding-bottom: 0">
        <el-tab-pane label="组件" name="palette">
          <div style="padding: 10px 12px">
            <el-input
              v-model="searchBlocks" size="small" placeholder="搜索组件"
              clearable style="margin-bottom: 10px"
            />
            <div
              v-for="(list, cat) in blockGroups" :key="cat"
              class="ce-block-group"
            >
              <div class="ce-section-title" style="cursor: pointer"
                   @click="collapsed[cat] = !collapsed[cat]">
                {{ CATEGORY_LABEL[cat] || cat }}
                <span class="ce-faint">({{ list.length }})</span>
              </div>
              <template v-if="!collapsed[cat]">
                <div
                  v-for="b in list" :key="b.key"
                  class="ce-block-item"
                  :class="{ 'is-plugin': b.source === 'plugin' }"
                  draggable="true"
                  :title="`${b.key}｜${b.category}`"
                  @click="onPick(b.key)"
                  @dragstart="(e: any) => e.dataTransfer?.setData('text/plain', b.key)"
                >
                  <span>{{ b.name }}</span>
                  <span class="ce-badge">{{ b.key.split('.')[1] }}</span>
                </div>
              </template>
            </div>
            <div v-if="!Object.keys(blockGroups).length" class="ce-faint" style="font-size: 12px">
              没有匹配的组件
            </div>
          </div>
        </el-tab-pane>
        <el-tab-pane label="大纲" name="outline">
          <div class="ce-outline">
            <div
              v-for="o in outlineTree" :key="o.id"
              class="ce-outline-node"
              :class="{
                selected: ed.selectedId === o.id,
                'hidden-node': false
              }"
              :style="{ paddingLeft: (6 + o.depth * 12) + 'px' }"
              @click="onSelect(o.id)"
            >
              <span class="tag">{{ o.type.split('.')[1] }}</span>
              <span style="overflow: hidden; text-overflow: ellipsis">{{ o.label }}</span>
              <span v-if="ed.commentsForBlock(o.id).length" class="cmt">
                ●{{ ed.commentsForBlock(o.id).length }}
              </span>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </aside>

    <!-- ============ 中栏：工具条 + 预览 ============ -->
    <section class="ce-pane center">
      <div class="ce-editor-bar">
        <el-button link @click="router.push('/contents')">← 内容库</el-button>
        <span class="ce-editor-title">{{ ed.content.name }}</span>
        <span class="ce-editor-key">{{ ed.content.key }}</span>
        <el-tag size="small" :type="ed.statusTagType[ed.content.status]">
          {{ ed.statusLabel[ed.content.status] }}
        </el-tag>
        <el-tag size="small" effect="plain">v{{ ed.content.current_version }}</el-tag>
        <span v-if="ed.dirty" style="color: var(--ce-warn); font-size: 12px">● 未保存</span>

        <div class="ce-spacer" />

        <!-- 状态流转 -->
        <el-dropdown @command="doTransition">
          <el-button size="small">
            流转状态<el-icon class="el-icon--right"><arrow-down /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-for="t in (ed.transitions[ed.content.status] || [])"
                :key="t" :command="t"
              >
                {{ ed.statusLabel[t] }}
              </el-dropdown-item>
              <el-dropdown-item v-if="!ed.transitions[ed.content.status]?.length" disabled>
                当前状态无可用流转
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>

        <el-button size="small" @click="loadDiff">版本对比</el-button>
        <el-button size="small" @click="exportVisible = true">导出</el-button>
        <el-button size="small" @click="downloadHtml">下载 HTML</el-button>

        <el-button size="small" type="primary" :loading="ed.saving" @click="doSave">
          保存 {{ ed.canUndo ? '(Ctrl+S)' : '' }}
        </el-button>
      </div>

      <!-- lint 汇总条 -->
      <div
        v-if="ed.lint"
        class="ce-row"
        style="padding: 6px 14px; background: var(--ce-panel); border-bottom: 1px solid var(--ce-border); font-size: 12px; flex-wrap: wrap; gap: 10px"
      >
        <el-tag size="small" :type="ed.lint.passed ? 'success' : 'danger'" effect="plain">
          可投递性 {{ ed.lint.passed ? '通过' : '未通过' }} · {{ ed.lint.score }} 分
        </el-tag>
        <span v-if="ed.lint.counts.error" style="color: var(--ce-danger)">
          {{ ed.lint.counts.error }} error
        </span>
        <span v-if="ed.lint.counts.warn" style="color: var(--ce-warn)">
          {{ ed.lint.counts.warn }} warning
        </span>
        <span v-if="ed.lint.counts.info" class="ce-muted">
          {{ ed.lint.counts.info }} info
        </span>
        <div class="ce-spacer" />
        <span class="ce-faint">
          {{ ed.info?.block_count || 0 }} 个块 · {{ ed.info?.text_chars || 0 }} 字符 ·
          {{ Math.round((ed.lint.html_size || 0) / 1024) }} KB
        </span>
        <el-tag v-if="ed.previewing" size="small" type="info">渲染中…</el-tag>
      </div>

      <!-- 预览舞台 -->
      <div class="ce-stage">
        <div class="ce-frame-wrap" :style="{ width: frameWidth }">
          <div class="ce-row" style="justify-content: center; gap: 4px; margin-bottom: 8px">
            <el-radio-group v-model="ed.previewMode" size="small">
              <el-radio-button value="desktop">桌面</el-radio-button>
              <el-radio-button value="tablet">平板 820</el-radio-button>
              <el-radio-button value="mobile">手机 390</el-radio-button>
            </el-radio-group>
          </div>
          <div class="ce-frame">
            <iframe
              ref="frameRef"
              :srcdoc="ed.previewHtml"
              sandbox="allow-same-origin allow-scripts"
              :style="{ height: kindKey === 'email' ? '760px' : '900px' }"
              @load="onFrameLoad"
            />
          </div>
          <div class="ce-frame-label">
            点击预览中的任意区块即可选中并编辑 · 编辑体验由后端渲染保证与导出一致
          </div>
        </div>
      </div>
    </section>

    <!-- ============ 右栏：属性 / 样式 / 文档 / 评论 ============ -->
    <aside class="ce-pane right">
      <div class="ce-pane-head">
        <el-tabs v-model="ed.panelTab" style="flex: 1">
          <el-tab-pane label="属性" name="props" />
          <el-tab-pane label="样式" name="style" />
          <el-tab-pane label="文档" name="doc" />
          <el-tab-pane label="评论" name="comments">
            <template #label>
              评论
              <el-badge v-if="ed.unresolvedComments.length" :value="ed.unresolvedComments.length" class="ce-tab-badge" />
            </template>
          </el-tab-pane>
        </el-tabs>
      </div>

      <div style="padding: 12px">
        <!-- 属性 -->
        <template v-if="ed.panelTab === 'props'">
          <div v-if="!ed.selected" class="ce-faint" style="font-size: 12px">
            在左侧点击组件、或在预览中点击区块来编辑属性。
          </div>
          <template v-else>
            <div class="ce-card" style="padding: 9px 11px; margin-bottom: 12px; background: var(--ce-bg)">
              <div style="font-weight: 650; font-size: 13px">{{ ed.selectedSpec?.name || ed.selected.type }}</div>
              <div class="ce-mono ce-faint" style="margin-top: 2px">{{ ed.selected.type }}</div>
            </div>

            <div class="ce-row" style="gap: 6px; margin-bottom: 12px">
              <el-button size="small" @click="ed.duplicateSelected()">复制</el-button>
              <el-button size="small" @click="ed.toggleHidden()">
                {{ ed.selected.hidden ? '显示' : '隐藏' }}
              </el-button>
              <el-button size="small" type="danger" plain @click="ed.removeSelected()">删除</el-button>
            </div>

            <div v-for="p in selectedProps" :key="p.key" class="ce-prop-row">
              <div class="ce-prop-label">
                {{ p.meta.label }}
                <span v-if="p.meta.required" class="ce-prop-req">*</span>
              </div>

              <el-select
                v-if="p.meta.enum"
                :model-value="ed.selected.props[p.key]"
                size="small" style="width: 100%"
                @update:model-value="(v: any) => ed.setProp(p.key, v)"
              >
                <el-option v-for="o in p.meta.enum" :key="String(o)" :label="String(o)" :value="o" />
              </el-select>

              <el-switch
                v-else-if="p.meta.type === 'boolean'"
                :model-value="!!ed.selected.props[p.key]"
                size="small"
                @update:model-value="(v: any) => ed.setProp(p.key, v)"
              />

              <el-input-number
                v-else-if="p.meta.type === 'number'"
                :model-value="Number(ed.selected.props[p.key] ?? 0)"
                size="small" style="width: 100%" :controls="false"
                @update:model-value="(v: any) => ed.setProp(p.key, v)"
              />

              <div v-else-if="p.meta.type === 'array'" class="ce-col" style="gap: 6px">
                <div
                  v-for="(row, ri) in (ed.selected.props[p.key] || [])"
                  :key="ri" class="ce-row" style="gap: 4px"
                >
                  <template v-for="(val, k) in row" :key="k">
                    <el-input
                      :model-value="String(val)"
                      size="small" :placeholder="String(k)"
                      style="flex: 1"
                      @update:model-value="(v: any) => {
                        const arr = JSON.parse(JSON.stringify(ed.selected!.props[p.key]))
                        arr[ri][k] = v
                        ed.setProp(p.key, arr)
                      }"
                    />
                  </template>
                  <el-button link size="small" type="danger"
                             @click="ed.setProp(p.key, (ed.selected!.props[p.key] || []).filter((_: any, i: number) => i !== ri))">
                    ×
                  </el-button>
                </div>
                <el-button size="small" plain
                           @click="ed.setProp(p.key, [...(ed.selected!.props[p.key] || []), {}])">
                  + 添加一项
                </el-button>
              </div>

              <el-input
                v-else-if="p.meta.editor === 'richtext'"
                type="textarea" :rows="4" resize="vertical"
                :model-value="String(ed.selected.props[p.key] ?? '')"
                class="ce-mono"
                @update:model-value="(v: string) => ed.setProp(p.key, v)"
              />

              <el-input
                v-else
                size="small"
                :model-value="String(ed.selected.props[p.key] ?? '')"
                :placeholder="p.meta.placeholder"
                @update:model-value="(v: string) => ed.setProp(p.key, v)"
              />

              <div v-if="p.key === 'html'" class="ce-prop-desc">
                支持基础 HTML 标签；脚本与事件属性会在保存时被自动剥离
              </div>
              <div v-if="p.key === 'alt'" class="ce-prop-desc">
                无障碍必填项，缺失会在可投递性检查中被标记
              </div>
              <div v-if="p.key === 'url' || p.key === 'src'" class="ce-prop-desc">
                邮件与投放场景请使用绝对地址（https://）
              </div>
            </div>

            <div v-if="!selectedProps.length" class="ce-faint" style="font-size: 12px">
              该组件没有可配置属性，可在「样式」标签调整外观。
            </div>
          </template>
        </template>

        <!-- 样式 -->
        <template v-else-if="ed.panelTab === 'style'">
          <div v-if="ed.selected">
            <div class="ce-section-title">当前节点样式</div>
            <div v-if="!styleKeys.length" class="ce-faint" style="font-size: 12px; margin-bottom: 12px">
              该节点尚未设置自定义样式。
            </div>
            <div v-for="k in styleKeys" :key="k" class="ce-style-row" style="margin-bottom: 6px">
              <span class="k">{{ k }}</span>
              <el-input
                :model-value="String(ed.selected.style[k])"
                size="small" style="flex: 1"
                @update:model-value="(v: string) => ed.setStyle(k, v)"
              />
              <el-button link size="small" @click="ed.setStyle(k, '')">×</el-button>
            </div>

            <div class="ce-section-title" style="margin-top: 16px">设计 token 覆盖</div>
            <div class="ce-faint" style="font-size: 11.5px; margin-bottom: 8px">
              token 会传导到所有引用它的节点，是换肤的正确入口。
            </div>
            <div
              v-for="(t, tk) in tokenDefs" :key="tk"
              class="ce-token-row"
            >
              <div>
                <div class="ce-token-name">--{{ tk }}</div>
                <div class="ce-token-label">{{ t.label }}</div>
              </div>
              <div class="ce-row" style="gap: 4px">
                <span
                  v-if="t.type === 'color'"
                  :style="{ width: 20, height: 20, borderRadius: '4px', border: '1px solid var(--ce-border)', background: ed.schema?.theme.token_overrides?.[tk] || t.default }"
                />
                <el-input
                  :model-value="ed.schema?.theme.token_overrides?.[tk] || ''"
                  :placeholder="t.default"
                  size="small" style="width: 92px"
                  @update:model-value="(v: string) => ed.setToken(tk, v)"
                />
                <el-button
                  v-if="ed.schema?.theme.token_overrides?.[tk]"
                  link size="small" @click="ed.resetToken(tk)"
                >重置</el-button>
              </div>
            </div>
          </div>
          <div v-else class="ce-faint" style="font-size: 12px">先选中一个节点。</div>
        </template>

        <!-- 文档设置 -->
        <template v-else-if="ed.panelTab === 'doc'">
          <div class="ce-prop-row">
            <div class="ce-prop-label">内容名称</div>
            <el-input
              :model-value="ed.schema?.doc.name"
              size="small"
              @update:model-value="(v: string) => ed.setDoc('name', v)"
            />
          </div>
          <div class="ce-prop-row">
            <div class="ce-prop-label">Key（对外标识）</div>
            <el-input :model-value="ed.schema?.doc.key" size="small" disabled />
          </div>
          <template v-if="ed.kind === 'email'">
            <div class="ce-prop-row">
              <div class="ce-prop-label">邮件主题 <span class="ce-prop-req">*</span></div>
              <el-input
                :model-value="ed.schema?.doc.subject"
                size="small" show-word-limit maxlength="120"
                @update:model-value="(v: string) => ed.setDoc('subject', v)"
              />
              <div class="ce-prop-desc">移动端约 35 字后截断，建议控制在 35 字内</div>
            </div>
            <div class="ce-prop-row">
              <div class="ce-prop-label">预览文案（preheader）</div>
              <el-input
                :model-value="ed.schema?.doc.preheader"
                size="small" maxlength="120"
                @update:model-value="(v: string) => ed.setDoc('preheader', v)"
              />
              <div class="ce-prop-desc">收件箱里主题之后显示的一行摘要</div>
            </div>
          </template>
          <div class="ce-prop-row">
            <div class="ce-prop-label">描述（用于 SEO / og）</div>
            <el-input
              type="textarea" :rows="3" resize="vertical"
              :model-value="ed.schema?.doc.description"
              @update:model-value="(v: string) => ed.setDoc('description', v)"
            />
          </div>
          <div class="ce-prop-row">
            <div class="ce-prop-label">语言</div>
            <el-select
              :model-value="ed.schema?.doc.locale" size="small" style="width: 100%"
              @update:model-value="(v: string) => ed.setDoc('locale', v)"
            >
              <el-option label="简体中文" value="zh-CN" />
              <el-option label="English (UK)" value="en-GB" />
              <el-option label="English (US)" value="en-US" />
            </el-select>
          </div>

          <div class="ce-section-title" style="margin-top: 18px">版本历史</div>
          <div
            v-for="v in ed.versions" :key="v.id"
            class="ce-version" :class="{ current: v.version === ed.content.current_version }"
          >
            <span class="ce-version-n">v{{ v.version }}</span>
            <div style="flex: 1; min-width: 0">
              <div style="font-size: 12.5px">{{ v.version_meta?.message || '—' }}</div>
              <div class="ce-faint" style="font-size: 11px">
                {{ v.author_name }} ·
                {{ new Date(v.created_at).toLocaleString('zh-CN') }}
                <span v-if="v.diff?.summary && Object.keys(v.diff.summary).length">
                  · 改动 {{ Object.values(v.diff.summary).reduce((a: any, b: any) => a + b, 0) }} 处
                </span>
              </div>
            </div>
            <el-button
              v-if="v.version !== ed.content.current_version"
              link size="small" @click="restore(v.version)"
            >回滚</el-button>
          </div>
        </template>

        <!-- 评论 -->
        <template v-else>
          <div class="ce-row" style="margin-bottom: 10px">
            <el-input
              v-model="commentDraft" type="textarea" :rows="3" resize="none"
              :placeholder="ed.selected ? `对「${ed.selectedSpec?.name}」评论` : '先选中节点可精确评论到该区块；否则评论整篇内容'"
            />
            <el-button type="primary" size="small" @click="submitComment">发表</el-button>
          </div>

          <div
            v-for="c in ed.comments" :key="c.id"
            class="ce-comment" :class="{ resolved: c.resolved }"
          >
            <div class="ce-comment-head">
              <span class="ce-avatar">{{ (c.author_name || 'U').slice(0, 1) }}</span>
              <span style="font-size: 12.5px; font-weight: 600">{{ c.author_name }}</span>
              <span v-if="c.block_id" class="ce-tag">锚点 {{ c.block_id }}</span>
              <div class="ce-spacer" />
              <span class="ce-faint" style="font-size: 11px">
                {{ new Date(c.created_at).toLocaleString('zh-CN') }}
              </span>
            </div>
            <div style="font-size: 12.5px; line-height: 1.5">{{ c.body }}</div>
            <div v-if="!c.resolved" style="margin-top: 6px">
              <el-button link size="small" @click="ed.resolveComment(c.id)">标记已解决</el-button>
            </div>
          </div>
          <div v-if="!ed.comments.length" class="ce-faint" style="font-size: 12px">
            暂无评论。多人协作时，评论会锚定到具体区块。
          </div>
        </template>
      </div>
    </aside>

    <!-- ============ 导出对话框 ============ -->
    <el-dialog v-model="exportVisible" title="导出与交付" width="620px">
      <el-form label-width="96px">
        <el-form-item label="导出目标">
          <el-radio-group v-model="exportTarget">
            <el-radio value="single_html">单文件 HTML</el-radio>
            <el-radio value="bundle">Bundle（zip）</el-radio>
            <el-radio value="scaffold">Vite 脚手架</el-radio>
            <el-radio value="mautic" :disabled="!session.config?.mautic?.configured">
              推送到 Mautic
            </el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>

      <el-alert type="info" :closable="false" show-icon style="margin-bottom: 12px">
        <template #title>
          <span v-if="exportTarget === 'single_html'">生成一个自包含 HTML，可直接投放或邮件内嵌</span>
          <span v-else-if="exportTarget === 'bundle'">
            产出 zip：index.html + tokens.css + schema.json + README（可回灌继续编辑）
          </span>
          <span v-else-if="exportTarget === 'scaffold'">
            产出 Vite 工程：src/ 拆分 + tokens + dev/build 脚本，适合交给前端继续开发
          </span>
          <span v-else>
            投递到 Mautic：邮件 → /emails，表单 → /forms，页面 → /pages（仅软上下线，不做删除）
          </span>
        </template>
      </el-alert>

      <div v-if="exportResult" class="ce-col">
        <el-alert
          type="success" :closable="false" show-icon
          :title="`导出成功（${exportResult.target}）`"
        />
        <div v-if="exportResult.files?.zip" class="ce-col">
          <div class="ce-section-title">产物路径</div>
          <div class="ce-code">{{ exportResult.files.zip }}</div>
        </div>
        <div v-if="exportResult.files?.files" class="ce-col">
          <div class="ce-section-title">包含文件</div>
          <div class="ce-tag-list">
            <span v-for="f in exportResult.files.files" :key="f" class="ce-tag">{{ f }}</span>
          </div>
        </div>
        <div v-if="exportResult.mautic" class="ce-col">
          <div class="ce-section-title">Mautic 资产</div>
          <div class="ce-code">
            {{ exportResult.mautic.asset_type }} #{{ exportResult.mautic.asset_id }}
          </div>
        </div>
        <el-alert
          v-if="exportResult.lint"
          :type="exportResult.lint.passed ? 'success' : 'warning'"
          :closable="false" show-icon
          :title="`可投递性 ${exportResult.lint.score} 分｜error ${exportResult.lint.counts.error} / warning ${exportResult.lint.counts.warn}`"
        />
      </div>

      <template #footer>
        <el-button @click="exportVisible = false">关闭</el-button>
        <el-button type="primary" :loading="exporting" @click="doExport">执行导出</el-button>
      </template>
    </el-dialog>

    <!-- ============ 版本对比 ============ -->
    <el-dialog v-model="diffVisible" title="版本对比" width="860px">
      <div class="ce-row" style="margin-bottom: 12px">
        <el-select v-model="diffFrom" size="small" style="width: 120px">
          <el-option v-for="v in ed.versions" :key="v.id" :label="`v${v.version}`" :value="v.version" />
        </el-select>
        <span>→</span>
        <el-select v-model="diffTo" size="small" style="width: 120px">
          <el-option v-for="v in ed.versions" :key="v.id" :label="`v${v.version}`" :value="v.version" />
        </el-select>
        <el-button size="small" @click="loadDiff">对比</el-button>
        <div class="ce-spacer" />
        <div v-if="diffData" class="ce-row" style="gap: 8px; font-size: 12px">
          <span v-for="(n, op) in diffData.summary" :key="op" class="ce-tag">{{ op }} {{ n }}</span>
        </div>
      </div>

      <div v-if="diffData" class="ce-diff">
        <div
          v-for="(c, i) in diffData.changes" :key="i"
          class="ce-diff-row" :class="`ce-diff-${c.op}`"
        >
          <b>{{ c.op }}</b> {{ c.path }}
          <span v-if="c.old !== undefined" class="ce-faint"> · 原: {{ String(c.old).slice(0, 60) }}</span>
          <span v-if="c.new !== undefined" class="ce-faint"> → 新: {{ String(c.new).slice(0, 60) }}</span>
          <span v-if="c.type" class="ce-faint"> ({{ c.type }})</span>
        </div>
        <div v-if="!diffData.changes?.length" style="padding: 20px; text-align: center" class="ce-faint">
          两个版本无差异
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.ce-tab-badge :deep(.el-badge__content) {
  transform: translate(80%, -50%) scale(0.8);
}
</style>