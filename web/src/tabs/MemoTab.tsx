import { useCallback, useEffect, useState } from "react";

/**
 * 메모 탭 (2026-07-14 신설, 관리자 전용).
 * 자유 노트 여러 개 — 서버 파일(data/memos.json) 저장이라 LAN 어느 PC 에서든 공유.
 * 좌측 목록 + 우측 편집기. 저장은 명시 버튼(수정 중 dirty 표시).
 */
type Memo = { id: string; title: string; content: string; created_at: string; updated_at: string };

const S = {
  root: { display: "flex", gap: 16, alignItems: "flex-start" } as const,
  list: { width: 260, flexShrink: 0, border: "1px solid #e5e7eb", borderRadius: 6, overflow: "hidden" } as const,
  item: (on: boolean) => ({
    padding: "8px 10px", cursor: "pointer", borderBottom: "1px solid #f1f2f4",
    background: on ? "#eef2ff" : "#fff",
  }),
  editor: { flex: 1, minWidth: 0 } as const,
  btn: {
    padding: "5px 12px", fontSize: 13, border: "1px solid #d1d5db",
    background: "#fff", borderRadius: 4, cursor: "pointer",
  } as const,
};

export default function MemoTab() {
  const [memos, setMemos] = useState<Memo[]>([]);
  const [sel, setSel] = useState<string>("");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(async (keepSel?: string) => {
    const r = await fetch("/api/admin/memos");
    const d = await r.json();
    setMemos(d.memos);
    const target = keepSel ?? sel;
    const cur = d.memos.find((m: Memo) => m.id === target) ?? d.memos[0];
    if (cur) {
      setSel(cur.id); setTitle(cur.title); setContent(cur.content);
    } else {
      setSel(""); setTitle(""); setContent("");
    }
    setDirty(false);
  }, [sel]);
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (m: Memo) => {
    if (dirty && !window.confirm("저장하지 않은 변경이 있습니다. 이동할까요?")) return;
    setSel(m.id); setTitle(m.title); setContent(m.content); setDirty(false); setMsg("");
  };

  const create = async () => {
    const r = await fetch("/api/admin/memos", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "새 메모", content: "" }),
    });
    const d = await r.json();
    await load(d.id);
    setMsg("");
  };

  const save = async () => {
    if (!sel) return;
    const r = await fetch(`/api/admin/memos/${sel}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, content }),
    });
    if (r.ok) { setMsg("✔ 저장됨"); await load(sel); }
    else { const d = await r.json().catch(() => null); setMsg(`✖ ${d?.detail ?? r.status}`); }
  };

  const remove = async () => {
    if (!sel || !window.confirm("이 메모를 삭제할까요?")) return;
    await fetch(`/api/admin/memos/${sel}`, { method: "DELETE" });
    await load("");
    setMsg("");
  };

  return (
    <section style={S.root}>
      <div style={S.list}>
        <div style={{ padding: 8, borderBottom: "1px solid #e5e7eb", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <b style={{ fontSize: 13 }}>메모 ({memos.length})</b>
          <button style={S.btn} onClick={create}>+ 새 메모</button>
        </div>
        {memos.length === 0 && <div style={{ padding: 12, color: "#98a2b3", fontSize: 13 }}>메모 없음</div>}
        {memos.map((m) => (
          <div key={m.id} style={S.item(m.id === sel)} onClick={() => pick(m)}>
            <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {m.title || "(제목 없음)"}
            </div>
            <div style={{ fontSize: 11, color: "#98a2b3" }}>{m.updated_at}</div>
          </div>
        ))}
      </div>

      <div style={S.editor}>
        {!sel ? (
          <div style={{ color: "#98a2b3", padding: 24 }}>좌측에서 메모를 선택하거나 "+ 새 메모"를 누르세요.</div>
        ) : (
          <>
            <div style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center" }}>
              <input
                value={title}
                onChange={(e) => { setTitle(e.target.value); setDirty(true); }}
                placeholder="제목"
                style={{ flex: 1, padding: "6px 10px", fontSize: 14, fontWeight: 600, border: "1px solid #d1d5db", borderRadius: 4 }}
              />
              <button style={{ ...S.btn, background: dirty ? "#1f2937" : "#fff", color: dirty ? "#fff" : "#374151" }} onClick={save}>
                저장{dirty ? " *" : ""}
              </button>
              <button style={{ ...S.btn, color: "#b42318" }} onClick={remove}>삭제</button>
              {msg && <span style={{ fontSize: 12, color: "#667085" }}>{msg}</span>}
            </div>
            <textarea
              value={content}
              onChange={(e) => { setContent(e.target.value); setDirty(true); }}
              placeholder="내용"
              rows={24}
              style={{ width: "100%", boxSizing: "border-box", padding: 10, fontSize: 13, lineHeight: 1.6, border: "1px solid #d1d5db", borderRadius: 4, fontFamily: "inherit", resize: "vertical" }}
            />
          </>
        )}
      </div>
    </section>
  );
}
