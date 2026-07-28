import { useCallback, useEffect, useMemo, useState } from "react";
import { periodLabel, renderTextBlocks } from "../lib/reportText";

/**
 * 발송 운용보고 리더 (모달) — 카드 클릭 시 본문 열람.
 * 기본 = 원본 캡쳐 PNG(발송된 디자인 그대로), 캡쳐 없으면 추출 텍스트.
 * ←/→ 이전·다음 기간, ESC 닫기, 배경 클릭 닫기.
 */

export type FileRow = {
  filename: string;
  rel_path: string;
  kind: string;
  mail_date: string;
  mail_subject: string;
  has_text: boolean;
  text_chars: number;
  preview_pages: number;
  preview_rev: number;   // 캡쳐 세대 (mtime) — img URL 캐시 우회용
  category: string;      // main=본문 / appendix=부속자료
};
export type PeriodRow = { period: string; files: FileRow[] };
export type GeneratedRow = { period: string; comment: string; approved_at: string };

type Mode = "preview" | "text" | "gen";

export default function SentReportReader({
  fundCode, periods, index, generated, onNav, onClose,
}: {
  fundCode: string;
  periods: PeriodRow[];
  index: number;
  generated?: GeneratedRow;
  onNav: (nextIndex: number) => void;
  onClose: () => void;
}) {
  const row = periods[index];
  const [fileIdx, setFileIdx] = useState(0);
  const [mode, setMode] = useState<Mode>("preview");
  const [text, setText] = useState("");
  const [textErr, setTextErr] = useState("");
  // 캡쳐 PNG 가 DRM 래핑되어 브라우저가 렌더하지 못하는 경우 안내로 대체
  const [previewBroken, setPreviewBroken] = useState(false);
  // 캡쳐 확대 배율 — 1 = 모달 폭에 맞춤. 늘리면 컨테이너에서 가로 스크롤로 훑어본다.
  const [zoom, setZoom] = useState(1);

  const file: FileRow | undefined = row?.files[fileIdx];
  const { big, small } = periodLabel(row?.period ?? "");

  // 기간 이동 시 파일 선택 초기화 + 표시 모드 재결정 (캡쳐 없으면 텍스트)
  useEffect(() => {
    setFileIdx(0);
    setText("");
    setTextErr("");
    setPreviewBroken(false);
    setZoom(1);
  }, [index]);

  useEffect(() => {
    if (!file) return;
    setMode(file.preview_pages > 0 ? "preview" : file.has_text ? "text" : "preview");
  }, [file]);

  // 텍스트 모드 진입 시 지연 로드
  useEffect(() => {
    if (mode !== "text" || !file || !file.has_text) return;
    let alive = true;
    setText("");
    setTextErr("");
    fetch(`/api/funds/${fundCode}/sent-reports/text?rel_path=${encodeURIComponent(file.rel_path)}`)
      .then((r) => r.json())
      .then((d) => { if (alive) setText(d.text ?? ""); })
      .catch((e) => { if (alive) setTextErr(String(e)); });
    return () => { alive = false; };
  }, [mode, file, fundCode]);

  const go = useCallback((delta: number) => {
    const next = index + delta;
    if (next >= 0 && next < periods.length) onNav(next);
  }, [index, periods.length, onNav]);

  // 키보드: ESC 닫기 / ←→ 기간 이동
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft") go(-1);   // 최신 방향
      else if (e.key === "ArrowRight") go(1);   // 과거 방향
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, onClose]);

  // 배경 스크롤 잠금
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);

  const isPdf = useMemo(() => !!file && file.filename.toLowerCase().endsWith(".pdf"), [file]);

  if (!row) return null;

  return (
    <div className="srr-backdrop" onClick={onClose}>
      <div className="srr-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="srr-head">
          {/* periods 는 최신순 — 왼쪽=최신(index-1), 오른쪽=과거(index+1). 키보드도 동일 */}
          <button type="button" className="nav" disabled={index <= 0}
            onClick={() => go(-1)} title="최신 기간 (←)">◀</button>
          <div className="ttl">
            <span className="pd">{big}</span>
            <span className="yr num">{small}</span>
            <span className="fc">{fundCode}</span>
            {file && <span className="kd">{file.kind}</span>}
          </div>
          <button type="button" className="nav" disabled={index >= periods.length - 1}
            onClick={() => go(1)} title="과거 기간 (→)">▶</button>
          <button type="button" className="close" onClick={onClose} title="닫기 (ESC)">✕</button>
        </div>

        {/* 한 기간에 파일이 여럿이면 파일 탭 */}
        {row.files.length > 1 && (
          <div className="srr-files">
            {row.files.map((f, i) => (
              <button key={f.rel_path} type="button"
                className={i === fileIdx ? "on" : ""}
                title={f.filename}
                onClick={() => setFileIdx(i)}>{f.filename}</button>
            ))}
          </div>
        )}

        <div className="srr-bar">
          {file && file.preview_pages > 0 && (
            <button type="button" className={mode === "preview" ? "on" : ""}
              onClick={() => setMode("preview")}>원본 ({file.preview_pages}p)</button>
          )}
          {file?.has_text && (
            <button type="button" className={mode === "text" ? "on" : ""}
              onClick={() => setMode("text")}>텍스트</button>
          )}
          {generated && (
            <button type="button" className={mode === "gen" ? "on" : ""}
              onClick={() => setMode("gen")}>생성 코멘트</button>
          )}
          <span className="sp" />
          {/* 캡쳐 확대 — 원문을 그대로 키워 보는 게 텍스트 변환보다 읽기 낫다(2026-07-28) */}
          {mode === "preview" && !previewBroken && (file?.preview_pages ?? 0) > 0 && (
            <span className="zoom">
              <button type="button" onClick={() => setZoom((z) => Math.max(1, +(z - 0.25).toFixed(2)))}
                disabled={zoom <= 1} title="축소">−</button>
              <span className="lv">{Math.round(zoom * 100)}%</span>
              <button type="button" onClick={() => setZoom((z) => Math.min(4, +(z + 0.25).toFixed(2)))}
                disabled={zoom >= 4} title="확대">+</button>
              <button type="button" onClick={() => setZoom(1)} disabled={zoom === 1}>맞춤</button>
            </span>
          )}
          {file && isPdf && (
            <a href={`/api/funds/${fundCode}/sent-reports/file?rel_path=${encodeURIComponent(file.rel_path)}&inline=true`}
              target="_blank" rel="noreferrer"><button type="button">새 탭에서 PDF</button></a>
          )}
          {/* '원본 다운로드' 제거 (2026-07-28) — 원본은 DRM 이라 사외 client 는 열 수 없다.
              열람 경로는 캡쳐 이미지로 단일화. 사내에서 원본이 필요하면 메일/파일서버로. */}
        </div>

        <div className="srr-body">
          {mode === "preview" && file && file.preview_pages > 0 && !previewBroken && (
            <div className="srr-pages" style={{ "--z": zoom } as React.CSSProperties}>
              {Array.from({ length: file.preview_pages }, (_, i) => (
                <img key={i} loading="lazy" alt={`${file.filename} p${i + 1}`}
                  title="더블클릭: 확대 / 되돌리기"
                  onDoubleClick={() => setZoom((z) => (z > 1 ? 1 : 2))}
                  onError={() => { if (i === 0) setPreviewBroken(true); }}
                  src={`/api/funds/${fundCode}/sent-reports/preview?rel_path=${encodeURIComponent(file.rel_path)}&page=${i + 1}&v=${file.preview_rev}`} />
              ))}
            </div>
          )}
          {mode === "preview" && previewBroken && (
            <div className="srr-empty">
              원본 캡쳐 이미지가 문서보안(DRM)으로 래핑돼 브라우저에서 표시할 수 없습니다.
              {file?.has_text && " 텍스트 탭을 이용하거나,"} 원본을 다운로드해 열어보세요.
              <div className="sub">(해결: PC 에서 캡쳐 재생성 — 클립보드 경유 저장 필요)</div>
            </div>
          )}
          {mode === "preview" && file && file.preview_pages === 0 && (
            <div className="srr-empty">
              원본 캡쳐가 없습니다{isPdf ? " — 위 '새 탭에서 PDF' 로 열람하세요." : "."}
              {file.has_text && " 텍스트 탭을 이용하세요."}
            </div>
          )}
          {mode === "text" && (
            textErr ? <div className="srr-empty">텍스트 로드 실패: {textErr}</div>
              : text ? <div className="srr-doc">{renderTextBlocks(text)}</div>
                : <div className="srr-empty">불러오는 중…</div>
          )}
          {mode === "gen" && generated && (
            <div className="srr-doc">
              <div className="srr-genmeta">생성 코멘트 (Admin 승인 {generated.approved_at.slice(0, 10)})</div>
              {renderTextBlocks(generated.comment)}
            </div>
          )}
        </div>

        <div className="srr-foot">
          <span className="fn" title={file?.mail_subject}>{file?.filename}</span>
          {file?.mail_date && <span className="dt num">발송 {file.mail_date}</span>}
          <span className="hint">← → 기간 이동 · ESC 닫기</span>
        </div>
      </div>
    </div>
  );
}
