import { createApp } from 'vue'
import { createPinia } from 'pinia'
import lazyPlugin from 'vue3-lazy'

import App from './App.vue'
import router from './router'
import './assets/main.css'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
import VueVirtualScroller from 'vue-virtual-scroller'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

app.use(lazyPlugin, {
  loading: '', // 可以配置懒加载的默认图片
  error: ''
})

app.use(VueVirtualScroller)

app.mount('#app')
