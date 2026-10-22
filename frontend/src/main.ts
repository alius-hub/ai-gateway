import { createPinia } from "pinia";
import { createApp } from "vue";
import "element-plus/dist/index.css";

import App from "./App.vue";
import { backdropClose } from "./directives/backdropClose";
import router from "./router";
import "./styles/index.css";

const app = createApp(App);
app.directive("backdrop-close", backdropClose);

app.use(createPinia());
app.use(router);
app.mount("#app");
