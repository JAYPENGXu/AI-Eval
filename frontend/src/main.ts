import { createApp } from 'vue'
import { createPinia } from 'pinia'
import {
  ElAside,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElContainer,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElMain,
  ElOption,
  ElSelect,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTooltip,
  ElUpload,
} from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import './styles.css'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
useAuthStore(pinia)

;[
  ElAside,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElContainer,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElMain,
  ElOption,
  ElSelect,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTooltip,
  ElUpload,
].forEach((component) => {
  app.use(component)
})

app.mount('#app')
