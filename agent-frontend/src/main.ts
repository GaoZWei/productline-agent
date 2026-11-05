import { createPinia } from "pinia";
import "element-plus/es/components/alert/style/css";
import "element-plus/es/components/button/style/css";
import "element-plus/es/components/loading/style/css";
import "element-plus/es/components/skeleton/style/css";
import "element-plus/es/components/tag/style/css";
import { createApp } from "vue";

import App from "./App.vue";
import "./styles.css";

createApp(App).use(createPinia()).mount("#app");
