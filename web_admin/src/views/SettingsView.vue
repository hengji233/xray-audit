<template>
  <div>
    <h1 class="page-title">Settings</h1>
    <el-alert
      v-if="forcePasswordChange"
      title="Password change required: update your admin password before using other pages."
      type="warning"
      show-icon
      :closable="false"
      class="section-gap"
    />
    <el-card v-if="!forcePasswordChange" class="page-card">
      <div class="toolbar">
        <el-button type="primary" :loading="loadingSave" :disabled="forcePasswordChange" @click="save">Save</el-button>
        <el-button :loading="loadingBase" @click="reload">Reload</el-button>
      </div>

      <el-collapse v-model="activeGroups">
        <el-collapse-item v-for="group in groupedItems" :key="group.group" :name="group.group">
          <template #title>
            <strong>{{ group.label }}</strong>
          </template>
          <div class="group-grid">
            <el-card v-for="item in group.items" :key="item.config_key" class="setting-item">
              <div class="setting-key">{{ item.label }}</div>
              <div class="setting-desc">{{ item.description }}</div>
              <div class="setting-row">
                <component
                  :is="inputComponent(item)"
                  v-model="values[item.config_key]"
                  v-bind="inputProps(item)"
                  style="width: 100%"
                >
                  <el-option
                    v-for="option in item.options || []"
                    :key="option"
                    :label="option"
                    :value="option"
                  />
                </component>
              </div>
              <div class="setting-meta">
                <el-tag size="small" effect="plain">{{ currentSource(item.config_key) }}</el-tag>
                <span>Key: {{ item.config_key }}</span>
              </div>
            </el-card>
          </div>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <el-card v-if="auth.authEnabled" class="page-card section-gap">
      <template #header>Change Password</template>
      <div class="toolbar">
        <el-input
          v-model="passwordForm.oldPassword"
          type="password"
          show-password
          placeholder="Old password"
          style="width: 220px"
        />
        <el-input
          v-model="passwordForm.newPassword"
          type="password"
          show-password
          placeholder="New password"
          style="width: 240px"
        />
        <el-button type="primary" :loading="passwordSaving" @click="submitChangePassword">Update Password</el-button>
      </div>
    </el-card>

    <el-card v-if="!forcePasswordChange" class="page-card section-gap">
      <template #header>Config History</template>
      <el-table :data="historyRows" border size="small" height="340">
        <el-table-column prop="changed_at" label="Time" min-width="180" />
        <el-table-column prop="changed_by" label="By" width="120" />
        <el-table-column prop="source_ip" label="Source IP" width="140" />
        <el-table-column prop="config_key" label="Config Key" min-width="220" />
        <el-table-column prop="old_value_json" label="Old" min-width="220" show-overflow-tooltip />
        <el-table-column prop="new_value_json" label="New" min-width="220" show-overflow-tooltip />
      </el-table>
      <div class="section-gap">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="historyTotal"
          :page-size="historyPageSize"
          :current-page="historyPage"
          :page-sizes="[20, 50, 100]"
          @update:page-size="onHistoryPageSizeChange"
          @update:current-page="onHistoryPageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { changePassword, getConfigCurrent, getConfigHistory, getConfigSchema, updateConfigCurrent } from "@/api/audit";
import type {
  RuntimeConfigCurrentItem,
  RuntimeConfigHistoryItem,
  RuntimeConfigSchemaItem,
} from "@/types";
import { useAuthStore } from "@/stores/auth";

interface GroupBlock {
  group: string;
  label: string;
  items: RuntimeConfigSchemaItem[];
}

const schemaItems = ref<RuntimeConfigSchemaItem[]>([]);
const currentItems = ref<RuntimeConfigCurrentItem[]>([]);
const values = reactive<Record<string, unknown>>({});
const loadingBase = ref(false);
const loadingSave = ref(false);
const passwordSaving = ref(false);
const activeGroups = ref<string[]>([]);
const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const passwordForm = reactive({
  oldPassword: "",
  newPassword: "",
});
const forcePasswordChange = computed(
  () => auth.authEnabled && (auth.mustChangePassword || String(route.query.force_password_change || "") === "1")
);

const historyRows = ref<RuntimeConfigHistoryItem[]>([]);
const historyTotal = ref(0);
const historyPage = ref(1);
const historyPageSize = ref(50);

