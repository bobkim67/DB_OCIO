import { useMemo, useState, type CSSProperties } from "react";
import MetaBadge from "../components/common/MetaBadge";
import {
  useWikiContextPack,
  useWikiContextPackPeriods,
  useWikiPage,
} from "../hooks/useWikiContextPack";
import type { WikiPackStage } from "../api/endpoints";

const STAGES: { value: WikiPackStage; label: string }[] = [
  { value: "market_debate", label: "market_debate" },
  { value: "fund_comment", label: "fund_comment" },
  { value: "quarterly_debate", label: "quarterly_debate" },
  { value: "admin_preview", label: "admin_preview" },
];

const FUNDS = [
  "07G02", "07G03", "07G04", "08K88", "08N33", "08N81",
  "08P22", "2JM23", "4JM12",
] as const;

const SECTION: CSSProperties = {
  border: "1px solid #e5e7eb",
  borderRadius: 6,
  padding: 12,
  marginBottom: 12,
  background: "#fff",
};

const SECTION_TITLE: CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  color: "#374151",
  marginBottom: 8,
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const PATH_BTN: CSSProperties = {
  fontSize: 12,
  fontFamily: "monospace",
  background: "transparent",
  border: "none",
  color: "#2563eb",
  cursor: "pointer",
  padding: 0,
  textAlign: "left",
  textDecoration: "underline",
};

const KV_LABEL: CSSProperties = {
  fontSize: 12,
  color: "#6b7280",
  marginRight: 6,
};

function fmtJoinRate(v: number | null | undefined): string {
  if (v === null || v === undefined) return "n/a";
  return `${(v * 100).toFixed(1)}%`;
}

