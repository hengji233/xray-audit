<template>
  <div>
    <h1 class="page-title">User Detail</h1>
    <el-card class="page-card">
      <div class="toolbar">
        <el-input :model-value="email" readonly style="width: 320px" />
        <el-date-picker
          v-model="timeRange"
          type="datetimerange"
          value-format="YYYY-MM-DDTHH:mm:ss"
          range-separator="to"
          start-placeholder="From"
          end-placeholder="To"
        />
        <el-button type="primary" :loading="loading" @click="fetchRows">Search</el-button>
      </div>

      <el-table :data="rows" border size="small" height="520">
        <el-table-column label="Time" min-width="180">
          <template #default="{ row }">{{ formatDateTime(row.event_time, ui.useUtc) }}</template>
        </el-table-column>
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
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import { geoipBatch, userVisits } from "@/api/audit";
import type { AccessEventRow } from "@/types";
import { useUiStore } from "@/stores/ui";
import { parseSourceIp } from "@/utils/net";
import { formatDateTime, getPickerRange, pickerRangeToUtcIso } from "@/utils/time";

const route = useRoute();
const ui = useUiStore();
const email = computed(() => decodeURIComponent(String(route.params.email || "")));
const timeRange = ref<[string, string]>(getPickerRange(24));
const rows = ref<AccessEventRow[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const loading = ref(false);
const geoMap = ref<Record<string, string>>({});

async function fetchRows() {
  if (!email.value) {
    return;
  }
  if (!timeRange.value || timeRange.value.length !== 2) {
    ElMessage.error("Time range is required");
    return;
  }
  loading.value = true;
  try {
    const [from, to] = pickerRangeToUtcIso(timeRange.value);
    const data = await userVisits(email.value, {
      from,
      to,
      page: page.value,
      page_size: pageSize.value,
    });
    rows.value = data.items;
    total.value = data.total;
    await hydrateGeo(data.items);
  } catch (error) {
    ElMessage.error("Failed to query user visits");
  } finally {
    loading.value = false;
  }
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

onMounted(() => {
  fetchRows();
});
</script>
