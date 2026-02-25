<template>
  <div>
    <h1 class="page-title">Events</h1>
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
        <el-input v-model="filters.email" placeholder="Email" clearable style="width: 180px" />
        <el-input v-model="filters.destHost" placeholder="Domain contains" clearable style="width: 180px" />
        <el-select v-model="filters.status" placeholder="Status" clearable style="width: 120px">
          <el-option label="accepted" value="accepted" />
          <el-option label="rejected" value="rejected" />
        </el-select>
        <el-input v-model="filters.detour" placeholder="Detour contains" clearable style="width: 180px" />
        <el-select v-model="filters.isDomain" placeholder="Domain only" clearable style="width: 120px">
          <el-option label="Yes" :value="true" />
          <el-option label="No" :value="false" />
        </el-select>
      </div>
      <div class="toolbar">
        <el-button type="primary" :loading="loading" @click="fetchRows">Search</el-button>
        <el-button @click="resetFilters">Reset</el-button>
        <el-button @click="exportCsv">Export CSV</el-button>
        <el-switch v-model="autoRefresh" inline-prompt active-text="Auto 3s" inactive-text="Manual" />
      </div>

      <el-table :data="rows" border size="small" height="520">
        <el-table-column label="Time" min-width="170">
          <template #default="{ row }">{{ formatDateTime(row.event_time, ui.useUtc) }}</template>
        </el-table-column>
        <el-table-column prop="user_email" label="Email" min-width="180" />
        <el-table-column prop="src" label="Source" min-width="160" />
        <el-table-column label="Source Geo" min-width="220">
          <template #default="{ row }">{{ geoForRow(row) }}</template>
        </el-table-column>
        <el-table-column prop="dest_host" label="Domain/Host" min-width="200" />
        <el-table-column prop="dest_port" label="Port" width="90" />
        <el-table-column prop="status" label="Status" width="100" />
        <el-table-column prop="detour" label="Detour" min-width="220" />
      </el-table>

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
import { onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { geoipBatch, queryEvents } from "@/api/audit";
import type { AccessEventRow } from "@/types";
import { useUiStore } from "@/stores/ui";
import { parseSourceIp } from "@/utils/net";
import { formatDateTime, getPickerRange, pickerRangeToUtcIso, shiftPickerRangeToNow } from "@/utils/time";

const ui = useUiStore();
const timeRange = ref<[string, string]>(getPickerRange(1));

const filters = reactive({
  email: "",
  destHost: "",
  status: "",
  detour: "",
  isDomain: undefined as boolean | undefined,
});
const rows = ref<AccessEventRow[]>([]);
const loading = ref(false);
const autoRefresh = ref(true);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const geoMap = ref<Record<string, string>>({});
let timer: number | undefined;
const defaultWindowSeconds = 3600;

function shiftRangeToNow(): void {
  timeRange.value = shiftPickerRangeToNow(timeRange.value, defaultWindowSeconds);
}

async function fetchRows(alignRangeToNow = false) {
  if (alignRangeToNow) {
    shiftRangeToNow();
  }
  if (!timeRange.value || timeRange.value.length !== 2) {
    ElMessage.error("Time range is required");
    return;
  }
  loading.value = true;
  try {
    const [from, to] = pickerRangeToUtcIso(timeRange.value);
    const data = await queryEvents({
      from,
      to,
      page: page.value,
      page_size: pageSize.value,
      email: filters.email || undefined,
      dest_host: filters.destHost || undefined,
      status: filters.status || undefined,
      detour: filters.detour || undefined,
      is_domain: filters.isDomain,
    });
    rows.value = data.items;
    total.value = data.total;
    await hydrateGeo(data.items);
  } catch (error) {
    ElMessage.error("Failed to query events");
  } finally {
    loading.value = false;
  }
}

function resetFilters() {
  timeRange.value = getPickerRange(1);
  filters.email = "";
  filters.destHost = "";
  filters.status = "";
  filters.detour = "";
  filters.isDomain = undefined;
  page.value = 1;
  fetchRows();
}

function onPageChange(nextPage: number) {
  page.value = nextPage;
  fetchRows();
}

function onPageSizeChange(nextSize: number) {
  pageSize.value = nextSize;
  page.value = 1;
  fetchRows();
}

function exportCsv() {
  const columns = [
    "event_time",
    "user_email",
    "src",
    "src_geo",
    "dest_host",
    "dest_port",
    "status",
    "detour",
    "reason",
  ];
  const csvLines = [columns.join(",")];
  for (const row of rows.value) {
    const values = columns.map((key) => {
      const value = (row as Record<string, unknown>)[key];
      const text = key === "src_geo" ? geoForRow(row) : value === undefined || value === null ? "" : String(value);
      return `"${text.replace(/"/g, "\"\"")}"`;
    });
    csvLines.push(values.join(","));
  }
  const blob = new Blob([csvLines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `xray-events-page-${page.value}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

async function hydrateGeo(items: AccessEventRow[]) {
  const ips = Array.from(new Set(items.map((row) => parseSourceIp(row.src)).filter((v) => Boolean(v))));
  if (ips.length === 0) {
    geoMap.value = {};
    return;
  }
  try {
    const geo = await geoipBatch(ips);
    const mapped: Record<string, string> = {};
    for (const [ip, item] of Object.entries(geo)) {
      mapped[ip] = item.label || item.addr || "unknown";
    }
    geoMap.value = mapped;
  } catch (error) {
    geoMap.value = {};
  }
}

function geoForRow(row: AccessEventRow): string {
  const ip = parseSourceIp(row.src);
  if (!ip) {
    return "-";
  }
  return geoMap.value[ip] || "-";
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
    fetchRows(true);
  }, 3000);
}

watch(autoRefresh, (enabled) => {
  if (enabled) {
    fetchRows(true);
    startAutoRefresh();
  } else {
    stopAutoRefresh();
  }
});

onMounted(() => {
  fetchRows();
  if (autoRefresh.value) {
    startAutoRefresh();
  }
});

onUnmounted(() => {
  stopAutoRefresh();
});
</script>
