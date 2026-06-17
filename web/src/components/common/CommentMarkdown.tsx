import { useMemo, type CSSProperties } from "react";

// 시장 코멘트는 LLM 이 줄바꿈 없이 한 덩어리로 생성한다(\n 0개). 읽기 편하게
// 클라이언트에서 **자산 주제(asset)별**로 문단을 나눈다: 문장이 다루는 자산군이
// 바뀌는 지점에서만 문단을 끊고, 같은/미상 자산 문장은 이어 붙인다. 열거
// (첫째·둘째…) 블록은 하나로 유지. **소제목**(분기 코멘트)은 별도 헤더. 데이터 불변.

const PARA: CSSProperties = { margin: "0 0 12px", lineHeight: 1.75 };
const SUBHEAD: CSSProperties = {
  fontWeight: 700,
  margin: "18px 0 8px",
  fontSize: 14,
  color: "#111827",
};

type Block = { kind: "head" | "para"; text: string };

// 자산군 앵커 — 문장에서 먼저 매칭되는 자산이 그 문장의 주제. 순서 = 우선순위.
const ASSET_ANCHORS: [string, RegExp][] = [
  ["국내주식", /코스피|코스닥|삼성전자|sk하이닉스|하이닉스|국내\s*증시|국내\s*주식|국내주식|국장/i],
  ["해외주식", /나스닥|s&p|에스앤피|미국\s*주식|빅테크|해외\s*주식|반도체주|엔비디아|필라델피아|다우/i],
  ["국내채권", /국고채|원화\s*채권|한국은행|한은|금통위|국내\s*채권/i],
  ["해외채권", /미국채|미\s*국채|국채|ust|treasury|하이일드|\bhy\b|크레딧|회사채|신용\s*스프레드|investment\s*grade|\big\b|해외\s*채권|연준|fed|fomc|사모신용|사모대출/i],
  ["환율", /환율|달러\/원|원·달러|원\/달러|달러원|dxy|원화\s*약세|원화\s*강세|위안|엔화/i],
  ["대체", /금값|금\s*가격|금\s*시장|금\s*선물|국제\s*금|원자재|유가|원유|wti|브렌트|리츠|reit|귀금속|구리|에너지\s*가격/i],
  ["유동성", /유동성|현금성|mmf|단기\s*금리|콜금리/i],
];

// 열거 문장(첫째·둘째…)은 자산이 바뀌어도 같은 블록으로 유지.
const ENUM_LEAD = /^(첫째|둘째|셋째|넷째|다섯째|여섯째|일곱째)/;
// 전망/종합 도입 문장은 자산과 무관하게 새 문단(전망 블록)으로 분리.
const OUTLOOK_LEAD = /(향후|핵심 변수|확인해야 할|관찰해야 할|체크포인트|종합하면|종합적으로|전망 요약)/;

function assetOf(sentence: string): string | null {
  for (const [name, re] of ASSET_ANCHORS) {
    if (re.test(sentence)) return name;
  }
  return null;
}

function splitSentences(text: string): string[] {
  // 종결어미('다.'/'요.'/'음.') 뒤 공백에서만 분리. lookbehind 라 마침표 보존,
  // 숫자 소수점·약어는 잘리지 않는다.
  return text
    .split(/(?<=[다요음]\.)\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function groupByAsset(sentences: string[]): string[] {
  const paras: string[] = [];
  let cur: string[] = [];
  let curAsset: string | null = null;
  for (const s of sentences) {
    const a = assetOf(s);
    const isEnum = ENUM_LEAD.test(s);
    const isOutlook = OUTLOOK_LEAD.test(s) && !isEnum;
    // 새 문단 조건: (자산 전환 && 열거 아님) 또는 (전망 도입 문장). 열거는 유지.
    if (cur.length > 0 && ((a && a !== curAsset && !isEnum) || isOutlook)) {
      paras.push(cur.join(" "));
      cur = [];
      if (isOutlook) curAsset = null; // 전망 블록 진입 — 이후 자산 언급으로 즉시 재분리 방지
    }
    cur.push(s);
    // 열거 문장의 자산은 curAsset 을 갱신하지 않아 리스트가 쪼개지지 않음.
    if (a && !isEnum) curAsset = a;
  }
  if (cur.length) paras.push(cur.join(" "));
  return paras;
}

function parseBlocks(raw: string): Block[] {
  const blocks: Block[] = [];
  // **bold** 토큰 분리 — split 결과의 홀수 인덱스가 bold 내용(소제목).
  const parts = raw.split(/\*\*(.+?)\*\*/g);
  parts.forEach((part, idx) => {
    if (idx % 2 === 1) {
      const t = part.trim();
      if (t) blocks.push({ kind: "head", text: t });
      return;
    }
    const clean = part.replace(/(^|\s)#{1,3}\s+/g, " ").trim();
    if (!clean) return;
    for (const para of groupByAsset(splitSentences(clean))) {
      blocks.push({ kind: "para", text: para });
    }
  });
  return blocks;
}

export default function CommentMarkdown({ text }: { text: string }) {
  const blocks = useMemo(() => parseBlocks(text), [text]);
  return (
    <>
      {blocks.map((b, i) =>
        b.kind === "head" ? (
          <div key={i} style={SUBHEAD}>
            {b.text}
          </div>
        ) : (
          <p key={i} style={PARA}>
            {b.text}
          </p>
        ),
      )}
    </>
  );
}
