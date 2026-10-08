import { createRouter, createWebHashHistory } from 'vue-router'

/**
 * 用 hash 路由：导出的静态文件可以直接双击打开，不受服务端 rewrite 配置限制。
 */
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/intent' },
    {
      path: '/intent',
      name: 'intent',
      component: () => import('@/views/IntentView.vue'),
      meta: { title: '意图控制台', icon: 'MagicStick' }
    },
    {
      path: '/contents',
      name: 'contents',
      component: () => import('@/views/ContentListView.vue'),
      meta: { title: '内容库', icon: 'Files' }
    },
    {
      path: '/contents/:id',
      name: 'editor',
      component: () => import('@/views/EditorView.vue'),
      meta: { title: '编辑器', hidden: true }
    },
    {
      path: '/templates',
      name: 'templates',
      component: () => import('@/views/TemplateView.vue'),
      meta: { title: '模板中心', icon: 'Grid' }
    },
    {
      path: '/themes',
      name: 'themes',
      component: () => import('@/views/ThemeView.vue'),
      meta: { title: '主题与设计 token', icon: 'Brush' }
    },
    {
      path: '/plugins',
      name: 'plugins',
      component: () => import('@/views/PluginView.vue'),
      meta: { title: '插件中心', icon: 'Box' }
    },
    {
      path: '/about',
      name: 'about',
      component: () => import('@/views/AboutView.vue'),
      meta: { title: '系统状态', icon: 'InfoFilled' }
    },
    { path: '/:pathMatch(.*)*', redirect: '/intent' }
  ]
})

router.afterEach((to) => {
  const t = (to.meta?.title as string) || ''
  document.title = t ? `${t} · Campaign Edit` : 'Campaign Edit'
})

export default router