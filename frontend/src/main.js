import { createApp, reactive } from 'vue'
import App from './App.vue'
import './styles.css'

export const store = reactive({
  access: localStorage.getItem('access') || '',
  refresh: localStorage.getItem('refresh') || '',
  user: null,
})

createApp(App).mount('#app')
