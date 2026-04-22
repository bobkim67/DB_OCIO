import { useState } from "react";
import { useMacro } from "../hooks/useMacro";
import MetaBadge from "../components/common/MetaBadge";
import MacroChart from "../components/charts/MacroChart";
import type { MacroSeriesDTO } from "../api/endpoints";

const KEY_OPTIONS = [
  { key: "PE", label: "PE (12M Fwd, S&P 500)" },
  { key: "EPS", label: "EPS (12M Fwd, S&P 500)" },
  { key: "USDKRW", label: "USD/KRW" },
];

function fmtValue(v: number, unit: MacroSeriesDTO["unit"]): string {
  if (unit === "pct") return `${(v * 100).toFixed(2)}%`;
  if (unit === "bp") return `${(v * 10000).toFixed(0)}bp`;
  if (unit === "krw" || unit === "usd") {
    return v.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  }
  if (unit === "ratio") return v.toFixed(2);
  return v.toFixed(2);
}

export default function MacroTab() {
  const [selected, setSelected] = useState<Set<string>>(
    new Set(KEY_OPTIONS.map((o) => o.key)),
  );
  const keys = Array.from(selected);
  const { data, isLoading, error } = useMacro(keys);

  const toggle = (k: string) => {
    const next = new Set(selected);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setSelected(next);
  };

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
        <h2 style={{ fontSize: 16, margin: 0 }}>매크로 지표</h2>
        {data && <MetaBadge meta={data.meta} />}
      </div>

      <div
        style={{
          display: "flex",
          gap: 14,
          marginBottom: 12,
          fontSize: 13,
        }}
      >
        {KEY_OPTIONS.map((opt) => (
          <label key={opt.key} style={{ cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={selected.has(opt.key)}
              onChange={() => toggle(opt.key)}
              style={{ marginRight: 6, verticalAlign: "middle" }}
            />
            {opt.label}
          </label>
        ))}
      </div>

      {keys.length === 0 ? (
        <div style={{ color: "#6b7280", padding: 16 }}>
          지표를 하나 이상 선택하세요.
        </div>
      ) : isLoading ? (
        <div>loading macro...</div>
      ) : error || !data ? (
        <div style={{ color: "#dc2626" }}>failed to load macro</div>
      ) : (
        <>
          {data.series.length > 0 && (
            <div
              style={{
                display: "flex",
                gap: 16,
                marginBottom: 12,
                padding: "8px 12px",
                background: "#f9fafb",
                borderRadius: 6,
                flexWrap: "wrap",
                fontSize: 13,
              }}
            >
              {data.series.map((s) => {
                const last = s.points[s.points.length - 1];
                return (
                  <div key={s.key}>
                    <span style={{ color: "#6b7280", marginRight: 4 }}>
                      {s.label}:
                    </span>
                    <span style={{ fontWeight: 600 }}>
                      {last ? fmtValue(last.value, s.unit) : "—"}
                    </span>
                    {last && (
                      <span
                        style={{
                          color: "#9ca3af",
                          marginLeft: 4,
                          fontSize: 11,
                        }}
                      >
                        ({last.date})
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <MacroChart series={data.series} />
        </>
      )}
    </section>
  );
}
