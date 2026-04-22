import type { BaseMeta } from "../../api/endpoints";

interface Props {
  meta: BaseMeta;
}

export default function MetaBadge({ meta }: Props) {
  const color = meta.is_fallback
    ? "#d97706"            // orange — fallback
    : meta.source === "mixed"
    ? "#ca8a04"            // yellow — mixed (부분 실패)
    : "#059669";           // green — db

  const label = meta.is_fallback
    ? "⚠ fallback"
    : meta.source === "mixed"
    ? "mixed"
    : "db";

  return (
    <div style={{ display: "inline-flex", flexDirection: "column", gap: 4 }}>
      <span
        style={{
          display: "inline-block",
          padding: "2px 8px",
          borderRadius: 4,
          background: color,
          color: "white",
          fontSize: 12,
          fontWeight: 600,
          width: "fit-content",
        }}
      >
        {label}
        {meta.as_of_date ? ` · ${meta.as_of_date}` : ""}
      </span>

      {meta.sources.length > 0 && (
        <span style={{ fontSize: 11, color: "#6b7280" }}>
          {meta.sources
            .map(
              (s) =>
                `${s.component}=${s.kind}${s.note ? ` (${s.note})` : ""}`,
            )
            .join(" · ")}
        </span>
      )}

      {meta.warnings.length > 0 && (
        <ul
          style={{
            margin: 0,
            paddingLeft: 16,
            fontSize: 11,
            color: "#b45309",
          }}
        >
          {meta.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
