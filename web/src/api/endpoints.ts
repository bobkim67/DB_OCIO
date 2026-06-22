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
export type WeightedDurationDTO = S["WeightedDurationDTO"];
export type PortfolioMixSummaryDTO = S["PortfolioMixSummaryDTO"];
export type HoldingsResponseDTO = S["HoldingsResponseDTO"];

// === Macro ===
export type MacroPointDTO = S["MacroPointDTO"];
export type MacroSeriesDTO = S["MacroSeriesDTO"];
export type MacroTimeseriesResponseDTO = S["MacroTimeseriesResponseDTO"];

// === Admin ===
export type AdminEvidenceQualityRowDTO = S["AdminEvidenceQualityRowDTO"];
export type AdminEvidenceQualityResponseDTO = S["AdminEvidenceQualityResponseDTO"];
export type AdminDebateStatusResponseDTO = S["AdminDebateStatusResponseDTO"];
export type AdminDebatePeriodsResponseDTO = S["AdminDebatePeriodsResponseDTO"];
export type DebateStatus = AdminDebateStatusResponseDTO["status"];

// === Admin Report Enrichment Diagnosis (P1-②, admin/debug 전용) ===
export type AdminReportEnrichmentResponseDTO = S["AdminReportEnrichmentResponseDTO"];
export type AdminEnrichmentJsonlRowDTO = S["AdminEnrichmentJsonlRowDTO"];
export type ReportEnrichmentFinalStatus =
  AdminReportEnrichmentResponseDTO["final_status"];
export type InternalReportEnrichmentDTO = S["InternalReportEnrichmentDTO"];

// === Report (client-facing approved-only) ===
export type ReportFinalDTO = S["ReportFinalDTO"];
export type ReportFinalResponseDTO = S["ReportFinalResponseDTO"];
export type ReportApprovedPeriodsResponseDTO = S["ReportApprovedPeriodsResponseDTO"];
// Client viewer 응답에 들어가는 enrichment (internal_source / raw reason 미포함).
export type ClientReportEnrichmentDTO = S["ClientReportEnrichmentDTO"];
// 기존 alias 유지 (호환). client 응답 타입이 ClientReportEnrichmentDTO 로 변경됨.
export type ReportEnrichmentDTO = S["ClientReportEnrichmentDTO"];
export type EvidenceAnnotationDTO = S["EvidenceAnnotationDTO"];
export type RelatedNewsDTO = S["RelatedNewsDTO"];
export type ClaimCitationDTO = S["ClaimCitationDTO"];
export type AgentOpinionDTO = S["AgentOpinionDTO"];
export type EvidenceQualitySummaryDTO = S["EvidenceQualitySummaryDTO"];
export type ValidationSummaryDTO = S["ValidationSummaryDTO"];
export type ValidationWarningDTO = S["ValidationWarningDTO"];
export type IndicatorChartDTO = S["IndicatorChartDTO"];
export type IndicatorSeriesDTO = S["IndicatorSeriesDTO"];
export type IndicatorPointDTO = S["IndicatorPointDTO"];

// === Wiki Coverage (R3) ===
export type WikiCoverageReportListItemDTO = S["WikiCoverageReportListItemDTO"];
export type WikiCoverageReportListResponseDTO = S["WikiCoverageReportListResponseDTO"];
export type WikiCoverageReportFullResponseDTO = S["WikiCoverageReportFullResponseDTO"];

// === Comment Trace (R4) ===
export type CommentTraceListItemDTO = S["CommentTraceListItemDTO"];
export type CommentTraceListResponseDTO = S["CommentTraceListResponseDTO"];
export type CommentTraceFullResponseDTO = S["CommentTraceFullResponseDTO"];

// === Wiki Context Pack (R9-B) ===
export type WikiContextPackPeriodItemDTO = S["WikiContextPackPeriodItemDTO"];
export type WikiContextPackPeriodsResponseDTO =
  S["WikiContextPackPeriodsResponseDTO"];
