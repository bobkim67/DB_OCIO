// 결제 예정 중 "원장 미반영"(해외 체결확인서에만 있는 건) 요약 — 카드 라벨/툴팁 (2026-08-03)
//
// 해외 거래는 브로커 SettleDate(체결 T+1)에야 원장에 잡히므로, 그 사이엔 비중·평가액
// 어디에도 나타나지 않는다. 반대로 국내 매입미지급금(source='ledger')은 이미 부채로
// 반영돼 있어 카드 대상이 아니다 — 카드는 "원장에 없는 것"만 말한다 (사용자 확정).
import type { PendingSettlementDTO } from "../api/endpoints";
import { secAlias } from "./securityAlias";

export interface UnreflectedSummary {
  count: number;
  label: string;    // 카드 문구
  detail: string;   // 툴팁 (건별 상세)
}

const eok = (v: number) => `${(v / 1e8).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}억`;

export function unreflectedSummary(
  list: PendingSettlementDTO[] | null | undefined,
): UnreflectedSummary | null {
  const mail = (list ?? []).filter((p) => p.source === "mail");
  if (mail.length === 0) return null;

  const sides = new Set(mail.map((p) => p.side));
  const what =
    sides.size === 1 ? (sides.has("매도") ? "해외 매도대금" : "해외 매수대금") : "해외 거래";
  // 라벨은 사실만 — 반영 예정일은 툴팁('해외거래는 체결 T+2에 반영')과
  // 하단 배너의 reflect_date 로 (2026-08-03 사용자 지시).
  const label = `${what} 미반영`;

  // 건별 1줄: · ticker(종목명) · 매도/매수 x주 · 금액 · 체결 · 결제 (2026-08-03 사용자 지정)
  const lines = mail.map((p) => {
    const nm = secAlias(p.item_nm);
    const head = p.ticker ? `${p.ticker}(${nm})` : nm;
    const qty = `${p.side}${p.qty ? ` ${p.qty.toLocaleString("ko-KR")}주` : ""}`;
    const native =
      p.ccy !== "KRW" && p.amount != null
        ? `${p.ccy} ${p.amount.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
        : p.amount_krw != null
          ? eok(p.amount_krw)
          : "—";
    const amount = native + (p.ccy !== "KRW" && p.amount_krw ? ` (약 ${eok(p.amount_krw)})` : "");
    return `· ${head} · ${qty} · ${amount} · 체결 ${p.trade_date ?? "—"} · 결제 ${p.settle_date ?? "—"}`;
  });

  const detail = ["해외거래는 체결 T+2에 반영", ...lines].join("\n");

  return { count: mail.length, label, detail };
}
