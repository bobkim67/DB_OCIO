import { api } from "./client";

// === Meta ===
export type SourceKind = "db" | "cache" | "mock" | "mixed";

export interface SourceBreakdown {
  component: string;
  kind: "db" | "cache" | "mock";
  note: string | null;
}

export interface BaseMeta {
  as_of_date: string | null;
  source: SourceKind;
  sources: SourceBreakdown[];
  is_fallback: boolean;
  warnings: string[];
  generated_at: string;
}

// === Fund ===
export interface FundMetaDTO {
  code: string;
  name: string;
  group: string;
  inception: string;
  bm_configured: boolean;
  default_mapping_method: string;
}

export interface FundListResponseDTO {
  meta: BaseMeta;
  data: FundMetaDTO[];
}

// === Overview ===
export interface NavPointDTO {
  date: string;
  nav: number;
  bm: number | null;
  excess: number | null;
  aum: number | null;
}

export interface MetricCardDTO {
  key: string;
  label: string;
  value: number;             // raw ratio (0.0123 = 1.23%)
  unit: "pct" | "bp" | "currency" | "raw";
  bm_value: number | null;
  excess_value: number | null;
}

export interface OverviewResponseDTO {
  meta: BaseMeta;
  fund_code: string;
  fund_name: string;
  inception_date: string;
  bm_configured: boolean;
  cards: MetricCardDTO[];
  nav_series: NavPointDTO[];
  period_returns: Record<string, number>;        // Week 2: {"1M","3M","6M","YTD","1Y","SI"}
  bm_period_returns: Record<string, number>;     // Week 2: 동일 키, BM 없으면 빈 객체
}

// === Fetchers ===
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