function CountChip({
  label,
  value,
  highlight,
}: {
  label: string;
  value: number | string;
  highlight?: boolean;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        background: highlight ? "#fef3c7" : "#f3f4f6",
        color: "#1f2937",
        borderRadius: 4,
        padding: "2px 8px",
        fontSize: 12,
        fontWeight: 500,
      }}
    >
      <span style={{ color: "#6b7280" }}>{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

export default function AdminWikiContextPackPanel() {
  const periodsQ = useWikiContextPackPeriods();
  const [period, setPeriod] = useState<string>("");
  const [stage, setStage] = useState<WikiPackStage>("market_debate");
  const [fundCode, setFundCode] = useState<string>("08K88");
  const [maxPages, setMaxPages] = useState<number>(12);
  const [includeDebateMemory, setIncludeDebateMemory] = useState<boolean>(false);
  const [openPath, setOpenPath] = useState<string | null>(null);

  // periods 응답이 도착하면 첫 항목으로 기본 선택
  const periods = periodsQ.data?.periods ?? [];
  const effectivePeriod = period || periods[0]?.period_key || "";

  const packQ = useWikiContextPack(
    effectivePeriod || null,
    stage,
    {
      fundCode: stage === "fund_comment" ? fundCode : undefined,
      maxPages,
      includeDebateMemory,
    },
  );

  const pageQ = useWikiPage(openPath);

  const summary = packQ.data?.summary;
  const warnings = (packQ.data?.pack?.warnings ?? []) as Array<
    Record<string, unknown>
  >;

  const sortedSourceTypes = useMemo(() => {
    if (!summary) return [] as [string, number][];
    return Object.entries(summary.source_type_counts).sort(
      (a, b) => b[1] - a[1],
    );
  }, [summary]);

  const sortedDirs = useMemo(() => {
    if (!summary) return [] as [string, number][];
    return Object.entries(summary.selected_by_directory).sort((a, b) =>
      a[0].localeCompare(b[0]),
    );
  }, [summary]);

  return (
    <section>
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 12,
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <h2 style={{ fontSize: 16, margin: 0 }}>
          Admin · Wiki Context Pack (R9-B)
        </h2>
        {packQ.data && <MetaBadge meta={packQ.data.meta} />}
      </div>

      <div
        style={{
          display: "flex",
          gap: 12,
          marginBottom: 12,
          fontSize: 13,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <label>
          period:&nbsp;
          <select
            value={effectivePeriod}
            onChange={(e) => setPeriod(e.target.value)}
            style={{ fontSize: 13, padding: "3px 6px" }}
            disabled={periodsQ.isLoading || periods.length === 0}
          >
            {periods.map((p) => (
              <option key={p.period_key} value={p.period_key}>
                {p.period_key}
                {p.claim_count !== null && p.claim_count !== undefined
                  ? ` (claims=${p.claim_count})`
                  : ""}
              </option>
            ))}
          </select>
        </label>

        <label>
          stage:&nbsp;
          <select
            value={stage}
            onChange={(e) => setStage(e.target.value as WikiPackStage)}
            style={{ fontSize: 13, padding: "3px 6px" }}
          >
            {STAGES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>

        {stage === "fund_comment" && (
          <label>
            fund:&nbsp;
            <select
              value={fundCode}
              onChange={(e) => setFundCode(e.target.value)}
              style={{ fontSize: 13, padding: "3px 6px" }}
            >
              {FUNDS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </label>
        )}

        <label>
          max_pages:&nbsp;
          <input
            type="number"
            min={1}
            max={64}
            value={maxPages}
            onChange={(e) =>
              setMaxPages(Math.max(1, Math.min(64, Number(e.target.value) || 1)))
            }
            style={{
              fontSize: 13,
              padding: "3px 6px",
              width: 60,
              border: "1px solid #d1d5db",
              borderRadius: 4,
            }}
          />
        </label>

        <label
          style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
        >
          <input
            type="checkbox"
            checked={includeDebateMemory}
            onChange={(e) => setIncludeDebateMemory(e.target.checked)}
          />
          include 06_Debate_Memory
        </label>
      </div>

      {packQ.isLoading && (
        <div style={{ padding: 16, color: "#6b7280" }}>
          loading context pack...
        </div>
      )}
      {packQ.error && (
        <div style={{ padding: 16, color: "#b91c1c" }}>
          pack 조회 실패: {String((packQ.error as Error).message ?? packQ.error)}
        </div>
      )}

      {packQ.data && summary && (
        <>
          <div style={SECTION}>
            <div style={SECTION_TITLE}>요약</div>
            <div
              style={{
                display: "flex",
                gap: 8,
                flexWrap: "wrap",
                marginBottom: 8,
              }}
            >
              <CountChip
                label="considered"
                value={summary.wiki_pages_considered}
              />
              <CountChip
                label="selected"
                value={summary.wiki_pages_selected}
              />
              <CountChip
                label="claim_store"
                value={summary.claim_store_selected_count}
              />
              <CountChip
                label="matched"
                value={summary.matched_wiki_claim_count}
              />
              <CountChip
                label="join_rate"
                value={fmtJoinRate(summary.claim_store_to_wiki_join_rate)}
              />
              <CountChip
                label="cutoff_violations"
                value={summary.source_cutoff_violations}
                highlight={summary.source_cutoff_violations > 0}
              />
            </div>
            <div style={{ fontSize: 12, color: "#6b7280" }}>
              <span style={KV_LABEL}>schema:</span>
              <code>{String(packQ.data.pack?.schema_version ?? "?")}</code>
              &nbsp;·&nbsp;
              <span style={KV_LABEL}>window:</span>
              <code>
                {String(packQ.data.pack?.window_start ?? "?")} →{" "}
                {String(packQ.data.pack?.window_end ?? "?")}
              </code>
              &nbsp;·&nbsp;
              <span style={KV_LABEL}>as_of:</span>
              <code>{String(packQ.data.pack?.as_of_date ?? "?")}</code>
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 12,
            }}
          >
            <div style={SECTION}>
              <div style={SECTION_TITLE}>source_type_counts</div>
              {sortedSourceTypes.length === 0 ? (
                <div style={{ color: "#6b7280", fontSize: 12 }}>(empty)</div>
              ) : (
                <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12 }}>
                  {sortedSourceTypes.map(([k, v]) => (
                    <li key={k}>
                      <code>{k}</code> &nbsp;—&nbsp; <strong>{v}</strong>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div style={SECTION}>
              <div style={SECTION_TITLE}>selected_by_directory</div>
              {sortedDirs.length === 0 ? (
                <div style={{ color: "#6b7280", fontSize: 12 }}>(empty)</div>
              ) : (
                <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12 }}>
                  {sortedDirs.map(([k, v]) => (
                    <li key={k}>
                      <code>{k}</code> &nbsp;—&nbsp; <strong>{v}</strong>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div style={SECTION}>
            <div style={SECTION_TITLE}>
              selected_claim_ids ({summary.selected_claim_ids.length})
            </div>
            {summary.selected_claim_ids.length === 0 ? (
              <div style={{ color: "#6b7280", fontSize: 12 }}>(none)</div>
            ) : (
              <ul
                style={{
                  margin: 0,
                  paddingLeft: 16,
                  fontSize: 12,
                  fontFamily: "monospace",
                }}
              >
                {summary.selected_claim_ids.map((cid) => (
                  <li key={cid}>{cid}</li>
                ))}
              </ul>
            )}
            {summary.selected_related_group_ids.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div
                  style={{ fontSize: 12, color: "#6b7280", marginBottom: 4 }}
                >
                  related_group_ids
                </div>
                <ul
                  style={{
                    margin: 0,
                    paddingLeft: 16,
                    fontSize: 12,
                    fontFamily: "monospace",
                  }}
                >
                  {summary.selected_related_group_ids.map((g) => (
                    <li key={g}>{g}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div style={SECTION}>
            <div style={SECTION_TITLE}>
              selected_wiki_paths ({summary.selected_wiki_paths.length})
            </div>
            {summary.selected_wiki_paths.length === 0 ? (
              <div style={{ color: "#6b7280", fontSize: 12 }}>(none)</div>
            ) : (
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {summary.selected_wiki_paths.map((p) => (
                  <li key={p}>
                    <button
                      style={{
                        ...PATH_BTN,
                        fontWeight: openPath === p ? 700 : 400,
                      }}
                      onClick={() => setOpenPath(p)}
                    >
                      {p}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {warnings.length > 0 && (
            <div
              style={{
                ...SECTION,
                borderColor: "#fbbf24",
                background: "#fffbeb",
              }}
            >
              <div style={{ ...SECTION_TITLE, color: "#92400e" }}>
                warnings ({warnings.length})
              </div>
              <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12 }}>
                {warnings.map((w, i) => (
                  <li key={i} style={{ fontFamily: "monospace" }}>
                    <strong>{String(w.warning_type ?? "?")}</strong>
                    &nbsp;
                    <code style={{ color: "#6b7280" }}>
                      {JSON.stringify(
                        Object.fromEntries(
                          Object.entries(w).filter(
                            ([k]) => k !== "warning_type",
                          ),
                        ),
                      )}
                    </code>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {openPath && (
            <div style={SECTION}>
              <div style={SECTION_TITLE}>
                <span>wiki page · </span>
                <code style={{ fontSize: 12 }}>{openPath}</code>
                <button
                  onClick={() => setOpenPath(null)}
                  style={{
                    marginLeft: "auto",
                    fontSize: 11,
                    border: "1px solid #d1d5db",
                    background: "#fff",
                    padding: "2px 8px",
                    borderRadius: 4,
                    cursor: "pointer",
                  }}
                >
                  close
                </button>
              </div>
              {pageQ.isLoading && (
                <div style={{ color: "#6b7280", fontSize: 12 }}>
                  loading page...
                </div>
              )}
              {pageQ.error && (
                <div style={{ color: "#b91c1c", fontSize: 12 }}>
                  page 조회 실패:{" "}
                  {String((pageQ.error as Error).message ?? pageQ.error)}
                </div>
              )}
              {pageQ.data && (
                <>
                  <div
                    style={{
                      fontSize: 12,
                      color: "#6b7280",
                      marginBottom: 8,
                    }}
                  >
                    <span style={KV_LABEL}>title:</span>
                    <strong style={{ color: "#1f2937" }}>
                      {pageQ.data.title || "(none)"}
                    </strong>
                    &nbsp;·&nbsp;
                    <span style={KV_LABEL}>type:</span>
                    <code>{pageQ.data.page_type}</code>
                    &nbsp;·&nbsp;
                    <span style={KV_LABEL}>source_type:</span>
                    <code>{pageQ.data.source_type}</code>
                    &nbsp;·&nbsp;
                    <span style={KV_LABEL}>bytes:</span>
                    {pageQ.data.byte_size}
                  </div>
                  {Object.keys(pageQ.data.frontmatter ?? {}).length > 0 && (
                    <details style={{ marginBottom: 8 }}>
                      <summary
                        style={{
                          cursor: "pointer",
                          fontSize: 12,
                          color: "#374151",
                        }}
                      >
                        frontmatter (
                        {Object.keys(pageQ.data.frontmatter ?? {}).length} keys)
                      </summary>
                      <pre
                        style={{
                          background: "#f9fafb",
                          padding: 8,
                          margin: "8px 0 0",
                          fontSize: 11,
                          overflowX: "auto",
                          borderRadius: 4,
                        }}
                      >
                        {JSON.stringify(pageQ.data.frontmatter, null, 2)}
                      </pre>
                    </details>
                  )}
                  <pre
                    style={{
                      background: "#f9fafb",
                      padding: 12,
                      margin: 0,
                      fontSize: 12,
                      lineHeight: 1.5,
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      maxHeight: 480,
                      overflowY: "auto",
                      borderRadius: 4,
                      fontFamily:
                        "ui-monospace, SFMono-Regular, Menlo, monospace",
                    }}
                  >
                    {pageQ.data.body}
                  </pre>
                </>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
