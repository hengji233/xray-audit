import { defineStore } from "pinia";

const KEY_USE_UTC = "xray-audit-ui-use-utc";

export const useUiStore = defineStore("ui", {
  state: () => ({
    useUtc: false,
  }),
  actions: {
    restore() {
      const raw = window.localStorage.getItem(KEY_USE_UTC);
      if (raw !== null) {
        this.useUtc = raw === "1";
      }
    },
    persist() {
      window.localStorage.setItem(KEY_USE_UTC, this.useUtc ? "1" : "0");
    },
  },
});
