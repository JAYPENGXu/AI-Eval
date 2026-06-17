import { createApp, reactive } from 'vue'
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

export const store = reactive({
  access: localStorage.getItem('access') || '',
  refresh: localStorage.getItem('refresh') || '',
  user: null,
})

const app = createApp(App)

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
