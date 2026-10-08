<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useSessionStore } from '@/stores/session'
import api from '@/api'

const session = useSessionStore()
const route = useRoute()
const router = useRouter()

const navItems = computed(() =>
  router.getRoutes()
    .filter((r) => r.meta?.title && !r.meta?.hidden)
    .map((r) => ({ path: r.path, title: r.meta!.title as string, icon: r.meta!.icon as string }))
)

const llmOk = computed(() => session.llmReady())
const apiOk = computed(() => !!session.config || !!session.user)

async function doLogout() {
  session.logout()
  ElMessage.success('已退出，请重新登录')
}

onMounted(async () => {
  // 路由进入编辑器时，确保组件注册表已加载（插件启停后需要）
  if (!session.blocks.email.length) {
    await session.loadBlocks().catch(() => {})
  }
})
</script>

<template>
  <div class="ce-shell">
    <header class="ce-header">
      <div class="ce-logo">
        <span class="dot" />
        <span>Campaign Edit</span>
      </div>

      <nav class="ce-nav">
        <router-link
          v-for="it in navItems"
          :key="it.path"
          :to="it.path"
          :class="{ active: route.path === it.path || (it.path !== '/' && route.path.startsWith(it.path)) }"
        >
          <span>{{ it.title }}</span>
        </router-link>
      </nav>

      <div class="ce-header-right">
        <el-tooltip
          :content="llmOk
            ? `LLM 已接入：${session.config?.llm?.model}`
            : 'LLM 未配置，意图识别运行在规则通道（设置 LLM_API_KEY 可启用完整语义理解）'"
          placement="bottom"
        >
          <span class="ce-row" style="gap: 5px">
            <el-tag size="small" :type="llmOk ? 'success' : 'info'" effect="dark">
              {{ llmOk ? 'LLM' : '规则' }}
            </el-tag>
          </span>
        </el-tooltip>

        <el-tooltip :content="apiOk ? '后端已连接' : '后端未连接，请确认 API 已启动'" placement="bottom">
          <span style="width: 8px; height: 8px; border-radius: 50%"
                :style="{ background: apiOk ? '#4ade80' : '#f87171' }" />
        </el-tooltip>

        <el-dropdown v-if="session.user" trigger="click">
          <span class="ce-row" style="cursor: pointer; gap: 6px">
            <span class="ce-avatar">{{ (session.user.name || 'U').slice(0, 1) }}</span>
            <span>{{ session.user.name }}</span>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                {{ session.user.email }} · {{ session.user.role }}
              </el-dropdown-item>
              <el-dropdown-item divided @click="doLogout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button v-else size="small" type="primary" plain @click="router.push('/intent')">
          登录
        </el-button>
      </div>
    </header>

    <main class="ce-main" :class="{ 'ce-page-wide': route.name === 'editor' }">
      <router-view v-slot="{ Component }">
        <component :is="Component" />
      </router-view>
    </main>
  </div>
</template>