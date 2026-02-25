<template>
  <div>
    <h1 class="page-title">Errors</h1>
    <el-card class="page-card">
      <div class="toolbar">
        <el-date-picker
          v-model="timeRange"
          type="datetimerange"
          value-format="YYYY-MM-DDTHH:mm:ss"
          range-separator="to"
          start-placeholder="From"
          end-placeholder="To"
        />
        <el-select v-model="filters.level" placeholder="Level" clearable style="width: 120px">
          <el-option label="error" value="error" />
          <el-option label="warning" value="warning" />
          <el-option label="info" value="info" />
          <el-option label="debug" value="debug" />
          <el-option label="unknown" value="unknown" />
        </el-select>
        <el-input v-model="filters.category" placeholder="Category" clearable style="width: 180px" />
        <el-input v-model="filters.keyword" placeholder="Keyword" clearable style="width: 220px" />
        <el-switch v-model="filters.includeNoise" inline-prompt active-text="Noise" inactive-text="No Noise" />
      </div>

      <div class="toolbar">
        <el-button type="primary" :loading="loading" @click="loadData">Search</el-button>
        <el-button @click="resetFilters">Reset</el-button>
        <el-button @click="exportCsv">Export CSV</el-button>
        <el-switch v-model="autoRefresh" inline-prompt active-text="Auto 3s" inactive-text="Manual" />
      </div>

      <div class="metric-grid">
        <div class="metric-item">
          <div class="metric-label">Total</div>
          <div class="metric-value">{{ summary.total }}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">Error</div>
          <div class="metric-value">{{ summary.error_count }}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">Warning</div>
          <div class="metric-value">{{ summary.warning_count }}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">Info</div>
          <div class="metric-value">{{ summary.info_count }}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">Noise</div>
          <div class="metric-value">{{ summary.noise_count }}</div>
        </div>
      </div>

      <div class="section-gap">
        <v-chart :option="categoryChartOption" style="height: 320px" autoresize />
      </div>

      <div class="section-gap">
        <el-table :data="rows" border size="small" height="520">
          <el-table-column label="Time" min-width="170">
            <template #default="{ row }">{{ formatDateTime(row.event_time, ui.useUtc) }}</template>
          </el-table-column>
          <el-table-column label="Level" width="110">
            <template #default="{ row }">
              <el-tag :type="levelTagType(row.level)" effect="light">{{ row.level }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="category" label="Category" min-width="160" />
          <el-table-column prop="component" label="Component" min-width="220" show-overflow-tooltip />
          <el-table-column prop="message" label="Message" min-width="360" show-overflow-tooltip />
          <el-table-column prop="src" label="Source" min-width="160" show-overflow-tooltip />
          <el-table-column prop="dest_raw" label="Dest Raw" min-width="220" show-overflow-tooltip />
          <el-table-column prop="session_id" label="Session" width="120" />
          <el-table-column label="Noise" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="Boolean(row.is_noise) ? 'info' : 'success'">
                {{ Boolean(row.is_noise) ? "yes" : "no" }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="node_id" label="Node" min-width="120" />
        </el-table>
      </div>

      <div class="section-gap">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          :page-sizes="[20, 50, 100, 200]"
          @update:page-size="onPageSizeChange"
          @update:current-page="onPageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import VChart from "vue-echarts";
import { ElMessage } from "element-plus";
import { fetchErrorSummary, queryErrors } from "@/api/audit";
import { useUiStore } from "@/stores/ui";
import type { ErrorEventRow, ErrorSummary } from "@/types";
import {
  formatDateTime,
  getPickerRange,
  pickerRangeDurationSeconds,
  pickerRangeToUtcIso,
  shiftPickerRangeToNow,
} from "@/utils/time";

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent]);

const ui = useUiStore();
const timeRange = ref<[string, string]>(getPickerRange(1));

const filters = reactive({
  level: "",
  category: "",
  keyword: "",
  includeNoise: false,
});

const rows = ref<ErrorEventRow[]>([]);
const summary = ref<ErrorSummary>({
  window: "1h",
  total: 0,
  error_count: 0,
  warning_count: 0,
  info_count: 0,
  noise_count: 0,
  top_categories: [],
});
const loading = ref(false);
const autoRefresh = ref(true);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
let timer: number | undefined;
const defaultWindowSeconds = 3600;

