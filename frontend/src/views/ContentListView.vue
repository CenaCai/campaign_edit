<script setup lang="ts">
/** 内容库：按类型/状态/项目筛选，支持从模板新建、复制、归档。 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'
import type { ContentItem } from '@/types'
import { KIND_LABEL, STATUS_LABEL } from '@/blocks/schema'

const router = useRouter()
const items = ref<ContentItem[]>([])
const loading = ref(false)
const stats = ref<any>({})
const projects = ref<any[]>([])

const kind = ref<string>('')
const status = ref<string>('')
const projectId = ref<string>('')
const q = ref('')

const createVisible = ref(false)
const createKind = ref<'email' | 'form' | 'landing'>('landing')
const templates = ref<any[]>([])
const chosenTpl = ref<string>('')
const newName = ref('')
const newLocale = ref('zh-CN')
const creating = ref(false)

const statusTag: Record<string, any> = {
  draft: 'info', in_review: 'warning', approved: 'primary',
  published: 'success', archived: 'info'
}

async function load() {
  loading.value = true
  try {
    items.value = await api.contents({
      kind: kind.value, status: status.value,
      project_id: projectId.value, q: q.value, limit: 100
    })
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadMeta() {
  try {
    const [s, p] = await Promise.all([api.contentStats(), api.projects()])
    stats.value = s
    projects.value = p
  } catch { /* ignore */ }
}

async function openCreate(k?: string) {
  createKind.value = (k as any) || 'landing'
  newName.value = ''
  chosenTpl.value = ''
  createVisible.value = true
  await loadTemplates()
}

async function loadTemplates() {
  try {
    templates.value = await api.templates(createKind.value)
    chosenTpl.value = templates.value[0]?.id || ''
  } catch { templates.value = [] }
}

