<script setup lang="ts">
/** 系统状态：配置、依赖连通性、架构说明。 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const health = ref<any>(null)
const deep = ref<any>(null)
const lexicon = ref<any>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const [h, d, l] = await Promise.all([
      api.health(),
      api.deepHealth().catch(() => null),
      api.lexicon().catch(() => null)
    ])
    health.value = h
    deep.value = d
    lexicon.value = l
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="ce-page">
    <div class="ce-row" style="align-items: flex-start; gap: 14px">
      <div style="flex: 1; min-width: 0">
        <!-- 健康 -->
        <div class="ce-card" style="margin-bottom: 14px">
          <div class="ce-card-head">
            <span class="ce-card-title">系统状态</span>
            <el-button size="small" @click="load">刷新</el-button>
          </div>
          <div class="ce-card-body">
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="服务状态">
                <el-tag :type="health?.status === 'ok' ? 'success' : 'danger'" size="small">
                  {{ health?.status || '未知' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="版本">
                <span class="ce-mono">{{ health?.version }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="数据库">
                <el-tag :type="health?.db ? 'success' : 'danger'" size="small">
                  {{ health?.db ? '正常' : '异常' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="注册组件数">
                <span class="ce-mono">{{ health?.blocks }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="内容总数">
                <span class="ce-mono">{{ health?.contents }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="运行环境">
                <span class="ce-mono">{{ session.config?.app?.env }}</span>
              </el-descriptions-item>
            </el-descriptions>

            <div v-if="deep" class="ce-section-title" style="margin-top: 16px">外部依赖</div>
            <div v-if="deep" class="ce-row" style="gap: 10px; flex-wrap: wrap">
              <el-tag :type="deep.llm?.ok ? 'success' : 'info'" effect="plain">
                LLM {{ deep.llm?.ok ? '已连通' : (deep.llm?.reason || '未配置') }}
                <span v-if="deep.llm?.model" class="ce-mono" style="margin-left: 4px">
                  {{ deep.llm.model }}
                </span>
              </el-tag>
              <el-tag :type="deep.mautic?.ok ? 'success' : 'info'" effect="plain">
                Mautic {{ deep.mautic?.ok ? `v${deep.mautic.version}` : (deep.mautic?.reason || '未配置') }}
              </el-tag>
            </div>
          </div>
        </div>

        <!-- 架构 -->
        <div class="ce-card">
          <div class="ce-card-head"><span class="ce-card-title">架构说明</span></div>
          <div class="ce-card-body">
            <p style="font-size: 13px; line-height: 1.75; margin-top: 0">
              三类内容（HTML 邮件 / 表单 / 活动站点）共用一份
              <b>Block Schema</b>。这是整个系统的关键取舍：
              意图识别、模板、编辑器、渲染、导出、Mautic 投递全都围绕这一份JSON，
              因此只有一条链路，而不是"邮件一套逻辑、表单一套逻辑、页面一套逻辑"。
            </p>

            <pre class="ce-code">运营一句话
   │
   ├─→ 意图识别（规则词典 ⊕ LLM，双通道 + 融合仲裁）
   │      └─→ 结构化计划：内容类型 / 场景 / 槽位 / 多资产依赖 / 必填追问
   │
   ├─→ 模板打分匹配（场景 + 标签 + 组件 + 语言 + 渠道 + 团队偏好）
   │      └─→ Block Schema 骨架
   │
   ├─→ 编辑器（组件面板由 props_schema 自动生成，无硬编码）
   │      └─→ 后端渲染 → iframe 预览（所见即所得，且与导出一致）
   │            └─→ 可投递性 lint（error 阻断导出）
   │
   └─→ 导出
          ├─ 单文件 HTML（直接投放）
          ├─ Bundle zip（含 tokens.css + schema.json，可回灌）
          ├─ Vite 脚手架（交给前端继续开发）
          └─ Mautic 投递（emails / forms / pages，软上下线）</pre>

            <div class="ce-section-title" style="margin-top: 16px">关键设计取舍</div>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="预览由后端渲染">
                前端不复刻渲染逻辑。否则编辑器所见与交付物必然漂移，
                而内容系统的价值恰恰在于交付物可直接使用。
              </el-descriptions-item>
              <el-descriptions-item label="版本只追加">
                回滚也是追加新版本，审计链完整，出问题能追到具体是谁改了什么。
              </el-descriptions-item>
              <el-descriptions-item label="下线不用删除">
                归档 = status=archived，Mautic 侧用 unpublish。资产永不丢失。
              </el-descriptions-item>
              <el-descriptions-item label="组件面板由 schema 驱动">
                props_schema 里有什么，右侧面板就渲染什么 ——
                插件新增组件无需改前端一行代码。
              </el-descriptions-item>
              <el-descriptions-item label="LLM 可降级">
                未配置 LLM 时意图识别跑规则通道，功能完整可用，
                只是长句与隐含需求需要人工确认。
              </el-descriptions-item>
              <el-descriptions-item label="插件不执行代码">
                manifest 只声明数据，渲染器走宿主白名单。
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </div>
      </div>

      <!-- 意图词典 -->
      <div style="width: 400px; flex-shrink: 0">
        <div class="ce-card">
          <div class="ce-card-head">
            <span class="ce-card-title">意图词典</span>
            <el-tag size="small" effect="plain" v-if="lexicon">
              权重规则 {{ lexicon.weights?.rule }} / LLM {{ lexicon.weights?.llm }}
            </el-tag>
          </div>
          <div class="ce-card-body">
            <template v-if="lexicon">
              <div
                v-for="(kws, kind) in lexicon.direct" :key="kind"
                style="margin-bottom: 12px"
              >
                <div class="ce-section-title">
                  {{ { email: '邮件信号', form: '表单信号', landing: '页面信号' }[kind] || kind }}
                </div>
                <div class="ce-tag-list">
                  <span v-for="[kw, w] in kws" :key="kw" class="ce-tag">
                    {{ kw }} <span class="ce-faint">×{{ w }}</span>
                  </span>
                </div>
              </div>

              <div class="ce-section-title">营销场景</div>
              <div class="ce-tag-list">
                <span v-for="(words, s) in lexicon.scenarios" :key="s" class="ce-tag"
                      :title="words.join(' / ')">
                  {{ s }} <span class="ce-faint">{{ words.length }}</span>
                </span>
              </div>

              <div class="ce-section-title" style="margin-top: 14px">否定词（避免误判）</div>
              <div class="ce-tag-list">
                <span v-for="n in lexicon.negations" :key="n" class="ce-tag">{{ n }}</span>
              </div>

              <div class="ce-section-title" style="margin-top: 14px">阈值</div>
              <div class="ce-code" style="max-height: 180px">{{ JSON.stringify(lexicon.weights, null, 2) }}</div>
            </template>
            <div v-else class="ce-faint" style="font-size: 12px">加载中…</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>