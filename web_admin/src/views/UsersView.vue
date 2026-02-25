<template>
  <div>
    <h1 class="page-title">Users</h1>
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
        <el-button type="primary" :loading="loading" @click="fetchRows">Search</el-button>
      </div>

      <el-table :data="rows" border size="small" height="520" @row-click="openUser">
        <el-table-column prop="user_email" label="Email" min-width="220" />
        <el-table-column prop="count" label="Visits" width="120" />
        <el-table-column prop="unique_dest_host_count" label="Unique Domains" width="150" />
        <el-table-column label="Last Seen" min-width="180">
          <template #default="{ row }">{{ formatDateTime(row.last_seen, ui.useUtc) }}</template>
        </el-table-column>
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
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { listUsers } from "@/api/audit";
import { formatDateTime, getPickerRange, pickerRangeToUtcIso } from "@/utils/time";
import type { UserSummary } from "@/types";
import { useUiStore } from "@/stores/ui";

const router = useRouter();
const ui = useUiStore();
const timeRange = ref<[string, string]>(getPickerRange(24));
const rows = ref<UserSummary[]>([]);
const loading = ref(false);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);

async function fetchRows() {
  if (!timeRange.value || timeRange.value.length !== 2) {
    ElMessage.error("Time range is required");
    return;
  }
  loading.value = true;
  try {
    const [from, to] = pickerRangeToUtcIso(timeRange.value);
    const data = await listUsers({
      from,
      to,
      page: page.value,
      page_size: pageSize.value,
    });
    rows.value = data.items;
    total.value = data.total;
  } catch (error) {
    ElMessage.error("Failed to query users");
  } finally {
    loading.value = false;
  }
}

function openUser(row: UserSummary) {
  router.push(`/users/${encodeURIComponent(row.user_email)}`);
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

onMounted(() => {
  fetchRows();
});
</script>
