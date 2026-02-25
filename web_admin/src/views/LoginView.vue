<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <div class="login-title">Xray Audit Login</div>
      <el-form label-position="top">
        <el-form-item label="Username">
          <el-input v-model="username" placeholder="admin" autocomplete="username" />
        </el-form-item>
        <el-form-item label="Password">
          <el-input
            v-model="password"
            type="password"
            placeholder="Password"
            autocomplete="current-password"
            show-password
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button type="primary" :loading="loading" style="width: 100%" @click="submit">Sign In</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { useAuthStore } from "@/stores/auth";

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

const username = ref("");
const password = ref("");
const loading = ref(false);

async function submit() {
  if (!username.value.trim() || !password.value) {
    ElMessage.error("Username and password are required");
    return;
  }
  loading.value = true;
  try {
    await auth.login(username.value.trim(), password.value);
    const redirect = String(route.query.redirect || "/");
    await router.replace(redirect.startsWith("/") ? redirect : "/");
  } catch (error: any) {
    const detail = String(error?.response?.data?.detail || "");
    ElMessage.error(detail || "Login failed");
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-wrap {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.login-card {
  width: 420px;
  max-width: 100%;
}

.login-title {
  font-size: 24px;
  font-weight: 700;
  margin-bottom: 14px;
}
</style>