const categoryChartOption = computed(() => ({
  backgroundColor: "transparent",
  tooltip: { trigger: "axis" },
  grid: { left: 80, right: 20, top: 20, bottom: 40 },
  xAxis: {
    type: "value",
    axisLabel: { color: "#476275" },
  },
  yAxis: {
    type: "category",
    data: summary.value.top_categories.map((x) => x.category || "unknown"),
    axisLabel: { color: "#29485c", width: 220, overflow: "truncate" },
  },
  series: [
    {
      type: "bar",
      data: summary.value.top_categories.map((x) => x.hits),
      itemStyle: {
        color: "#d97706",
        borderRadius: [0, 7, 7, 0],
      },
      barWidth: 14,
    },
  ],
}));

function summaryWindowFromRange(): string {
  if (!timeRange.value || timeRange.value.length !== 2) {
    return "1h";
  }
  const seconds = pickerRangeDurationSeconds(timeRange.value, defaultWindowSeconds);
  return `${seconds}s`;
}

function shiftRangeToNow(): void {
  timeRange.value = shiftPickerRangeToNow(timeRange.value, defaultWindowSeconds);
}

async function loadData(alignRangeToNow = false) {
  if (alignRangeToNow) {
    shiftRangeToNow();
  }
  if (!timeRange.value || timeRange.value.length !== 2) {
    ElMessage.error("Time range is required");
    return;
  }
  if (loading.value) {
    return;
  }
  loading.value = true;
  try {
    const [from, to] = pickerRangeToUtcIso(timeRange.value);
    const [queryData, summaryData] = await Promise.all([
      queryErrors({
        from,
        to,
        page: page.value,
        page_size: pageSize.value,
        level: filters.level || undefined,
        category: filters.category || undefined,
        keyword: filters.keyword || undefined,
        include_noise: filters.includeNoise,
      }),
      fetchErrorSummary(summaryWindowFromRange()),
    ]);
    rows.value = queryData.items;
    total.value = queryData.total;
    summary.value = summaryData;
  } catch (error) {
    ElMessage.error("Failed to query errors");
  } finally {
    loading.value = false;
  }
}

function resetFilters() {
  timeRange.value = getPickerRange(1);
  filters.level = "";
  filters.category = "";
  filters.keyword = "";
  filters.includeNoise = false;
  page.value = 1;
  pageSize.value = 50;
  loadData();
}

function onPageChange(nextPage: number) {
  page.value = nextPage;
  loadData();
}

function onPageSizeChange(nextSize: number) {
  pageSize.value = nextSize;
  page.value = 1;
  loadData();
}

function levelTagType(level: string): "danger" | "warning" | "info" | "" {
  const value = level.toLowerCase();
  if (value === "error") {
    return "danger";
  }
  if (value === "warning") {
    return "warning";
  }
  if (value === "info") {
    return "info";
  }
  return "";
}

function exportCsv() {
  const columns = [
    "event_time",
    "level",
    "category",
    "component",
    "message",
    "src",
    "dest_raw",
    "session_id",
    "is_noise",
    "node_id",
  ];
  const csvLines = [columns.join(",")];
  for (const row of rows.value) {
    const values = columns.map((key) => {
      const value = (row as Record<string, unknown>)[key];
      const text = value === undefined || value === null ? "" : String(value);
      return `"${text.replace(/"/g, "\"\"")}"`;
    });
    csvLines.push(values.join(","));
  }
  const blob = new Blob([csvLines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `xray-errors-page-${page.value}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function stopAutoRefresh() {
  if (timer) {
    window.clearInterval(timer);
    timer = undefined;
  }
}

function startAutoRefresh() {
  stopAutoRefresh();
  timer = window.setInterval(() => {
    loadData(true);
  }, 3000);
}

watch(autoRefresh, (enabled) => {
  if (enabled) {
    loadData(true);
    startAutoRefresh();
  } else {
    stopAutoRefresh();
  }
});

onMounted(() => {
  loadData();
  if (autoRefresh.value) {
    startAutoRefresh();
  }
});

onUnmounted(() => {
  stopAutoRefresh();
});
</script>