export type WikiContextPackSummaryDTO = S["WikiContextPackSummaryDTO"];
export type WikiContextPackResponseDTO = S["WikiContextPackResponseDTO"];
export type WikiPackStage = WikiContextPackResponseDTO["stage"];
export type WikiPageResponseDTO = S["WikiPageResponseDTO"];

// === Warmup (앱 시작 시 백그라운드 프리워밍 진행률) ===
export type WarmupStatusDTO = S["WarmupStatusDTO"];
export type WarmupErrorDTO = S["WarmupErrorDTO"];
export type WarmupStatus = WarmupStatusDTO["status"];

// === Brinson ===
export type BrinsonAssetRowDTO = S["BrinsonAssetRowDTO"];
export type BrinsonBmComponentDTO = S["BrinsonBmComponentDTO"];
export type BrinsonSecContribDTO = S["BrinsonSecContribDTO"];
export type BrinsonDailyPointDTO = S["BrinsonDailyPointDTO"];
export type BrinsonDailyClassDTO = S["BrinsonDailyClassDTO"];
export type BrinsonResponseDTO = S["BrinsonResponseDTO"];
export type BrinsonMappingMethod = "방법1" | "방법2" | "방법3" | "방법4";
export type BrinsonPaMethod = "8" | "5";

// === Transactions (거래내역 탭) ===
export type TransactionRowDTO = S["TransactionRowDTO"];
export type TransactionsResponseDTO = S["TransactionsResponseDTO"];
export type WeightHistoryPointDTO = S["WeightHistoryPointDTO"];
export type WeightMarkerDTO = S["WeightMarkerDTO"];
export type WeightHistoryResponseDTO = S["WeightHistoryResponseDTO"];
export type WeightHistoryLevel = "security" | "asset";
export type FxPositionPointDTO = S["FxPositionPointDTO"];
export type FxRatePointDTO = S["FxRatePointDTO"];
export type FxForeignWeightPointDTO = S["FxForeignWeightPointDTO"];
export type FxPositionResponseDTO = S["FxPositionResponseDTO"];
export type SecurityItemDTO = S["SecurityItemDTO"];
export type SecuritiesResponseDTO = S["SecuritiesResponseDTO"];
export type SecurityReturnPointDTO = S["SecurityReturnPointDTO"];
export type SecurityTradeMarkerDTO = S["SecurityTradeMarkerDTO"];
export type SecurityWeightPointDTO = S["SecurityWeightPointDTO"];
export type SecurityReturnResponseDTO = S["SecurityReturnResponseDTO"];

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

export const fetchAdminDebateStatus = async (
  period: string,
  fund: string,
): Promise<AdminDebateStatusResponseDTO> => {
  const r = await api.get<AdminDebateStatusResponseDTO>(
    "/admin/debate-status",
    { params: { period, fund } },
  );
  return r.data;
};

export const fetchAdminDebatePeriods =
  async (): Promise<AdminDebatePeriodsResponseDTO> => {
    const r = await api.get<AdminDebatePeriodsResponseDTO>(
      "/admin/debate-periods",
    );
    return r.data;
  };

export const fetchAdminReportEnrichmentDiagnosis = async (
  period: string,
  fund: string,
  limit?: number,
): Promise<AdminReportEnrichmentResponseDTO> => {
  const params: Record<string, string | number> = { period, fund };
  if (limit !== undefined) params.limit = limit;
  const r = await api.get<AdminReportEnrichmentResponseDTO>(
    "/admin/report-enrichment",
    { params },
  );
  return r.data;
};

// ----------------------------------------------------------------------
// Report (client-facing) — approved-only viewer.
// 시장(`_market`)과 펀드 코멘트는 의미적으로 다른 산출물이라 URL 분리.
// ----------------------------------------------------------------------
export const fetchMarketReport = async (
  period: string,
): Promise<ReportFinalResponseDTO> => {
  const r = await api.get<ReportFinalResponseDTO>("/market-report", {
    params: { period },
  });
  return r.data;
};

export const fetchMarketReportApprovedPeriods =
  async (): Promise<ReportApprovedPeriodsResponseDTO> => {
    const r = await api.get<ReportApprovedPeriodsResponseDTO>(
      "/market-report/approved-periods",
    );
    return r.data;
  };

