import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE ?? "/api";

export const api = axios.create({
  baseURL,
  withCredentials: false,
  timeout: 30_000,
});

// ---- 정적 스냅샷 모드 (GitHub Pages 등 백엔드 없는 배포, 2026-07-07) ----
// VITE_SNAPSHOT=1 빌드 시 모든 GET 을 public/snapshot/*.json 조회로 대체.
// 키 규칙은 tools/dump_static_snapshot.py 의 snapshot_key 와 동일해야 한다.
// 날짜류 파라미터는 키에서 제외 — 기본 기간 조합만 유효(그 외 요청도 기본 파일 반환).
const SNAPSHOT_PARAM_WHITELIST = ["asset_class", "item_cd", "level", "lookthrough", "period"];
const sanitize = (s: unknown) => String(s).replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
// 파라미터 값 — 한글 등 비ASCII 는 percent-encoding 16진수로 보존 (dump_static_snapshot.py 동일 규칙)
const sanitizeValue = (s: unknown) =>
  encodeURIComponent(String(s)).replace(/%/g, "").replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
export function snapshotKey(url: string, params?: Record<string, unknown>): string {
  let key = sanitize(url.replace(/^\//, ""));
  for (const k of Object.keys(params ?? {}).sort()) {
    if (SNAPSHOT_PARAM_WHITELIST.includes(k) && params![k] !== undefined && params![k] !== null) {
      key += `__${k}-${sanitizeValue(params![k])}`;
    }
  }
  return key;
}
if (import.meta.env.VITE_SNAPSHOT === "1") {
  api.defaults.adapter = async (config) => {
    const key = snapshotKey(config.url ?? "", config.params);
    const resp = await fetch(`${import.meta.env.BASE_URL}snapshot/${key}.json`);
    if (!resp.ok) {
      throw new axios.AxiosError(`snapshot missing: ${key}`, "SNAPSHOT_404", config as never);
    }
    const data = await resp.json();
    return { data, status: 200, statusText: "OK", headers: {}, config } as never;
  };
}

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
