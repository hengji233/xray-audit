<template>
  <div>
    <h1 class="page-title">System</h1>
    <el-card class="page-card">
      <div class="toolbar">
        <el-button type="primary" :loading="loading" @click="reload">Refresh</el-button>
      </div>

      <div class="metric-grid">
        <div class="metric-item">
          <div class="metric-label">Node</div>
          <div class="metric-value" style="font-size: 20px">{{ data?.node_id || "-" }}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">Collector Embedded</div>
          <div class="metric-value" style="font-size: 20px">{{ data?.collector_embedded ? "Yes" : "No" }}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">Now</div>
          <div class="metric-value" style="font-size: 20px">
            {{ data?.now ? formatDateTime(data.now, ui.useUtc) : "-" }}
          </div>
        </div>
        <div class="metric-item">
          <div class="metric-label">Collector Lag (s)</div>
          <div class="metric-value" style="font-size: 20px">{{ collectorLag }}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">API 5xx / 5m</div>
          <div class="metric-value" style="font-size: 20px">{{ api5xx5m }}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">API 5xx Rate / 5m</div>
          <div class="metric-value" style="font-size: 20px">{{ api5xxRate5m }}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">Collector DB Write Fail</div>
          <div class="metric-value" style="font-size: 20px">{{ dbWriteFailTotal }}</div>
        </div>
      </div>

      <div class="section-gap" v-if="(data?.alerts || []).length > 0">
        <el-alert
          v-for="alert in data?.alerts || []"
          :key="`${alert.code}:${alert.message}`"
          :title="`${alert.code}: ${alert.message}`"
          :type="alert.severity === 'critical' ? 'error' : 'warning'"
          show-icon
          :closable="false"
          style="margin-bottom: 8px"
        />
      </div>

      <div class="section-gap">
        <el-input
          type="textarea"
          :rows="20"
          :model-value="prettyJson"
          readonly
          style="font-family: Consolas, monospace"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { fetchHealth } from "@/api/audit";
import type { HealthResponse } from "@/types";
import { useUiStore } from "@/stores/ui";
import { formatDateTime } from "@/utils/time";

const ui = useUiStore();
const data = ref<HealthResponse | null>(null);
const loading = ref(false);
let timer: number | undefined;

const prettyJson = computed(() => JSON.stringify(data.value, null, 2));
const collectorLag = computed(() => {
  const value = data.value?.collector_lag_seconds;
  if (value === undefined || value === null) {
    return "-";
  }
  return String(value);
});
const api5xx5m = computed(() => {
  const value = data.value?.api_metrics?.responses_5xx_5m;
  if (value === undefined || value === null) {
    return "-";
  }
  return String(value);
});
const api5xxRate5m = computed(() => {
  const value = data.value?.api_metrics?.error_rate_5xx_5m;
  if (value === undefined || value === null) {
    return "-";
  }
  const percentage = Number(value) * 100;
  if (!Number.isFinite(percentage)) {
    return "-";
  }
  return `${percentage.toFixed(2)}%`;
});
const dbWriteFailTotal = computed(() => {
  const value = data.value?.local_stats?.db_write_fail_total;
  if (value === undefined || value === null) {
    return "-";
  }
  return String(value);
});

async function reload() {
  loading.value = true;
  try {
    data.value = await fetchHealth();
  } catch (error) {
    ElMessage.error("Failed to load system data");
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  reload();
  timer = window.setInterval(reload, 3000);
});

onUnmounted(() => {
  if (timer) {
    window.clearInterval(timer);
  }
});
</script>