export const fetchFundReport = async (
  code: string,
  period: string,
): Promise<ReportFinalResponseDTO> => {
  const r = await api.get<ReportFinalResponseDTO>(
    `/funds/${code}/report`,
    { params: { period } },
  );
  return r.data;
};

export const fetchFundReportApprovedPeriods = async (
  code: string,
): Promise<ReportApprovedPeriodsResponseDTO> => {
  const r = await api.get<ReportApprovedPeriodsResponseDTO>(
    `/funds/${code}/report/approved-periods`,
  );
  return r.data;
};

// ----------------------------------------------------------------------
// R3 — Wiki coverage report (read-only viewer)
// ----------------------------------------------------------------------
export const fetchWikiCoverageReports =
  async (): Promise<WikiCoverageReportListResponseDTO> => {
    const r = await api.get<WikiCoverageReportListResponseDTO>(
      "/admin/wiki-coverage/reports",
    );
    return r.data;
  };

export const fetchWikiCoverageLatest =
  async (): Promise<WikiCoverageReportFullResponseDTO> => {
    const r = await api.get<WikiCoverageReportFullResponseDTO>(
      "/admin/wiki-coverage/latest",
    );
    return r.data;
  };

export const fetchWikiCoverageById = async (
  reportId: string,
): Promise<WikiCoverageReportFullResponseDTO> => {
  const r = await api.get<WikiCoverageReportFullResponseDTO>(
    `/admin/wiki-coverage/${reportId}`,
  );
  return r.data;
};

// ----------------------------------------------------------------------
// R4 — Comment trace viewer (read-only)
// ----------------------------------------------------------------------
export const fetchCommentTraces = async (
  period?: string,
  fund?: string,
): Promise<CommentTraceListResponseDTO> => {
  const params: Record<string, string> = {};
  if (period) params.period = period;
  if (fund) params.fund = fund;
  const r = await api.get<CommentTraceListResponseDTO>("/admin/comment-trace", {
    params,
  });
  return r.data;
};

export const fetchCommentTraceLatest = async (
  period?: string,
  fund?: string,
): Promise<CommentTraceFullResponseDTO> => {
  const params: Record<string, string> = {};
  if (period) params.period = period;
  if (fund) params.fund = fund;
  const r = await api.get<CommentTraceFullResponseDTO>(
    "/admin/comment-trace/latest",
    { params },
  );
  return r.data;
};

export const fetchCommentTraceById = async (
  traceId: string,
): Promise<CommentTraceFullResponseDTO> => {
  const r = await api.get<CommentTraceFullResponseDTO>(
    `/admin/comment-trace/${traceId}`,
  );
  return r.data;
};

// ----------------------------------------------------------------------
// R9-B — Wiki Context Pack viewer (read-only)
// ----------------------------------------------------------------------
export const fetchWikiContextPackPeriods =
  async (): Promise<WikiContextPackPeriodsResponseDTO> => {
    const r = await api.get<WikiContextPackPeriodsResponseDTO>(
      "/admin/wiki-context-pack/periods",
    );
    return r.data;
  };

export interface FetchWikiContextPackOptions {
  fundCode?: string;
  maxPages?: number;
  bodyExcerptChars?: number;
  includeDebateMemory?: boolean;
}

export const fetchWikiContextPack = async (
  periodKey: string,
  stage: WikiPackStage,
  opts: FetchWikiContextPackOptions = {},
): Promise<WikiContextPackResponseDTO> => {
  const params: Record<string, string | number | boolean> = {
    period_key: periodKey,
    stage,
  };
  if (opts.fundCode) params.fund_code = opts.fundCode;
  if (opts.maxPages !== undefined) params.max_pages = opts.maxPages;
  if (opts.bodyExcerptChars !== undefined)
    params.body_excerpt_chars = opts.bodyExcerptChars;
  if (opts.includeDebateMemory !== undefined)
    params.include_debate_memory = opts.includeDebateMemory;
  const r = await api.get<WikiContextPackResponseDTO>(
    "/admin/wiki-context-pack",
    { params },
  );
  return r.data;
};

