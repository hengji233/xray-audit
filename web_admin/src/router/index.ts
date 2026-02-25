import { createRouter, createWebHistory } from "vue-router";
import OverviewView from "@/views/OverviewView.vue";
import EventsView from "@/views/EventsView.vue";
import ErrorsView from "@/views/ErrorsView.vue";
import UsersView from "@/views/UsersView.vue";
import UserDetailView from "@/views/UserDetailView.vue";
import SystemView from "@/views/SystemView.vue";
import LoginView from "@/views/LoginView.vue";
import SettingsView from "@/views/SettingsView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", component: LoginView, meta: { public: true } },
    { path: "/", component: OverviewView },
    { path: "/events", component: EventsView },
    { path: "/errors", component: ErrorsView },
    { path: "/users", component: UsersView },
    { path: "/users/:email", component: UserDetailView },
    { path: "/settings", component: SettingsView },
    { path: "/system", component: SystemView },
  ],
});

export default router;