const groupedItems = computed<GroupBlock[]>(() => {
  const grouped: Record<string, GroupBlock> = {};
  for (const item of schemaItems.value) {
    if (!grouped[item.group]) {
      grouped[item.group] = {
        group: item.group,
        label: item.group_label || item.group,
        items: [],
      };
    }
    grouped[item.group].items.push(item);
  }
  return Object.values(grouped);
});

function inputComponent(item: RuntimeConfigSchemaItem): string {
  if (item.value_type === "bool") {
    return "el-switch";
  }
  if (item.value_type === "enum") {
    return "el-select";
  }
  if (item.value_type === "int" || item.value_type === "float") {
    return "el-input-number";
  }
  return "el-input";
}

function inputProps(item: RuntimeConfigSchemaItem): Record<string, unknown> {
  if (item.value_type === "bool") {
    return { "inline-prompt": true, "active-text": "On", "inactive-text": "Off" };
  }
  if (item.value_type === "enum") {
    return { clearable: false };
  }
  if (item.value_type === "int") {
    return {
      controls: true,
      precision: 0,
      min: item.min_value ?? undefined,
      max: item.max_value ?? undefined,
    };
  }
  if (item.value_type === "float") {
    return {
      controls: true,
      precision: 3,
      min: item.min_value ?? undefined,
      max: item.max_value ?? undefined,
    };
  }
  return { clearable: true };
}

function currentSource(configKey: string): string {
  const row = currentItems.value.find((x) => x.config_key === configKey);
  if (!row) {
    return "unknown";
  }
  return row.source === "db" ? "db override" : "env default";
}

async function reload() {
  loadingBase.value = true;
  try {
    const [schema, current] = await Promise.all([getConfigSchema(), getConfigCurrent()]);
    schemaItems.value = schema;
    currentItems.value = current;
    for (const row of current) {
      values[row.config_key] = row.value;
    }
    activeGroups.value = Array.from(new Set(schema.map((x) => x.group)));
    await loadHistory();
  } catch {
    ElMessage.error("Failed to load settings");
  } finally {
    loadingBase.value = false;
  }
}

async function save() {
  loadingSave.value = true;
  try {
    const payload: Record<string, unknown> = {};
    for (const item of schemaItems.value) {
      payload[item.config_key] = values[item.config_key];
    }
    const updated = await updateConfigCurrent(payload);
    currentItems.value = updated;
    ElMessage.success("Saved and hot-applied");
    await loadHistory();
  } catch (error: any) {
    const detail = error?.response?.data?.detail;
    ElMessage.error(detail ? String(detail) : "Save failed");
  } finally {
    loadingSave.value = false;
  }
}

async function submitChangePassword() {
  if (!passwordForm.oldPassword || !passwordForm.newPassword) {
    ElMessage.error("Old and new password are required");
    return;
  }
  passwordSaving.value = true;
  try {
    await changePassword(passwordForm.oldPassword, passwordForm.newPassword);
    await auth.refresh();
    if (!auth.mustChangePassword && String(route.query.force_password_change || "") === "1") {
      await router.replace({ path: "/settings" });
      await reload();
    }
    passwordForm.oldPassword = "";
    passwordForm.newPassword = "";
    ElMessage.success("Password updated");
  } catch (error: any) {
    const detail = String(error?.response?.data?.detail || "");
    ElMessage.error(detail || "Password update failed");
  } finally {
    passwordSaving.value = false;
  }
}

async function loadHistory() {
  const data = await getConfigHistory(historyPage.value, historyPageSize.value);
  historyRows.value = data.items;
  historyTotal.value = data.total;
}

async function onHistoryPageChange(nextPage: number) {
  historyPage.value = nextPage;
  await loadHistory();
}

async function onHistoryPageSizeChange(nextSize: number) {
  historyPageSize.value = nextSize;
  historyPage.value = 1;
  await loadHistory();
}

onMounted(() => {
  if (!forcePasswordChange.value) {
    reload();
  }
});
</script>

<style scoped>
.group-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
}

.setting-item {
  border-radius: 12px;
}

.setting-key {
  font-size: 15px;
  font-weight: 700;
}

.setting-desc {
  font-size: 12px;
  color: #587182;
  margin-top: 4px;
  min-height: 32px;
}

.setting-row {
  margin-top: 10px;
}

.setting-meta {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #587182;
}
</style>