export const fetchWikiPage = async (
  path: string,
): Promise<WikiPageResponseDTO> => {
  const r = await api.get<WikiPageResponseDTO>("/admin/wiki-page", {
    params: { path },
  });
  return r.data;
};

// ----------------------------------------------------------------------
// Brinson 3-Factor Attribution
// ----------------------------------------------------------------------
export interface FetchBrinsonOptions {
  startDate?: string;
  endDate?: string;
  mappingMethod?: BrinsonMappingMethod;
  paMethod?: BrinsonPaMethod;
  fxSplit?: boolean;
  saaMode?: "auto" | "auto_drift" | "proxy" | "proxy_drift";
}

export const fetchBrinson = async (
  code: string,
  opts: FetchBrinsonOptions = {},
): Promise<BrinsonResponseDTO> => {
  const params: Record<string, string | boolean> = {};
  if (opts.startDate) params.start_date = opts.startDate;
  if (opts.endDate) params.end_date = opts.endDate;
  if (opts.mappingMethod) params.mapping_method = opts.mappingMethod;
  if (opts.paMethod) params.pa_method = opts.paMethod;
  if (opts.fxSplit !== undefined) params.fx_split = opts.fxSplit;
  if (opts.saaMode) params.saa_mode = opts.saaMode;
  // brinson 콜드 계산은 ~1분 → 공통 30s 타임아웃을 초과하므로 요청별로 상향.
  // (디스크 캐시 히트면 즉시지만, 날짜 변경 등 캐시 미스 시 재계산 대기)
  const r = await api.get<BrinsonResponseDTO>(
    `/funds/${code}/brinson`,
    { params, timeout: 120_000 },
  );
  return r.data;
};

// ----------------------------------------------------------------------
// 거래내역 탭 — 거래내역 조회 + 일별 비중 시계열 (FoF look-through)
// ----------------------------------------------------------------------
export const fetchTransactions = async (
  code: string,
  start: string,
  end: string,
): Promise<TransactionsResponseDTO> => {
  const r = await api.get<TransactionsResponseDTO>(
    `/funds/${code}/transactions`,
    { params: { start, end } },
  );
  return r.data;
};

export const fetchWeightHistory = async (
  code: string,
  start: string,
  level: WeightHistoryLevel,
): Promise<WeightHistoryResponseDTO> => {
  const r = await api.get<WeightHistoryResponseDTO>(
    `/funds/${code}/weight-history`,
    { params: { start, level } },
  );
  return r.data;
};

export const fetchFxPosition = async (
  code: string,
  start: string,
): Promise<FxPositionResponseDTO> => {
  const r = await api.get<FxPositionResponseDTO>(
    `/funds/${code}/fx-position`,
    { params: { start } },
  );
  return r.data;
};

export const fetchSecurities = async (
  code: string,
  start?: string,
): Promise<SecuritiesResponseDTO> => {
  const r = await api.get<SecuritiesResponseDTO>(`/funds/${code}/securities`, {
    params: start ? { start } : {},
  });
  return r.data;
};

export const fetchSecurityReturn = async (
  code: string,
  itemCd: string,
  itemNm: string,
  start: string,
  end: string,
): Promise<SecurityReturnResponseDTO> => {
  const r = await api.get<SecurityReturnResponseDTO>(
    `/funds/${code}/security-returns`,
    { params: { item_cd: itemCd, item_nm: itemNm, start, end } },
  );
  return r.data;
};

export const fetchAssetClassReturn = async (
  code: string,
  assetClass: string,
  start: string,
  end: string,
): Promise<SecurityReturnResponseDTO> => {
  const r = await api.get<SecurityReturnResponseDTO>(
    `/funds/${code}/asset-class-return`,
    { params: { asset_class: assetClass, start, end } },
  );
  return r.data;
};

// ----------------------------------------------------------------------
// Warmup — 앱 시작 시 백그라운드 프리워밍 진행률 (폴링용)
// ----------------------------------------------------------------------
export const fetchWarmupStatus = async (): Promise<WarmupStatusDTO> => {
  const r = await api.get<WarmupStatusDTO>("/warmup-status");
  return r.data;
};
