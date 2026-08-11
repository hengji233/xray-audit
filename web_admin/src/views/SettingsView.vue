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
            <div v-for="item in group.items" :key="item.config_key" class="setting-item">
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
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <el-card v-if="!forcePasswordChange" v-loading="storageLoading" class="page-card section-gap">
      <template #header>
        <div class="section-header">
          <strong>Storage</strong>
          <el-button size="small" :loading="storageStatusLoading" @click="loadStorageStatus">Refresh status</el-button>
        </div>
      </template>

      <div class="storage-summary">
        <div>
          <span class="summary-label">Active</span>
          <el-tag type="success" effect="plain">{{ storageConfig?.active_backend || "unknown" }}</el-tag>
        </div>
        <div>
          <span class="summary-label">Pending</span>
          <el-tag :type="storageConfig?.pending_backend ? 'warning' : 'info'" effect="plain">
            {{ storageConfig?.pending_backend || "none" }}
          </el-tag>
        </div>
        <div>
          <span class="summary-label">Status</span>
          <span>{{ storageStatusText }}</span>
        </div>
      </div>

      <el-divider />

      <el-form label-position="top" class="storage-form">
        <el-form-item label="Backend">
          <el-radio-group v-model="storageBackend">
            <el-radio-button value="memory">Memory</el-radio-button>
            <el-radio-button value="mysql">MySQL</el-radio-button>
            <el-radio-button value="d1">D1</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <div v-if="storageBackend === 'mysql'" class="storage-fields">
          <el-form-item label="Host">
            <el-input v-model="storageForm.mysql_host" placeholder="127.0.0.1" />
          </el-form-item>
          <el-form-item label="Port">
            <el-input-number v-model="storageForm.mysql_port" :min="1" :max="65535" controls-position="right" />
          </el-form-item>
          <el-form-item label="User">
            <el-input v-model="storageForm.mysql_user" />
          </el-form-item>
          <el-form-item label="Database">
            <el-input v-model="storageForm.mysql_db" />
          </el-form-item>
          <el-form-item label="Charset">
            <el-input v-model="storageForm.mysql_charset" placeholder="utf8mb4" />
          </el-form-item>
          <el-form-item>
            <template #label>
              Password
              <el-tag v-if="storageForm.mysql_password_configured" type="success" size="small" effect="plain">Configured</el-tag>
            </template>
            <el-input
              v-model="storageSecrets.mysql_password"
              type="password"
              show-password
              autocomplete="new-password"
              placeholder="Leave blank to keep the current password"
            />
          </el-form-item>
        </div>

        <div v-else-if="storageBackend === 'd1'" class="storage-fields">
          <el-form-item label="Gateway URL" class="wide-field">
            <el-input v-model="storageForm.d1_gateway_url" placeholder="https://..." />
          </el-form-item>
          <el-form-item label="Timeout (seconds)">
            <el-input-number v-model="storageForm.d1_timeout_seconds" :min="1" controls-position="right" />
          </el-form-item>
          <el-form-item label="Batch size">
            <el-input-number v-model="storageForm.d1_batch_size" :min="1" controls-position="right" />
          </el-form-item>
          <el-form-item label="Max retries">
            <el-input-number v-model="storageForm.d1_max_retries" :min="0" controls-position="right" />
          </el-form-item>
          <el-form-item class="wide-field">
            <template #label>
              Gateway token
              <el-tag v-if="storageForm.d1_gateway_token_configured" type="success" size="small" effect="plain">Configured</el-tag>
            </template>
            <el-input
              v-model="storageSecrets.d1_gateway_token"
              type="password"
              show-password
              autocomplete="new-password"
              placeholder="Leave blank to keep the current token"
            />
          </el-form-item>
        </div>

        <el-alert
          v-else
          title="Memory storage does not require connection settings."
          type="info"
          :closable="false"
          show-icon
        />
      </el-form>

      <div class="storage-actions">
        <el-button type="primary" :loading="storageSaving" @click="saveStorage">Save storage config</el-button>
        <el-button :loading="storageTesting" @click="testStorage">Test connection</el-button>
        <el-button
          type="warning"
          plain
          :loading="storageActivating"
          :disabled="storageConfig?.active_backend === storageBackend"
          @click="confirmActivateStorage"
        >
          Activate {{ storageBackend }}
        </el-button>
      </div>

      <el-divider content-position="left">Runtime status</el-divider>
      <el-descriptions :column="2" border size="small" class="status-details">
        <el-descriptions-item v-for="entry in storageStatusEntries" :key="entry.key" :label="entry.label">
          {{ entry.value }}
        </el-descriptions-item>
      </el-descriptions>
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
import { ElMessage, ElMessageBox } from "element-plus";
import {
  activateStorage,
  changePassword,
  getConfigCurrent,
  getConfigHistory,
  getConfigSchema,
  getStorageConfig,
  getStorageStatus,
  testStorageConnection,
  updateConfigCurrent,
  updateStorageConfig,
} from "@/api/audit";
import type {
  RuntimeConfigCurrentItem,
  RuntimeConfigHistoryItem,
  RuntimeConfigSchemaItem,
  StorageBackend,
  StorageConfigPayload,
  StorageConfigResponse,
  StorageConnectionConfig,
  StorageStatusResponse,
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
const storageConfig = ref<StorageConfigResponse | null>(null);
const storageStatus = ref<StorageStatusResponse>({});
const storageBackend = ref<StorageBackend>("memory");
const storageLoading = ref(false);
const storageStatusLoading = ref(false);
const storageSaving = ref(false);
const storageTesting = ref(false);
const storageActivating = ref(false);
const storageForm = reactive<StorageConnectionConfig>({
  mysql_host: "",
  mysql_port: 3306,
  mysql_user: "",
  mysql_db: "",
  mysql_charset: "utf8mb4",
  d1_gateway_url: "",
  d1_timeout_seconds: 10,
  d1_batch_size: 100,
  d1_max_retries: 3,
  mysql_password_configured: false,
  d1_gateway_token_configured: false,
});
const storageSecrets = reactive({ mysql_password: "", d1_gateway_token: "" });

const storageStatusText = computed(() => formatStatusValue(storageStatus.value.status ?? storageConfig.value?.status));
const storageStatusEntries = computed(() => {
  const details: Record<string, unknown> = { ...storageStatus.value };
  delete details.active_backend;
  delete details.pending_backend;
  delete details.status;
  if (!Object.keys(details).length && storageConfig.value?.memory) {
    details.memory = storageConfig.value.memory;
  }
  const entries = Object.entries(details).map(([key, value]) => ({
    key,
    label: key.replace(/_/g, " "),
    value: formatStatusValue(value),
  }));
  return entries.length ? entries : [{ key: "status", label: "status", value: storageStatusText.value }];
});

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

function formatStatusValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "unknown";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function applyStorageConfig(data: StorageConfigResponse) {
  storageConfig.value = data;
  storageBackend.value = data.pending_backend || data.active_backend;
  Object.assign(storageForm, data.config);
  storageSecrets.mysql_password = "";
  storageSecrets.d1_gateway_token = "";
}

function storagePayload(): StorageConfigPayload {
  const config: Partial<StorageConnectionConfig> = {};
  if (storageBackend.value === "mysql") {
    Object.assign(config, {
      mysql_host: storageForm.mysql_host,
      mysql_port: storageForm.mysql_port,
      mysql_user: storageForm.mysql_user,
      mysql_db: storageForm.mysql_db,
      mysql_charset: storageForm.mysql_charset,
    });
    if (storageSecrets.mysql_password) {
      config.mysql_password = storageSecrets.mysql_password;
    }
  } else if (storageBackend.value === "d1") {
    Object.assign(config, {
      d1_gateway_url: storageForm.d1_gateway_url,
      d1_timeout_seconds: storageForm.d1_timeout_seconds,
      d1_batch_size: storageForm.d1_batch_size,
      d1_max_retries: storageForm.d1_max_retries,
    });
    if (storageSecrets.d1_gateway_token) {
      config.d1_gateway_token = storageSecrets.d1_gateway_token;
    }
  }
  return { backend: storageBackend.value, config };
}

async function loadStorage() {
  storageLoading.value = true;
  try {
    const [config, status] = await Promise.all([getStorageConfig(), getStorageStatus()]);
    applyStorageConfig(config);
    storageStatus.value = status;
  } catch (error: any) {
    ElMessage.error(String(error?.response?.data?.detail || "Failed to load storage settings"));
  } finally {
    storageLoading.value = false;
  }
}

async function loadStorageStatus() {
  storageStatusLoading.value = true;
  try {
    storageStatus.value = await getStorageStatus();
  } catch (error: any) {
    ElMessage.error(String(error?.response?.data?.detail || "Failed to load storage status"));
  } finally {
    storageStatusLoading.value = false;
  }
}

async function saveStorage() {
  storageSaving.value = true;
  try {
    applyStorageConfig(await updateStorageConfig(storagePayload()));
    await loadStorageStatus();
    ElMessage.success("Storage configuration saved");
  } catch (error: any) {
    ElMessage.error(String(error?.response?.data?.detail || "Storage save failed"));
  } finally {
    storageSaving.value = false;
  }
}

async function testStorage() {
  storageTesting.value = true;
  try {
    const result = await testStorageConnection(storagePayload());
    ElMessage.success(result.message || "Storage connection succeeded");
  } catch (error: any) {
    ElMessage.error(String(error?.response?.data?.detail || "Storage connection failed"));
  } finally {
    storageTesting.value = false;
  }
}

async function confirmActivateStorage() {
  try {
    await ElMessageBox.confirm(
      `Activate ${storageBackend.value} storage? This changes the backend used by the service.`,
      "Confirm storage activation",
      { type: "warning", confirmButtonText: "Activate", cancelButtonText: "Cancel" }
    );
  } catch {
    return;
  }
  storageActivating.value = true;
  try {
    const result = await activateStorage(storageBackend.value);
    await loadStorage();
    ElMessage.success(result.message || `${storageBackend.value} storage activated`);
  } catch (error: any) {
    ElMessage.error(String(error?.response?.data?.detail || "Storage activation failed"));
  } finally {
    storageActivating.value = false;
  }
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
    loadStorage();
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
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.55);
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

.section-header,
.storage-summary,
.storage-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.section-header {
  justify-content: space-between;
}

.storage-summary {
  gap: 24px;
}

.storage-summary > div {
  display: flex;
  align-items: center;
  gap: 8px;
}

.summary-label {
  color: var(--text-sub);
  font-size: 13px;
}

.storage-form {
  max-width: 980px;
}

.storage-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 18px;
}

.storage-fields .wide-field {
  grid-column: 1 / -1;
}

.storage-fields :deep(.el-input-number) {
  width: 100%;
}

.storage-fields :deep(.el-form-item__label) {
  display: flex;
  align-items: center;
  gap: 8px;
}

.storage-actions {
  margin-top: 6px;
}

.status-details {
  width: 100%;
}

.status-details :deep(.el-descriptions__content) {
  overflow-wrap: anywhere;
}

@media (max-width: 700px) {
  .group-grid,
  .storage-fields {
    grid-template-columns: 1fr;
  }

  .storage-fields .wide-field {
    grid-column: auto;
  }

  .status-details :deep(.el-descriptions__body) {
    overflow-x: auto;
  }
}
</style>
