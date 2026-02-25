import { createApp } from "vue";
import { createPinia } from "pinia";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import App from "./App.vue";
import router from "./router";
import "./styles.css";
import { useAuthStore } from "@/stores/auth";

const app = createApp(App);
const pinia = createPinia();
app.use(pinia);
app.use(router);
app.use(ElementPlus);

router.beforeEach(async (to) => {
  const auth = useAuthStore(pinia);
  await auth.init();

  if (!auth.authEnabled) {
    if (to.path === "/login") {
      return { path: "/" };
    }
    return true;
  }

  const isPublic = Boolean(to.meta?.public);
  if (!isPublic && !auth.loggedIn) {
    return { path: "/login", query: { redirect: to.fullPath } };
  }
  if (to.path === "/login" && auth.loggedIn) {
    return { path: "/" };
  }
  if (
    auth.authEnabled &&
    auth.loggedIn &&
    auth.mustChangePassword &&
    to.path !== "/settings"
  ) {
    return { path: "/settings", query: { force_password_change: "1" } };
  }
  return true;
});

app.mount("#app");
