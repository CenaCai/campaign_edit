<script setup lang="ts">
/** 模板中心：按类型/场景筛选，实时 iframe 预览，一键实例化。 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '@/api'
import { KIND_LABEL } from '@/blocks/schema'

const router = useRouter()
const kind = ref<string>('all')
const scenario = ref<string>('')
const templates = ref<any[]>([])
const scenarios = ref<string[]>([])
const loading = ref(false)
const previewCache = ref<Record<string, string>>({})
const selected = ref<any>(null)
const instantiating = ref(false)
const newName = ref('')

const filtered = computed(() => {
  let r = templates.value
  if (kind.value !== 'all') r = r.filter((t) => t.kind === kind.value)
  if (scenario.value) r = r.filter((t) => t.scenario === scenario.value)
  return r
})

const grouped = computed(() => {
  const g: Record<string, any[]> = {}
  for (const t of filtered.value) {
    const k = `${KIND_LABEL[t.kind] || t.kind} / ${t.scenario}`
    ;(g[k] = g[k] || []).push(t)
  }
  return g
})

async function load() {
  loading.value = true
  try {
    templates.value = kind.value === 'all' ? await api.templates() : await api.templates(kind.value)
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadPreview(t: any) {
  selected.value = t
  newName.value = `${t.name} 副本`
  if (previewCache.value[t.id]) return
  try {
    const r = await api.templatePreview(t.id)
    previewCache.value[t.id] = r.html
  } catch {
    previewCache.value[t.id] = '<p>预览失败</p>'
  }
}

async function instantiate() {
  if (!selected.value) return
  if (!newName.value.trim()) {
    ElMessage.warning('请填写内容名称')
    return
  }
  instantiating.value = true
  try {
    const c = await api.instantiateTemplate(selected.value.id, newName.value.trim())
    ElMessage.success(`已创建 ${c.key}`)
    router.push(`/contents/${c.id}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '创建失败')
  } finally {
    instantiating.value = false
  }
}

onMounted(async () => {
  await Promise.all([load(), api.scenarios().then((r) => (scenarios.value = r.scenarios)).catch(() => {})])
})
</script>

<template>
  <div class="ce-page">
    <div class="ce-card" style="margin-bottom: 14px">
      <div class="ce-card-body tight">
        <div class="ce-row" style="gap: 10px; flex-wrap: wrap">
          <el-radio-group v-model="kind" @change="load">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="email">HTML 邮件</el-radio-button>
            <el-radio-button value="form">表单</el-radio-button>
            <el-radio-button value="landing">着陆页</el-radio-button>
          </el-radio-group>
          <el-select v-model="scenario" placeholder="全部场景" clearable style="width: 160px" @change="load">
            <el-option v-for="s in scenarios" :key="s" :label="s" :value="s" />
          </el-select>
          <div class="ce-spacer" />
          <span class="ce-faint" style="font-size: 12px">
            共 {{ filtered.length }} 套模板 · 模板的标签同时是意图匹配的检索入口
          </span>
        </div>
      </div>
    </div>

    <div v-for="(list, group) in grouped" :key="group" style="margin-bottom: 20px">
      <div class="ce-section-title">{{ group }}</div>
      <div class="ce-tpl-grid">
        <div
          v-for="t in list" :key="t.id"
          class="ce-tpl-card"
          @click="loadPreview(t)"
        >
          <div class="ce-tpl-thumb">
            <iframe
              v-if="previewCache[t.id]"
              :srcdoc="previewCache[t.id]"
              sandbox=""
              style="width: 380px; height: 260px; transform: scale(0.68); transform-origin: top left"
            />
            <div v-else class="ce-row" style="justify-content: center; height: 100%; color: var(--ce-text-faint); font-size: 12px">
              点击预览
            </div>
          </div>
          <div class="ce-tpl-meta">
            <div class="ce-tpl-name">{{ t.name }}</div>
            <div class="ce-tpl-desc">{{ t.description }}</div>
            <div class="ce-tag-list">
              <span v-for="tag in (t.tags || []).slice(0, 6)" :key="tag" class="ce-tag">{{ tag }}</span>
              <span v-if="t.source_plugin" class="ce-tag" style="background: #f3e8ff; color: #7c3aed">
                {{ t.source_plugin }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="!loading && !filtered.length" class="ce-faint" style="text-align: center; padding: 40px">
      没有匹配的模板
    </div>

    <!-- 预览与创建 -->
    <el-dialog
      :model-value="!!selected" title="模板预览与实例化" width="1000px"
      @update:model-value="(v: boolean) => { if (!v) selected = null }"
    >
      <div v-if="selected" class="ce-row" style="align-items: flex-start; gap: 16px">
        <div
          class="ce-frame"
          style="flex: 1; min-width: 0; height: 560px; overflow: auto"
        >
          <iframe
            :srcdoc="previewCache[selected.id] || ''"
            sandbox=""
            style="width: 100%; height: 100%; border: 0"
          />
        </div>
        <div style="width: 280px; flex-shrink: 0">
          <div class="ce-section-title">{{ selected.name }}</div>
          <p style="font-size: 12.5px; line-height: 1.6; color: var(--ce-text-muted)">
            {{ selected.description }}
          </p>
          <div class="ce-section-title" style="margin-top: 12px">适用场景</div>
          <div class="ce-tag-list">
            <span class="ce-tag">{{ selected.scenario }}</span>
            <span v-for="t in (selected.tags || [])" :key="t" class="ce-tag">{{ t }}</span>
          </div>
          <div class="ce-prop-row" style="margin-top: 16px">
            <div class="ce-prop-label">新内容名称</div>
            <el-input v-model="newName" size="small" maxlength="200" />
          </div>
          <el-button
            type="primary" size="small" style="width: 100%"
            :loading="instantiating" @click="instantiate"
          >
            用此模板创建内容
          </el-button>
          <div class="ce-faint" style="font-size: 11.5px; margin-top: 8px; line-height: 1.5">
            实例化会重新生成节点 id，因此多份内容不会共享锚点，
            评论、埋点与 A/B 实验互不干扰。
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>