async function doCreate() {
  if (!chosenTpl.value) return
  if (!newName.value.trim()) {
    ElMessage.warning('请填写内容名称')
    return
  }
  creating.value = true
  try {
    const c = await api.instantiateTemplate(chosenTpl.value, newName.value.trim(), newLocale.value)
    ElMessage.success(`已创建：${c.key}`)
    createVisible.value = false
    router.push(`/contents/${c.id}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '创建失败')
  } finally {
    creating.value = false
  }
}

async function duplicate(c: ContentItem) {
  try {
    const r = await api.duplicateContent(c.id)
    ElMessage.success(`已复制为 ${r.key}`)
    load()
  } catch (e: any) {
    ElMessage.error(e?.message || '复制失败')
  }
}

async function archive(c: ContentItem) {
  try {
    await ElMessageBox.confirm(
      `确认把「${c.name}」归档？归档是软下线，内容与版本全部保留，可随时恢复。`,
      '归档确认',
      { type: 'warning', confirmButtonText: '归档', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await api.review(c.id, 'archived', '内容库手动归档')
    ElMessage.success('已归档（内容与版本均保留）')
    load()
  } catch (e: any) {
    ElMessage.error(e?.message || '归档失败')
  }
}

function fmtTime(s: string) {
  if (!s) return ''
  const d = new Date(s)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

onMounted(async () => {
  await Promise.all([load(), loadMeta()])
})
</script>

<template>
  <div class="ce-page">
    <!-- 概览 -->
    <div class="ce-row" style="gap: 12px; margin-bottom: 16px; flex-wrap: wrap">
      <div class="ce-card" style="padding: 12px 16px; min-width: 150px">
        <div class="ce-faint" style="font-size: 11px">内容总数</div>
        <div style="font-size: 22px; font-weight: 700">
          {{ (stats.contents_by_kind?.email || 0) + (stats.contents_by_kind?.form || 0) + (stats.contents_by_kind?.landing || 0) }}
        </div>
        <div class="ce-row" style="gap: 8px; font-size: 11px; margin-top: 3px">
          <span>邮件 {{ stats.contents_by_kind?.email || 0 }}</span>
          <span>表单 {{ stats.contents_by_kind?.form || 0 }}</span>
          <span>页面 {{ stats.contents_by_kind?.landing || 0 }}</span>
        </div>
      </div>
      <div class="ce-card" style="padding: 12px 16px; min-width: 150px">
        <div class="ce-faint" style="font-size: 11px">已发布</div>
        <div style="font-size: 22px; font-weight: 700; color: var(--ce-ok)">
          {{ stats.contents_by_status?.published || 0 }}
        </div>
        <div class="ce-row" style="gap: 8px; font-size: 11px; margin-top: 3px">
          <span>审核中 {{ stats.contents_by_status?.in_review || 0 }}</span>
          <span>草稿 {{ stats.contents_by_status?.draft || 0 }}</span>
        </div>
      </div>
      <div class="ce-card" style="padding: 12px 16px; min-width: 150px">
        <div class="ce-faint" style="font-size: 11px">意图识别次数</div>
        <div style="font-size: 22px; font-weight: 700">{{ stats.intents || 0 }}</div>
        <div style="font-size: 11px; margin-top: 3px" class="ce-muted">来自意图控制台</div>
      </div>
      <div class="ce-spacer" />
      <div class="ce-row" style="gap: 8px">
        <el-button @click="openCreate('email')">新建邮件</el-button>
        <el-button @click="openCreate('form')">新建表单</el-button>
        <el-button type="primary" @click="openCreate('landing')">新建落地页</el-button>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="ce-card" style="margin-bottom: 14px">
      <div class="ce-card-body tight">
        <div class="ce-row" style="gap: 10px; flex-wrap: wrap">
          <el-select v-model="kind" placeholder="全部类型" clearable style="width: 150px" @change="load">
            <el-option label="HTML 邮件" value="email" />
            <el-option label="表单" value="form" />
            <el-option label="着陆页 / 活动站点" value="landing" />
          </el-select>
          <el-select v-model="status" placeholder="全部状态" clearable style="width: 140px" @change="load">
            <el-option v-for="(label, k) in STATUS_LABEL" :key="k" :label="label" :value="k" />
          </el-select>
          <el-select v-model="projectId" placeholder="全部项目" clearable style="width: 150px" @change="load">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <el-input v-model="q" placeholder="搜索名称或 Key" clearable style="width: 200px" @keyup.enter="load" />
          <el-button @click="load">查询</el-button>
          <el-button link @click="kind = ''; status = ''; projectId = ''; q = ''; load()">重置</el-button>
          <div class="ce-spacer" />
          <span class="ce-faint" style="font-size: 12px">共 {{ items.length }} 条</span>
        </div>
      </div>
    </div>

    <!-- 列表 -->
    <div class="ce-card">
      <el-table :data="items" v-loading="loading" style="width: 100%" @row-click="(r: any) => router.push(`/contents/${r.id}`)">
        <el-table-column label="Key" width="200">
          <template #default="{ row }">
            <span class="ce-mono">{{ row.key }}</span>
          </template>
        </el-table-column>
        <el-table-column label="名称" min-width="220">
          <template #default="{ row }">
            <div style="font-weight: 550">{{ row.name }}</div>
            <div v-if="row.meta?.note" class="ce-faint" style="font-size: 11.5px">{{ row.meta.note }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="150">
          <template #default="{ row }">
            <el-tag size="small" :type="row.kind === 'landing' ? 'danger' : row.kind === 'form' ? 'warning' : ''">
              {{ KIND_LABEL[row.kind] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTag[row.status]">{{ STATUS_LABEL[row.status] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="版本" width="80">
          <template #default="{ row }">
            <span class="ce-mono">v{{ row.current_version }}</span>
          </template>
        </el-table-column>
        <el-table-column label="语言" width="80">
          <template #default="{ row }">
            <span class="ce-mono ce-faint">{{ row.locale }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Mautic" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.mautic_asset_id" size="small" type="success">#{{ row.mautic_asset_id }}</el-tag>
            <span v-else class="ce-faint">—</span>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="110">
          <template #default="{ row }">
            <span class="ce-faint" style="font-size: 12px">{{ fmtTime(row.updated_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button link size="small" @click.stop="router.push(`/contents/${row.id}`)">编辑</el-button>
            <el-button link size="small" @click.stop="duplicate(row)">复制</el-button>
            <el-button link size="small" type="warning" @click.stop="archive(row)">归档</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="!loading && !items.length" style="padding: 40px; text-align: center" class="ce-faint">
        暂无内容。用上方按钮从模板创建，或到「意图控制台」用一句话生成。
      </div>
    </div>

    <!-- 新建对话框 -->
    <el-dialog v-model="createVisible" title="从模板新建内容" width="720px">
      <el-form label-width="82px">
        <el-form-item label="内容类型">
          <el-radio-group v-model="createKind" @change="loadTemplates">
            <el-radio-button value="email">HTML 邮件</el-radio-button>
            <el-radio-button value="form">表单</el-radio-button>
            <el-radio-button value="landing">着陆页</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="内容名称">
          <el-input v-model="newName" placeholder="例如：EURO 2028 会员促销邮件" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="语言">
          <el-select v-model="newLocale" style="width: 180px">
            <el-option label="简体中文" value="zh-CN" />
            <el-option label="English (UK)" value="en-GB" />
            <el-option label="English (US)" value="en-US" />
          </el-select>
        </el-form-item>
        <el-form-item label="选择模板">
          <div style="width: 100%">
            <el-radio-group v-model="chosenTpl" style="width: 100%">
              <div
                v-for="t in templates" :key="t.id"
                class="ce-row"
                style="gap: 10px; padding: 8px 10px; border: 1px solid var(--ce-border); border-radius: 6px; margin-bottom: 6px; cursor: pointer"
                :style="chosenTpl === t.id ? 'border-color: var(--ce-brand); background: var(--ce-brand-soft)' : ''"
                @click="chosenTpl = t.id"
              >
                <el-radio :value="t.id" style="margin-right: 0">
                  <span style="font-weight: 600">{{ t.name }}</span>
                </el-radio>
                <span class="ce-faint" style="font-size: 11.5px; flex: 1">{{ t.description }}</span>
                <el-tag size="small" effect="plain">{{ t.scenario }}</el-tag>
              </div>
            </el-radio-group>
            <div v-if="!templates.length" class="ce-faint">该类型暂无可用模板</div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="doCreate">创建并进入编辑器</el-button>
      </template>
    </el-dialog>
  </div>
</template>