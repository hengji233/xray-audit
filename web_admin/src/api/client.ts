import axios from "axios";

const client = axios.create({
  baseURL: "/api/v1",
  timeout: 10000,
  withCredentials: true,
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status;
    const path = String(error?.config?.url || "");
    const detail = String(error?.response?.data?.detail || "");
    if (status === 401 && !path.includes("/auth/login")) {
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    if (status === 403 && detail === "password change required") {
      if (window.location.pathname !== "/settings") {
        window.location.href = "/settings?force_password_change=1";
      }
    }
    return Promise.reject(error);
  }
);

export default client;
