import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useAdminDebateStatus } from "../hooks/useAdminDebateStatus";
import { useAdminDebatePeriods } from "../hooks/useAdminDebatePeriods";
import { useFunds } from "../hooks/useFunds";
import MetaBadge from "../components/common/MetaBadge";
import type { DebateStatus } from "../api/endpoints";

const MARKET_OPTION = "_market";

const PRE_BOX: CSSProperties = {
  background: "#0f172a",
  color: "#e2e8f0",
  padding: 12,
  borderRadius: 6,
  fontSize: 12,
  lineHeight: 1.5,
  maxHeight: 360,
  overflow: "auto",
  margin: 0,
  whiteSpace: "pre",
};

const PILL: CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 999,
  fontSize: 12,
  fontWeight: 600,
};

function statusPill(s: DebateStatus | undefined): CSSProperties {
  switch (s) {
    case "approved":
      return { ...PILL, background: "#dcfce7", color: "#166534" };
    case "edited":
      return { ...PILL, background: "#fef3c7", color: "#92400e" };
    case "draft_generated":
      return { ...PILL, background: "#dbeafe", color: "#1e40af" };
    case "not_generated":
    default:
      return { ...PILL, background: "#f3f4f6", color: "#6b7280" };
  }
}

function check(b: boolean | undefined): string {
  return b ? "✓" : "—";
}

function PrettyJson({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <div style={{ color: "#6b7280", fontSize: 12 }}>없음</div>;
  }
  return <pre style={PRE_BOX}>{JSON.stringify(value, null, 2)}</pre>;
}

function CollapsibleJson({
  title,
  value,
  defaultOpen = false,
}: {
  title: string;
  value: unknown;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ marginTop: 12 }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          fontSize: 13,
          fontWeight: 600,
          padding: "4px 8px",
          background: "#f9fafb",
          border: "1px solid #e5e7eb",
          borderRadius: 4,
          cursor: "pointer",
          marginBottom: 6,
        }}
      >
        {open ? "▼" : "▶"} {title}
      </button>
      {open && <PrettyJson value={value} />}
    </div>
  );
}

export default function AdminDebateStatusPanel() {
  const periodsQuery = useAdminDebatePeriods();
  const fundsQuery = useFunds();

  const [period, setPeriod] = useState<string>("");
  const [fund, setFund] = useState<string>("");

  const periodOptions = useMemo(() => {
    return periodsQuery.data?.periods ?? [];
  }, [periodsQuery.data]);

  const fundOptions = useMemo(() => {
    const xs = fundsQuery.data?.data?.map((f) => f.code) ?? [];
    return [MARKET_OPTION, ...xs];
  }, [fundsQuery.data]);

  useEffect(() => {
    if (period === "" && periodOptions.length > 0) {
      setPeriod(periodOptions[0]);
    }
  }, [period, periodOptions]);

  useEffect(() => {
    if (fund === "" && fundOptions.length > 0) {
      setFund(fundOptions[0]);
    }
  }, [fund, fundOptions]);

  const statusQuery = useAdminDebateStatus(
    period || undefined,
    fund || undefined,
  );

  const data = statusQuery.data;

  return (
    <section>
      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <h2 style={{ fontSize: 16, margin: 0 }}>Admin · Debate Status</h2>
        {data && <MetaBadge meta={data.meta} />}
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
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            style={{ fontSize: 13, padding: "3px 6px", minWidth: 110 }}
            disabled={periodOptions.length === 0}
          >
            {periodOptions.length === 0 && (
              <option value="">(period 없음)</option>
            )}
            {periodOptions.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>

        <label>
          fund:&nbsp;
          <select
            value={fund}
            onChange={(e) => setFund(e.target.value)}
            style={{ fontSize: 13, padding: "3px 6px", minWidth: 110 }}
          >
            {fundOptions.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </label>

        {periodsQuery.isLoading && (
          <span style={{ fontSize: 12, color: "#6b7280" }}>
            periods loading…
          </span>
        )}
      </div>

      {statusQuery.isLoading ? (
        <div>loading debate status…</div>
      ) : statusQuery.error ? (
        <div
          style={{
            color: "#b91c1c",
            padding: 12,
            background: "#fef2f2",
            borderRadius: 6,
            fontSize: 13,
          }}
        >
          {(statusQuery.error as Error).message}
        </div>
      ) : !data ? (
        <div style={{ color: "#6b7280", padding: 16, fontSize: 13 }}>
          period와 fund를 선택하세요.
        </div>
      ) : (
        <>
          <div
            style={{
              display: "flex",
              gap: 16,
              alignItems: "center",
              padding: 12,
              background: "#f9fafb",
              border: "1px solid #e5e7eb",
              borderRadius: 6,
              marginBottom: 12,
              fontSize: 13,
              flexWrap: "wrap",
            }}
          >
            <div>
              status:&nbsp;
              <span style={statusPill(data.status)}>{data.status}</span>
            </div>
            <div>
              has_input: <strong>{check(data.has_input)}</strong>
            </div>
            <div>
              has_draft: <strong>{check(data.has_draft)}</strong>
            </div>
            <div>
              has_final: <strong>{check(data.has_final)}</strong>
            </div>
            <div style={{ color: "#6b7280", fontSize: 12 }}>
              {data.period} · {data.fund_code}
            </div>
          </div>

          <CollapsibleJson
            title="input_summary"
            value={data.input_summary}
            defaultOpen
          />
          <CollapsibleJson title="draft_body" value={data.draft_body} />
          <CollapsibleJson title="final_body" value={data.final_body} />
        </>
      )}
    </section>
  );
}
