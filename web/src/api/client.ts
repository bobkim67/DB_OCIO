import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE ?? "/api";

export const api = axios.create({
  baseURL,
  withCredentials: false,
  timeout: 30_000,
});

api.interceptors.response.use(
  (resp) => resp,
  (err) => {
    if (import.meta.env.DEV) {
      // Week 1: 단순 로깅만. 401/토큰 처리는 Week 2+
      console.error(
        "[api]",
        err?.response?.status,
        err?.config?.url,
        err?.response?.data,
      );
    }
    return Promise.reject(err);
  },
);
