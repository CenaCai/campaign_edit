<script setup lang="ts">
/**
 * 插件中心：安装/启停第三方组件包、主题包、意图规则包与 MCP 插件。
 * 安全立场在 UI 上明示：远程安装默认关闭、渲染器白名单、软卸载。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const plugins = ref<any[]>([])
const scan = ref<any>({ items: [], plugin_dir: '', remote_install_enabled: false })
const mcpServers = ref<any[]>([])
const loading = ref(false)

const installPath = ref('')
const scaffoldDir = ref('D:/campaign-edit-plugins/my.plugin')
const scaffoldKey = ref('my.plugin')
const installing = ref(false)
const scaffoldResult = ref<any>(null)

const manifestJson = ref('')
const mcpProbe = ref<any>(null)
const mcpConfigJson = ref(JSON.stringify({
  name: 'my-mcp',
  transport: 'stdio',
  command: 'npx',
  args: ['-y', '@modelcontextprotocol/server-filesystem', '/tmp']
}, null, 2))

async function load() {
  loading.value = true
  try {
    const [p, s, m] = await Promise.all([
      api.plugins(),
      api.scanPlugins().catch(() => ({ items: [], plugin_dir: '', remote_install_enabled: false })),
      api.mcpServers().catch(() => [])
    ])
    plugins.value = p
    scan.value = s
    mcpServers.value = m
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function doInstall() {
  const p = installPath.value.trim()
  if (!p) {
    ElMessage.warning('请填写插件目录的绝对路径')
    return
  }
  installing.value = true
  try {
    const r = await api.installPlugin({ path: p, activate: true })
    const applied = r.applied || r
    ElMessage.success(
      `已安装 ${r.plugin?.name || ''}：组件 ${r.plan?.components?.length || 0}、主题 ${r.plan?.themes?.length || 0}、模板 ${r.plan?.templates?.length || 0}`
    )
    if (applied.errors?.length) {
      ElMessage.warning(`部分注册失败：${applied.errors.join('；')}`)
    }
    installPath.value = ''
    await load()
    await session.reloadBlocks()
  } catch (e: any) {
    ElMessage.error(e?.message || '安装失败')
  } finally {
    installing.value = false
  }
}

async function doScaffold() {
  try {
    const r = await api.scaffoldPlugin(scaffoldDir.value, scaffoldKey.value, scaffoldKey.value)
    scaffoldResult.value = r
    ElMessage.success('插件骨架已生成')
    load()
  } catch (e: any) {
    ElMessage.error(e?.message || '生成失败')
  }
}

async function doScanInstall(item: any) {
  try {
    await api.installPlugin({ path: item.path, activate: true })
    ElMessage.success(`已安装 ${item.key}`)
    load()
    session.reloadBlocks()
  } catch (e: any) {
    ElMessage.error(e?.message || '安装失败')
  }
}

async function toggle(p: any) {
  try {
    if (p.status === 'active') {
      await api.disablePlugin(p.key)
      ElMessage.success(`已停用 ${p.name}（软下线，可随时恢复）`)
    } else {
      await api.activatePlugin(p.key)
      ElMessage.success(`已启用 ${p.name}`)
    }
    await load()
    await session.reloadBlocks()
  } catch (e: any) {
    ElMessage.error(e?.message || '操作失败')
  }
}

async function uninstall(p: any) {
  try {
    await ElMessageBox.confirm(
      `卸载「${p.name}」？默认只做软卸载（停用并从运行时移除），不会删除插件目录。`,
      '卸载确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await api.uninstallPlugin(p.key, false)
    ElMessage.success('已软卸载')
    load()
    session.reloadBlocks()
  } catch (e: any) {
    ElMessage.error(e?.message || '卸载失败')
  }
}

function viewManifest(p: any) {
  manifestJson.value = JSON.stringify(p.manifest, null, 2)
}

async function probeMcp() {
  try {
    const cfg = JSON.parse(mcpConfigJson.value)
    mcpProbe.value = null
    const r = await api.mcpProbe(cfg)
    mcpProbe.value = r
    if (r.ok) ElMessage.success(`连接成功，发现 ${r.tool_count} 个工具`)
    else ElMessage.warning(r.error || '探测失败')
  } catch (e: any) {
    ElMessage.error(e?.message || '配置解析失败')
  }
}

onMounted(load)
</script>

<template>
  <div class="ce-page">
    <el-alert type="info" :closable="false" show-icon style="margin-bottom: 14px">
      <template #title>
        插件安全模型：manifest 只允许声明数据，<b>不允许在插件包里执行任意代码</b>；
        渲染器走宿主白名单；远程安装默认关闭；卸载一律软下线。
      </template>
    </el-alert>

    <div class="ce-row" style="align-items: flex-start; gap: 14px">
      <!-- 已安装 -->
      <div style="flex: 1; min-width: 0">
        <div class="ce-card">
          <div class="ce-card-head">
            <span class="ce-card-title">已安装插件（{{ plugins.length }}）</span>
            <el-button size="small" @click="load">刷新</el-button>
          </div>
          <div class="ce-card-body">
            <div v-for="p in plugins" :key="p.key" class="ce-plugin-card" style="margin-bottom: 10px">
              <div class="ce-row">
                <span style="font-weight: 650">{{ p.name }}</span>
                <span class="ce-plugin-status"
                      :class="`ce-st-${p.status}`">{{ p.status }}</span>
                <span class="ce-tag">{{ p.kind }}</span>
                <span class="ce-mono ce-faint">v{{ p.version }}</span>
                <div class="ce-spacer" />
                <el-button link size="small" @click="viewManifest(p)">manifest</el-button>
                <el-button link size="small" @click="toggle(p)">
                  {{ p.status === 'active' ? '停用' : '启用' }}
                </el-button>
                <el-button link size="small" type="danger" @click="uninstall(p)">卸载</el-button>
              </div>
              <div class="ce-muted" style="font-size: 12.5px; margin-top: 4px">{{ p.description }}</div>
              <div v-if="p.capabilities?.length" class="ce-tag-list" style="margin-top: 7px">
                <span v-for="c in p.capabilities" :key="c" class="ce-tag">{{ c }}</span>
              </div>
              <div v-if="p.registry?.applied?.errors?.length" class="ce-lint-item ce-lint-warn" style="margin-top: 7px">
                <div>{{ p.registry.applied.errors.join('；') }}</div>
              </div>
              <div class="ce-faint ce-mono" style="font-size: 11px; margin-top: 6px">
                {{ p.install_path }}
              </div>
            </div>
            <div v-if="!plugins.length" class="ce-faint" style="font-size: 12px">
              尚未安装插件。可用下方「生成插件骨架」创建第一个。
            </div>
          </div>
        </div>

        <!-- 扫描结果 -->
        <div class="ce-card" style="margin-top: 14px">
          <div class="ce-card-head">
            <span class="ce-card-title">扫描本地目录</span>
            <div class="ce-row">
              <el-tag size="small" :type="scan.remote_install_enabled ? 'warning' : 'info'" effect="plain">
                远程安装{{ scan.remote_install_enabled ? '已开启' : '已关闭' }}
              </el-tag>
              <el-button size="small" @click="load">重新扫描</el-button>
            </div>
          </div>
          <div class="ce-card-body">
            <div class="ce-mono ce-faint" style="font-size: 11.5px; margin-bottom: 8px">
              {{ scan.plugin_dir }}
            </div>
            <div v-for="item in scan.items" :key="item.path" class="ce-row"
                 style="gap: 10px; padding: 6px 0; border-bottom: 1px dashed var(--ce-border)">
              <span style="font-weight: 550">{{ item.name || item.key || '未知' }}</span>
              <span class="ce-tag">{{ item.version }}</span>
              <el-tag v-if="item.installed" size="small" type="success">已装 v{{ item.installed_version }}</el-tag>
              <el-tag v-else size="small" type="warning">未安装</el-tag>
              <el-tag v-if="item.outdated" size="small" type="danger">有新版本</el-tag>
              <div class="ce-spacer" />
              <el-button v-if="!item.installed" size="small" type="primary"
                         @click="doScanInstall(item)">安装</el-button>
            </div>
            <div v-if="!scan.items?.length" class="ce-faint" style="font-size: 12px">
              目录下没有 plugin.json
            </div>
          </div>
        </div>
      </div>

      <!-- 操作区 -->
      <div style="width: 400px; flex-shrink: 0">
        <div class="ce-card">
          <div class="ce-card-head"><span class="ce-card-title">安装本地插件</span></div>
          <div class="ce-card-body">
            <el-input
              v-model="installPath" placeholder="插件目录绝对路径，如 D:/plugins/my.plugin"
              size="small" style="margin-bottom: 10px"
            />
            <el-button type="primary" size="small" style="width: 100%"
                       :loading="installing" @click="doInstall">
              安装并启用
            </el-button>
            <div class="ce-faint" style="font-size: 11.5px; margin-top: 10px; line-height: 1.6">
              插件包就是一个包含 <code>plugin.json</code> 的目录（或其zip）。
              安装会先做 manifest 校验并展示将要注册的内容，确认后才写入运行时。
            </div>
          </div>
        </div>

        <div class="ce-card" style="margin-top: 14px">
          <div class="ce-card-head"><span class="ce-card-title">生成插件骨架</span></div>
          <div class="ce-card-body">
            <div class="ce-prop-row">
              <div class="ce-prop-label">目标目录</div>
              <el-input v-model="scaffoldDir" size="small" />
            </div>
            <div class="ce-prop-row">
              <div class="ce-prop-label">插件 Key（须带命名空间）</div>
              <el-input v-model="scaffoldKey" size="small" placeholder="acme.demo" />
            </div>
            <el-button size="small" style="width: 100%" @click="doScaffold">生成</el-button>
            <div v-if="scaffoldResult" class="ce-code" style="margin-top: 10px">
{{ scaffoldResult.directory }}
{{ scaffoldResult.manifest }}
            </div>
          </div>
        </div>

        <!-- MCP -->
        <div class="ce-card" style="margin-top: 14px">
          <div class="ce-card-head">
            <span class="ce-card-title">MCP server 探测</span>
            <el-tag size="small" effect="plain">{{ mcpServers.length }} 个已注册</el-tag>
          </div>
          <div class="ce-card-body">
            <el-input
              v-model="mcpConfigJson" type="textarea" :rows="7" resize="vertical"
              class="ce-mono" style="margin-bottom: 8px"
            />
            <el-button size="small" style="width: 100%" @click="probeMcp">探测连通性</el-button>
            <div v-if="mcpProbe" class="ce-code" style="margin-top: 10px; max-height: 200px">
{{ JSON.stringify(mcpProbe, null, 2) }}
            </div>
            <div class="ce-faint" style="font-size: 11.5px; margin-top: 10px; line-height: 1.6">
              支持 stdio（子进程 JSON-RPC）与 Streamable HTTP。
              MCP 让外部数据源（赛事库存、CRM、DAM）能直接接入内容生产链路。
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- manifest 查看 -->
    <el-dialog v-model="manifestJson" title="plugin.json" width="760px">
      <div class="ce-json-view">{{ manifestJson }}</div>
    </el-dialog>
  </div>
</template>