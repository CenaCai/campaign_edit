<script setup lang="ts">
/** 主题与设计 token：换肤的唯一入口，所有内容共用同一套 token 语义。 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const themes = ref<any[]>([])
const tokens = ref<Record<string, any>>({})
const cssText = ref('')
const active = ref<string>('')
const editing = ref<Record<string, string>>({})
const kindScope = ref<string>('')
const saving = ref(false)

const visibleTokens = computed(() =>
  Object.entries(tokens.value).map(([k, v]: [string, any]) => ({
    key: k, label: v.label, type: v.type, default: v.default
  }))
)

async function loadThemes() {
  try {
    themes.value = kindScope.value ? await api.themes(kindScope.value) : await api.themes()
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  }
}

async function loadTokens(themeId?: string) {
  try {
    const r = await api.themeTokens(themeId)
    tokens.value = r.tokens
    cssText.value = r.css
    editing.value = {}
  } catch (e: any) {
    ElMessage.error(e?.message || '加载 token 失败')
  }
}

async function applyTheme(t: any) {
  active.value = t.key
  try {
    const r = await api.themeTokens(t.id)
    tokens.value = r.tokens
    cssText.value = r.css
    editing.value = { ...(t.tokens || {}) }
    ElMessage.success(`已载入主题：${t.name}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '应用失败')
  }
}

function previewCss() {
  const lines = [':root {']
  for (const [k, v] of Object.entries(editing.value)) {
    lines.push(`  --${k}: ${v};`)
  }
  lines.push('}')
  return lines.join('\n')
}

function colorOf(t: any, k: string) {
  return editing.value[k] || t.default
}

async function copyCss() {
  const text = previewCss()
  try {
    await window.navigator.clipboard.writeText(text)
    ElMessage.success('已复制当前覆盖值')
  } catch {
    ElMessage.warning('浏览器拒绝了剪贴板访问，请手动复制')
  }
}

onMounted(async () => {
  await Promise.all([loadThemes(), loadTokens()])
})
</script>

<template>
  <div class="ce-page">
    <el-alert type="info" :closable="false" show-icon style="margin-bottom: 14px">
      <template #title>
        主题即design token 集合。改token 不需要动组件默认样式 —— 一处改动，三类内容（邮件 / 表单 / 落地页）同步生效。
      </template>
    </el-alert>

    <!-- 主题列表 -->
    <div class="ce-card" style="margin-bottom: 14px">
      <div class="ce-card-head">
        <span class="ce-card-title">主题预设</span>
        <el-select v-model="kindScope" placeholder="全部适用类型" clearable size="small"
                   style="width: 160px" @change="loadThemes">
          <el-option label="全部" value="all" />
          <el-option label="邮件" value="email" />
          <el-option label="表单" value="form" />
          <el-option label="落地页" value="landing" />
        </el-select>
      </div>
      <div class="ce-card-body">
        <div class="ce-tpl-grid">
          <div
            v-for="t in themes" :key="t.id"
            class="ce-tpl-card"
            :style="active === t.key ? 'border-color: var(--ce-brand); box-shadow: 0 0 0 2px var(--ce-brand-soft)' : ''"
            @click="applyTheme(t)"
          >
            <div class="ce-theme-swatch"
                 :style="{ background: `linear-gradient(135deg, ${t.tokens?.brand || '#c8102e'} 0%, ${t.tokens?.secondary || '#0b1f3a'} 100%)` }" />
            <div class="ce-tpl-meta">
              <div class="ce-tpl-name">{{ t.name }}</div>
              <div class="ce-row" style="gap: 5px; margin-top: 6px">
                <span
                  v-for="c in ['brand', 'secondary', 'accent'].filter((k) => t.tokens?.[k])"
                  :key="c"
                  :style="{ width: 16, height: 16, borderRadius: '3px', background: t.tokens[c], border: '1px solid rgba(0,0,0,.08)' }"
                  :title="`${c}: ${t.tokens[c]}`"
                />
                <span class="ce-tag">{{ t.kind_scope }}</span>
                <span v-if="t.source_plugin" class="ce-tag" style="background:#f3e8ff;color:#7c3aed">
                  {{ t.source_plugin }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="ce-row" style="align-items: flex-start; gap: 14px">
      <!-- token 列表 -->
      <div class="ce-card" style="flex: 1; min-width: 0">
        <div class="ce-card-head">
          <span class="ce-card-title">设计 token（{{ visibleTokens.length }} 项）</span>
          <span class="ce-faint" style="font-size: 12px">
            {{ active ? `当前主题：${active}` : '当前：系统默认值' }}
          </span>
        </div>
        <div class="ce-card-body">
          <div v-for="t in visibleTokens" :key="t.key" class="ce-token-row">
            <div style="min-width: 0">
              <div class="ce-token-name">--{{ t.key }}</div>
              <div class="ce-token-label">{{ t.label }}</div>
              <div class="ce-faint" style="font-size: 11px">默认 {{ t.default }}</div>
            </div>
            <div class="ce-row" style="gap: 6px">
              <span
                v-if="t.type === 'color'"
                :style="{ width: 22, height: 22, borderRadius: '4px', border: '1px solid var(--ce-border)', background: colorOf(t, t.key) }"
              />
              <el-input
                :model-value="editing[t.key] ?? ''"
                :placeholder="t.default"
                size="small" style="width: 110px"
                @update:model-value="(v: string) => (editing[t.key] = v)"
              />
              <el-button v-if="editing[t.key]" link size="small"
                         @click="delete editing[t.key]">重置</el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- CSS 输出 -->
      <div class="ce-card" style="width: 380px; flex-shrink: 0">
        <div class="ce-card-head">
          <span class="ce-card-title">CSS 输出</span>
          <el-button link size="small" @click="copyCss">
            复制覆盖值
          </el-button>
        </div>
        <div class="ce-card-body">
          <div class="ce-code">{{ previewCss() }}</div>
          <div class="ce-section-title" style="margin-top: 14px">完整 token 表</div>
          <div class="ce-code" style="max-height: 300px">{{ cssText }}</div>
          <div class="ce-faint" style="font-size: 11.5px; margin-top: 10px; line-height: 1.6">
            导出的每个 bundle 都包含完整 <code>tokens.css</code>；
            交接给前端时替换该文件即可整站换肤，不需要改组件。
          </div>
        </div>
      </div>
    </div>
  </div>
</template>