import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import { useSessionStore } from './stores/session'
import './styles/index.css'

async function bootstrap() {
  const app = createApp(App)
  app.use(ElementPlus, { locale: zhCn })
  app.use(router)

  // 启动即尝试静默登录：后端开了 AUTH_DISABLED 时直接放行，
  // 否则用演示账号换 token —— 让本地开发开箱即用。
  // 必须在挂载前完成，否则首屏的接口调用会因无 token 而 401。
  const session = useSessionStore()
  await session.loadSession()

  app.mount('#app')
}

bootstrap()