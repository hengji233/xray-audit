import { defineStore } from "pinia";
import { authLogin, authLogout, authMe } from "@/api/audit";

interface AuthState {
  ready: boolean;
  username: string;
  authEnabled: boolean;
  mustChangePassword: boolean;
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    ready: false,
    username: "",
    authEnabled: true,
    mustChangePassword: false,
  }),
  getters: {
    loggedIn: (state) => !state.authEnabled || Boolean(state.username),
  },
  actions: {
    async refresh() {
      try {
        const me = await authMe();
        this.authEnabled = me.auth_enabled !== false;
        this.username = me.username || "";
        this.mustChangePassword = Boolean(me.must_change_password);
      } catch {
        this.username = "";
        this.authEnabled = true;
        this.mustChangePassword = false;
      } finally {
        this.ready = true;
      }
    },
    async init() {
      if (this.ready) {
        return;
      }
      await this.refresh();
    },
    async login(username: string, password: string) {
      await authLogin(username, password);
      await this.refresh();
    },
    async logout() {
      if (!this.authEnabled) {
        this.username = "system";
        this.mustChangePassword = false;
        this.ready = true;
        return;
      }
      try {
        await authLogout();
      } catch {
        // ignore
      }
      this.username = "";
      this.mustChangePassword = false;
      this.ready = true;
    },
  },
});
