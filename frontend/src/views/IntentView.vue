<script setup lang="ts">
/**
 * 意图控制台 —— 系统的入口。
 *
 * 运营在这里用一句话描述需求，系统给出：
 *   内容类型 + 置信度 + 判断依据（可解释）+ 模板推荐 + 组件建议 + 必填追问
 * 确认后可一键落地成内容（含依赖顺序：表单 → 落地页 → 邮件）。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '@/api'
import { useSessionStore } from '@/stores/session'
import type { IntentResult } from '@/types'
import { KIND_LABEL } from '@/blocks/schema'

const router = useRouter()
const session = useSessionStore()

const text = ref('')
const useLlm = ref(true)
const loading = ref(false)
const result = ref<IntentResult | null>(null)
const creating = ref(false)
const history = ref<any[]>([])

const EXAMPLES = [
  '给会员发一封促销邮件，推20% 折扣券，主推新赛季套票',
  '做个欧洲杯活动落地页，要有倒计时、票档卡片和留资表单',
  '做一个赛事报名表，分组收集姓名邮箱手机号和票种',
  '7月15日比赛改期了，发个提醒邮件，同时更新活动页',
  'CUP2028 报名页 + 报名表单 + 开票提醒邮件，一套都要',
  '做一个 90 天未活跃用户的挽回邮件，带专属优惠'
]

const kindCounts = computed(() => {
  const m: Record<string, number> = { email: 0, form: 0, landing: 0 }
  for (const p of result.value?.plan || []) m[p.kind] = (m[p.kind] || 0) + 1
  return m
})

const topScore = computed(() => {
  const c = result.value?.candidates || []
  return c.length ? c[0].score : 0
})

function pct(v: number) {
  return Math.max(0, Math.min(100, Math.round((v / 10) * 100)))
}

function confType(c: number) {
  if (c >= 0.75) return 'success'
  if (c >= 0.5) return 'warning'
  return 'danger'
}

async function run() {
  if (!text.value.trim()) return
  loading.value = true
  result.value = null
  try {
    result.value = await api.recognize(text.value.trim(), { use_llm: useLlm.value })
  } catch (e: any) {
    ElMessage.error(e?.message || '识别失败')
  } finally {
    loading.value = false
  }
}

async function createAll() {
  if (!result.value) return
  creating.value = true
  try {
    const r = await api.recognize(text.value.trim(), {
      use_llm: useLlm.value,
      auto_create: true
    })
    result.value = r
    if (r.created_contents?.length) {
      ElMessage.success(`已创建 ${r.created_contents.length} 个内容`)
      await loadHistory()
      r.created_contents.forEach((c) => {
        window.setTimeout(() => {
          if (r.created_contents.length === 1) router.push(`/contents/${c.id}`)
        }, 600)
      })
    } else if (r.explanation?.auto_create_blocked) {
      ElMessage.warning(r.explanation.auto_create_blocked)
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '创建失败')
  } finally {
    creating.value = false
  }
}

async function loadHistory() {
  try {
    const h = await api.intentHistory(12)
    history.value = h.items || []
  } catch {
    history.value = []
  }
}

loadHistory()

function useExample(s: string) {
  text.value = s
  run()
}

function openContent(id: string) {
  router.push(`/contents/${id}`)
}
</script>

<template>
  <div class="ce-page">
    <!-- ============ 输入区 ============ -->
    <div class="ce-card ce-intent-hero">
      <h1 class="ce-intent-title">意图控制台</h1>
      <p class="ce-intent-sub">
        用一句运营话描述需求，系统自动判断内容类型（邮件 / 表单 / 落地页）、
        匹配模板与组件、抽取出关键信息，并可一键落地为可编辑内容。
      </p>

      <el-input
        v-model="text"
        type="textarea"
        :rows="3"
        resize="none"
        maxlength="500"
        show-word-limit
        placeholder="例如：做个欧洲杯活动落地页，要有倒计时和购票按钮，再配一个留资表单收集邮箱"
        @keydown.ctrl.enter="run"
        @keydown.meta.enter="run"
      />

      <div class="ce-row" style="margin-top: 12px; flex-wrap: wrap">
        <el-button type="primary" :loading="loading" @click="run">
          识别意图
          <span style="opacity: 0.7; font-size: 11px; margin-left: 4px">Ctrl+Enter</span>
        </el-button>

        <el-tooltip :content="session.llmReady()
          ? '已接入 LLM：语义理解 + 规则校验双通道'
          : 'LLM 未配置，仅用规则通道（长句与隐含需求可能误判）'"
          placement="top">
          <el-switch v-model="useLlm" :disabled="!session.llmReady()" active-text="启用 LLM 通道" />
        </el-tooltip>

        <div class="ce-spacer" />
        <span class="ce-faint" style="font-size: 12px">
          内容类型由系统判断；识别结果仅创建草稿，不会自动发布
        </span>
      </div>

      <div style="margin-top: 14px">
        <div class="ce-section-title">试试这些真实运营话术</div>
        <div>
          <span
            v-for="ex in EXAMPLES"
            :key="ex"
            class="ce-example-chip"
            @click="useExample(ex)"
          >
            {{ ex }}
          </span>
        </div>
      </div>
    </div>

    <!-- ============ 识别结果 ============ -->
    <div v-if="result" class="ce-row" style="align-items: flex-start; gap: 16px; margin-top: 16px">
      <!-- 左：判断结论 -->
      <div style="flex: 1; min-width: 0">
        <div class="ce-card">
          <div class="ce-card-head">
            <span class="ce-card-title">识别结论</span>
            <div class="ce-row">
              <el-tag size="small" :type="result.degraded ? 'info' : 'success'" effect="plain">
                引擎：{{ { rule: '规则', llm: 'LLM', hybrid: '规则+LLM' }[result.engine] || result.engine }}
              </el-tag>
              <el-tag size="small" effect="plain">{{ result.latency_ms }} ms</el-tag>
            </div>
          </div>

          <div class="ce-card-body">
            <!-- 类型 + 置信度 -->
            <div class="ce-row" style="gap: 18px; flex-wrap: wrap">
              <div>
                <div class="ce-faint" style="font-size: 11px">主内容类型</div>
                <div style="font-size: 19px; font-weight: 700">
                  {{ result.content_type ? KIND_LABEL[result.content_type] : '无法判断' }}
                </div>
              </div>
              <div>
                <div class="ce-faint" style="font-size: 11px">置信度</div>
                <div class="ce-row" style="gap: 8px">
                  <el-progress
                    type="dashboard" :width="58" :stroke-width="7"
                    :percentage="Math.round(result.confidence * 100)"
                    :color="result.confidence >= 0.75 ? '#12a150' : result.confidence >= 0.5 ? '#f59e0b' : '#e5484d'"
                  />
                </div>
              </div>
              <div>
                <div class="ce-faint" style="font-size: 11px">营销场景</div>
                <el-tag effect="dark" type="warning">{{ result.scenario }}</el-tag>
              </div>
              <div v-if="kindCounts.email + kindCounts.form + kindCounts.landing > 1">
                <div class="ce-faint" style="font-size: 11px">资产组合</div>
                <div class="ce-row" style="gap: 5px">
                  <el-tag v-if="kindCounts.landing" size="small" type="danger">落地页 ×{{ kindCounts.landing }}</el-tag>
                  <el-tag v-if="kindCounts.form" size="small" type="warning">表单 ×{{ kindCounts.form }}</el-tag>
                  <el-tag v-if="kindCounts.email" size="small">邮件 ×{{ kindCounts.email }}</el-tag>
                </div>
              </div>
            </div>

            <!-- 判断依据 -->
            <div v-if="result.explanation?.reasoning || result.explanation?.note" style="margin-top: 12px">
              <div class="ce-section-title">判断依据</div>
              <div v-if="result.explanation?.reasoning" style="font-size: 13px; margin-bottom: 6px">
                {{ result.explanation.reasoning }}
              </div>
              <el-alert
                v-if="result.explanation?.note"
                :type="result.explanation.agreed ? 'info' : 'warning'"
                :closable="false" show-icon
                :title="result.explanation.note"
              />
            </div>

            <!-- 类型得分对比 -->
            <div style="margin-top: 14px">
              <div class="ce-section-title">三通道加权得分</div>
              <div v-for="c in result.candidates" :key="c.kind" class="ce-row" style="gap: 10px; margin-bottom: 5px">
                <span style="width: 110px; font-size: 12px">{{ KIND_LABEL[c.kind] || c.kind }}</span>
                <div class="ce-score-bar" style="flex: 1">
                  <i :style="{ width: pct(c.score) + '%', background: c.kind === result.content_type ? '#c8102e' : '#94a3b8' }" />
                </div>
                <span class="ce-mono ce-faint" style="width: 46px; text-align: right">{{ c.score.toFixed(2) }}</span>
              </div>
            </div>

            <!-- 冲突与风险 -->
            <div v-if="result.conflicts?.length" style="margin-top: 12px">
              <div class="ce-section-title">需要注意</div>
              <el-alert
                v-for="(c, i) in result.conflicts" :key="i"
                type="warning" :closable="false" show-icon style="margin-bottom: 5px"
                :title="c"
              />
            </div>

            <div class="ce-row" style="margin-top: 14px; gap: 8px; flex-wrap: wrap">
              <el-button
                type="primary"
                :loading="creating"
                :disabled="!result.content_type || result.needs_confirm"
                @click="createAll"
              >
                一键创建内容草稿
              </el-button>
              <span v-if="result.needs_confirm" class="ce-faint" style="font-size: 12px">
                存在分歧或必填项缺失，建议先确认下方追问再创建
              </span>
            </div>
          </div>
        </div>

        <!-- 追问 -->
        <div
          v-for="(p, pi) in result.plan"
          :key="pi"
          class="ce-card"
          style="margin-top: 14px"
        >
          <div class="ce-card-head">
            <div class="ce-row">
              <el-tag :type="p.kind === 'landing' ? 'danger' : p.kind === 'form' ? 'warning' : ''" size="small">
                {{ KIND_LABEL[p.kind] }}
              </el-tag>
              <el-tag v-if="p.role === 'primary'" size="small" type="success">主资产</el-tag>
              <el-tag v-else size="small" type="info">配套资产</el-tag>
              <span class="ce-faint" style="font-size: 12px">{{ p.purpose }}</span>
            </div>
            <el-tag size="small" effect="plain">场景 {{ p.scenario }}</el-tag>
          </div>

          <div class="ce-card-body">
            <!-- 模板推荐 -->
            <div>
              <div class="ce-section-title">模板推荐</div>
              <div
                v-for="t in p.template_candidates.slice(0, 3)"
                :key="t.template_id"
                class="ce-row"
                style="gap: 10px; padding: 6px 0; border-bottom: 1px dashed var(--ce-border)"
              >
                <span style="flex: 1; font-size: 13px">{{ t.name }}</span>
                <el-tag size="small" effect="plain">{{ t.scenario }}</el-tag>
                <div class="ce-score-bar" style="width: 70px">
                  <i :style="{ width: Math.round(t.score * 100) + '%' }" />
                </div>
                <span class="ce-mono ce-faint">{{ t.score.toFixed(2) }}</span>
                <el-tag v-if="t.template_id === p.template_id" size="small" type="success">选中</el-tag>
              </div>
              <div v-if="!p.template_candidates.length" class="ce-faint" style="font-size: 12px">
                该类型暂无可用模板
              </div>
            </div>

            <!-- 组件建议 -->
            <div v-if="p.component_hints?.length" style="margin-top: 12px">
              <div class="ce-section-title">建议组件</div>
              <div class="ce-tag-list">
                <span v-for="h in p.component_hints" :key="h" class="ce-tag">{{ h }}</span>
              </div>
            </div>

            <!-- 槽位 -->
            <div v-if="Object.keys(p.slots || {}).length" style="margin-top: 12px">
              <div class="ce-section-title">已抽取的关键信息</div>
              <div class="ce-tag-list">
                <span v-for="(v, k) in p.slots" :key="k" class="ce-tag">
                  <b>{{ k }}</b>: {{ typeof v === 'object' ? JSON.stringify(v) : v }}
                </span>
              </div>
            </div>

            <!-- 追问 -->
            <div v-if="p.followups?.length" style="margin-top: 12px">
              <div class="ce-section-title">需要补充</div>
              <el-alert
                v-for="(q, qi) in p.followups" :key="qi"
                :type="q.required ? 'warning' : 'info'"
                :closable="false" show-icon style="margin-bottom: 5px"
                :title="q.question"
              >
                <template v-if="q.options?.length" #default>
                  <div class="ce-tag-list" style="margin-top: 4px">
                    <span v-for="o in q.options" :key="o" class="ce-tag">{{ o }}</span>
                  </div>
                </template>
              </el-alert>
            </div>

            <!-- 依赖 -->
            <div v-if="p.depends_on?.length" style="margin-top: 10px">
              <span class="ce-faint" style="font-size: 12px">依赖：{{ p.depends_on.join('、') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右：证据 + 历史 -->
      <div style="width: 340px; flex-shrink: 0">
        <div class="ce-card">
          <div class="ce-card-head">
            <span class="ce-card-title">规则命中证据</span>
            <el-tag size="small" effect="plain">{{ result.rule_evidence.length }} 条</el-tag>
          </div>
          <div class="ce-card-body tight">
            <div class="ce-evidence">
              <div v-for="(e, i) in result.rule_evidence" :key="i">
                <span class="hit">[{{ e.layer }}]</span>
                <span class="kw">{{ e.keyword }}</span>
                → {{ KIND_LABEL[e.kind] || e.kind }}
                <span class="ce-faint">×{{ e.weight }}</span>
              </div>
              <div v-if="!result.rule_evidence.length" class="ce-faint">
                无规则命中（可能完全依赖 LLM 理解）
              </div>
            </div>
            <div v-if="result.explanation?.scenarios?.length" style="margin-top: 10px">
              <div class="ce-section-title">命中场景</div>
              <div class="ce-tag-list">
                <span v-for="s in result.explanation.scenarios" :key="s" class="ce-tag">{{ s }}</span>
              </div>
            </div>
            <div v-if="result.explanation?.channels?.length" style="margin-top: 10px">
              <div class="ce-section-title">命中渠道</div>
              <div class="ce-tag-list">
                <span v-for="s in result.explanation.channels" :key="s" class="ce-tag">{{ s }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="ce-card" style="margin-top: 14px">
          <div class="ce-card-head">
            <span class="ce-card-title">识别历史</span>
            <el-button link size="small" @click="loadHistory">刷新</el-button>
          </div>
          <div class="ce-card-body tight">
            <div
              v-for="h in history" :key="h.id"
              style="padding: 7px 0; border-bottom: 1px dashed var(--ce-border); cursor: pointer"
              @click="text = h.raw_text"
            >
              <div class="ce-row" style="gap: 6px">
                <el-tag size="small" effect="plain">{{ h.engine }}</el-tag>
                <el-tag
                  size="small"
                  :type="h.accepted ? 'success' : h.status === 'need_confirm' ? 'warning' : 'info'"
                >
                  {{ h.accepted ? '已落地' : h.status === 'need_confirm' ? '待确认' : '仅识别' }}
                </el-tag>
                <span class="ce-spacer" />
                <span class="ce-faint ce-mono">{{ h.latency_ms }}ms</span>
              </div>
              <div style="font-size: 12.5px; margin-top: 3px; line-height: 1.4">{{ h.raw_text }}</div>
              <div v-if="h.result_content_ids?.length" class="ce-row" style="gap: 4px; margin-top: 4px">
                <span
                  v-for="cid in h.result_content_ids" :key="cid"
                  class="ce-tag" style="cursor: pointer"
                  @click.stop="openContent(cid)"
                >打开内容</span>
              </div>
            </div>
            <div v-if="!history.length" class="ce-faint" style="font-size: 12px">暂无历史</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>