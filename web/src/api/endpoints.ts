// ----------------------------------------------------------------------
// DTO 타입은 src/api/generated/openapi.d.ts 에서 자동 유도됨 (openapi-typescript).
// 스키마 변경 필요 시: FastAPI 기동 상태에서 `cd web && npm run openapi:gen`.
// 수동 타입 추가 금지 — 백엔드 Pydantic 모델에서 파생시켜야 함.
// fetcher 함수 시그니처는 이 파일에서 유지 (hooks/tabs/pages 호환).
// ----------------------------------------------------------------------
import { api } from "./client";
import type { components } from "./generated/openapi";

type S = components["schemas"];

// === Meta ===
export type SourceKind = S["BaseMeta"]["source"];
export type SourceBreakdown = S["SourceBreakdown"];
export type BaseMeta = S["BaseMeta"];

// === Fund ===
export type FundMetaDTO = S["FundMetaDTO"];
export type FundListResponseDTO = S["FundListResponseDTO"];

// === Overview ===
export type NavPointDTO = S["NavPointDTO"];
export type MetricCardDTO = S["MetricCardDTO"];
export type OverviewResponseDTO = S["OverviewResponseDTO"];

// === Holdings ===
export type HoldingAssetClassDTO = S["HoldingAssetClassDTO"];
export type HoldingItemDTO = S["HoldingItemDTO"];
export type FxHedgeSummaryDTO = S["FxHedgeSummaryDTO"];
export type HoldingsResponseDTO = S["HoldingsResponseDTO"];

// === Macro ===
export type MacroPointDTO = S["MacroPointDTO"];
export type MacroSeriesDTO = S["MacroSeriesDTO"];
export type MacroTimeseriesResponseDTO = S["MacroTimeseriesResponseDTO"];

// === Admin ===
export type AdminEvidenceQualityRowDTO = S["AdminEvidenceQualityRowDTO"];
export type AdminEvidenceQualityResponseDTO = S["AdminEvidenceQualityResponseDTO"];

// ----------------------------------------------------------------------
// Fetchers — 시그니처/구현 불변. DTO 타입만 generated alias 참조.
// ----------------------------------------------------------------------
export const fetchFunds = async (): Promise<FundListResponseDTO> => {
  const r = await api.get<FundListResponseDTO>("/funds");
  return r.data;
};

export const fetchOverview = async (
  code: string,
  startDate?: string,
): Promise<OverviewResponseDTO> => {
  const r = await api.get<OverviewResponseDTO>(`/funds/${code}/overview`, {
    params: startDate ? { start_date: startDate } : undefined,
  });
  return r.data;
};

export const fetchHoldings = async (
  code: string,
  lookthrough: boolean,
  asOfDate?: string,
): Promise<HoldingsResponseDTO> => {
  const params: Record<string, string | boolean> = { lookthrough };
  if (asOfDate) params.as_of_date = asOfDate;
  const r = await api.get<HoldingsResponseDTO>(
    `/funds/${code}/holdings`,
    { params },
  );
  return r.data;
};

export const fetchMacro = async (
  keys: string[],
  start?: string,
): Promise<MacroTimeseriesResponseDTO> => {
  const params: Record<string, string> = { keys: keys.join(",") };
  if (start) params.start = start;
  const r = await api.get<MacroTimeseriesResponseDTO>(
    "/macro/timeseries",
    { params },
  );
  return r.data;
};

export const fetchEvidenceQuality = async (
  limit?: number,
  fundCode?: string,
): Promise<AdminEvidenceQualityResponseDTO> => {
  const params: Record<string, string | number> = {};
  if (limit !== undefined) params.limit = limit;
  if (fundCode) params.fund_code = fundCode;
  const r = await api.get<AdminEvidenceQualityResponseDTO>(
    "/admin/evidence-quality",
    { params },
  );
  return r.data;
};
