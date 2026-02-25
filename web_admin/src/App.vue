<template>
  <router-view v-if="isLoginPage" />
  <el-container v-else style="height: 100%">
    <el-header class="app-header">
      <div class="app-brand">
        <div class="title">Xray Audit</div>
        <div class="sub">Realtime access audit console</div>
      </div>
      <div class="app-actions">
        <el-tag size="small" effect="dark">{{ auth.username || "anonymous" }}</el-tag>
        <el-switch
          v-model="ui.useUtc"
          active-text="UTC"
          inactive-text="Local"
          inline-prompt
          @change="ui.persist()"
        />
        <el-button v-if="auth.authEnabled" size="small" @click="logout">Logout</el-button>
      </div>
    </el-header>
    <el-container>
      <el-aside width="220px" class="app-aside">
        <el-menu :default-active="activePath" router>
          <el-menu-item index="/">Overview</el-menu-item>
          <el-menu-item index="/events">Events</el-menu-item>
          <el-menu-item index="/errors">Errors</el-menu-item>
          <el-menu-item index="/users">Users</el-menu-item>
          <el-menu-item index="/settings">Settings</el-menu-item>
          <el-menu-item index="/system">System</el-menu-item>
        </el-menu>
      </el-aside>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useUiStore } from "@/stores/ui";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const router = useRouter();
const ui = useUiStore();
const auth = useAuthStore();
ui.restore();

const isLoginPage = computed(() => route.path === "/login");

const activePath = computed(() => {
  if (route.path.startsWith("/users/")) {
    return "/users";
  }
  return route.path || "/";
});

async function logout() {
  await auth.logout();
  await router.replace("/login");
}
</script>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  border-bottom: 1px solid rgba(5, 45, 66, 0.12);
  background: linear-gradient(120deg, rgba(14, 84, 127, 0.94), rgba(0, 122, 90, 0.9));
  color: #fff;
}

.app-brand .title {
  font-family: "Space Grotesk", "Segoe UI", sans-serif;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.1;
}

.app-brand .sub {
  font-size: 12px;
  opacity: 0.86;
}

.app-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.app-aside {
  border-right: 1px solid rgba(5, 45, 66, 0.08);
  background: rgba(255, 255, 255, 0.74);
}

.app-main {
  padding: 16px;
}

@media (max-width: 900px) {
  .app-aside {
    width: 84px !important;
  }

  :deep(.el-menu-item) {
    padding: 0 10px !important;
    font-size: 12px;
  }
}
</style>
