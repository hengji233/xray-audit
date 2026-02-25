<template>
  <div>
    <h1 class="page-title">Overview</h1>
    <el-card class="page-card">
      <div class="toolbar">
        <el-select v-model="windowValue" style="width: 130px">
          <el-option label="5 minutes" value="5m" />
          <el-option label="15 minutes" value="15m" />
          <el-option label="1 hour" value="1h" />
        </el-select>
        <el-button type="primary" :loading="loading" @click="reload">Refresh</el-button>
      </div>

      <div class="metric-grid">
        <div class="metric-item">
          <div class="metric-label">Total Events</div>
          <div class="metric-value">{{ summary.total_events }}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">Unique Users</div>
          <div class="metric-value">{{ summary.unique_users }}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">QPM</div>
          <div class="metric-value">{{ summary.qpm }}</div>
        </div>
      </div>
    </el-card>

    <el-row :gutter="12" class="section-gap">
      <el-col :span="16" :xs="24">
        <el-card class="page-card">
          <template #header>Top Domains</template>
          <v-chart :option="domainChartOption" style="height: 360px" autoresize />
        </el-card>
      </el-col>
      <el-col :span="8" :xs="24">
        <el-card class="page-card">
          <template #header>Active Users</template>
          <el-table :data="activeUsers" size="small" height="360">
            <el-table-column prop="user_email" label="Email" min-width="180" />
            <el-table-column label="Last Seen" min-width="160">
              <template #default="{ row }">
                {{ formatUnixSeconds(row.last_seen_unix, ui.useUtc) }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import VChart from "vue-echarts";
import { ElMessage } from "element-plus";
import { fetchActiveUsers, fetchSummary, fetchTopDomains } from "@/api/audit";
import { useUiStore } from "@/stores/ui";
import type { ActiveUser, DomainHit, SummaryStats } from "@/types";
import { formatUnixSeconds } from "@/utils/time";

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent]);

const ui = useUiStore();
const loading = ref(false);
const windowValue = ref("5m");
const summary = ref<SummaryStats>({
  window: "5m",
  total_events: 0,
  unique_users: 0,
  unique_domains: 0,
  qpm: 0,
});
const domains = ref<DomainHit[]>([]);
const activeUsers = ref<ActiveUser[]>([]);
let timer: number | undefined;

const domainChartOption = computed(() => ({
  backgroundColor: "transparent",
  tooltip: { trigger: "axis" },
  grid: { left: 50, right: 20, top: 20, bottom: 40 },
  xAxis: {
    type: "value",
    axisLabel: { color: "#476275" },
  },
  yAxis: {
    type: "category",
    data: domains.value.map((x) => x.domain),
    axisLabel: { color: "#29485c", width: 180, overflow: "truncate" },
  },
  series: [
    {
      type: "bar",
      data: domains.value.map((x) => x.hits),
      itemStyle: {
        color: "#0f547f",
        borderRadius: [0, 7, 7, 0],
      },
      barWidth: 14,
    },
  ],
}));

async function reload() {
  loading.value = true;
  try {
    const [summaryRes, topRes, usersRes] = await Promise.all([
      fetchSummary(windowValue.value),
      fetchTopDomains(windowValue.value, 12),
      fetchActiveUsers(30, 30),
    ]);
    summary.value = summaryRes;
    domains.value = topRes;
    activeUsers.value = usersRes;
  } catch (error) {
    ElMessage.error("Failed to load overview data");
  } finally {
    loading.value = false;
  }
}

watch(windowValue, () => {
  reload();
});

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
