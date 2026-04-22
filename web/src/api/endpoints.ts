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

// === Holdings ===
export interface HoldingAssetClassDTO {
  asset_class: string;
  weight: number;              // raw ratio
  evl_amt: number;
  item_count: number;
  color: string | null;
}

export interface HoldingItemDTO {
  item_cd: string;
  item_nm: string;
  asset_class: string;
  weight: number;              // raw ratio
  evl_amt: number;
  sub_fund_cd: string | null;
}

export interface HoldingsResponseDTO {
  meta: BaseMeta;
  fund_code: string;
  fund_name: string;
  as_of_date: string | null;
  lookthrough_applied: boolean;
  nast_amt: number | null;
  asset_class_weights: HoldingAssetClassDTO[];
  holdings_items: HoldingItemDTO[];
}

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
