# -*- coding: utf-8 -*-
"""R9-B.2 — CLI for wiki_context_pack_builder.

Read-only. LLM 호출 0. debate prompt 미주입. 운영 파일 변경 0.

사용:
    python -m market_research.tools.build_wiki_context_pack \
        --period 2026-04 --stage market_debate \
        --output debug/wiki_context_pack/r9b2_2026-04_market.json

기본 output 경로:
    debug/wiki_context_pack/r9b2_{period}_{stage}.json
    debug/wiki_context_pack/r9b2_{period}_{stage}.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# repo root 기준 — market_research/tools/* 에서 두 단계 올라간다
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DEBUG_DIR = _REPO_ROOT / "debug" / "wiki_context_pack"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="R9-B.2 wiki context pack builder (read-only / debug-only)"
    )
    p.add_argument("--period", required=True,
                   help="period_key. monthly: YYYY-MM (e.g. 2026-04). "
                        "quarterly: YYYY-QX (e.g. 2026-Q1) — R9-B.5.")
    p.add_argument("--period-type", default="monthly",
                   choices=("monthly", "quarterly"),
                   help="R9-B.5: 'quarterly' 시 period 가 YYYY-QX 형식이면 "
                        "자동 unpacking, 또는 --period-keys 로 명시.")
    p.add_argument("--period-keys", default=None,
                   help="R9-B.5 quarterly: monthly period_keys CSV "
                        "(예 '2026-01,2026-02,2026-03'). --period-type=monthly "
                        "와 함께 사용 불가.")
    p.add_argument("--stage", default="market_debate",
                   choices=("market_debate", "fund_comment",
                            "quarterly_debate", "admin_preview"),
                   help="debate stage (default market_debate)")
    p.add_argument("--fund-code", default=None,
                   help="fund_code (required for fund_comment stage)")
    p.add_argument("--max-pages", type=int, default=12,
                   help="max selected pages per directory (default 12)")
    p.add_argument("--body-excerpt-chars", type=int, default=700,
                   help="per-page excerpt cap (default 700)")
    p.add_argument("--include-debate-memory", action="store_true",
                   help="opt-in 06_Debate_Memory (admin_preview / dry-run)")
    p.add_argument("--output", default=None,
                   help="JSON output path. default: "
                        "debug/wiki_context_pack/r9b2_{period}_{stage_short}.json")
    p.add_argument("--no-report", action="store_true",
                   help="skip the .md dry-run report next to the JSON")
    return p.parse_args(argv)


def _stage_short(stage: str) -> str:
    return {
        "market_debate": "market",
        "fund_comment": "fund",
        "quarterly_debate": "quarterly",
        "admin_preview": "admin",
    }.get(stage, stage)


def _default_output_path(period: str, stage: str, fund_code: str | None) -> Path:
    DEFAULT_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    short = _stage_short(stage)
    if fund_code:
        return DEFAULT_DEBUG_DIR / f"r9b2_{period}_{short}_{fund_code}.json"
    return DEFAULT_DEBUG_DIR / f"r9b2_{period}_{short}.json"


def _render_report(pack: dict) -> str:
    st = pack["source_trace"]
    lines: list[str] = [
        f"# R9-B.2 Wiki Context Pack — Dry-run Report",
        "",
        f"- period_key: `{pack['period_key']}` ({pack['period_type']})",
        f"- window: `{pack['window_start']} ~ {pack['window_end']}`",
        f"- as_of_date: `{pack['as_of_date']}`",
        f"- stage: `{pack['stage']}`",
        f"- fund_code: `{pack.get('fund_code')}`",
        f"- generated_at: `{pack['generated_at']}`",
        f"- schema_version: `{pack['schema_version']}`",
        "",
        "## Coverage",
        "",
        "| metric | value |",
        "|---|---|",
        f"| wiki_pages_considered | {st['wiki_pages_considered']} |",
        f"| wiki_pages_selected | {st['wiki_pages_selected']} |",
        f"| 08_Claims selected | {st['selected_by_directory'].get('08_Claims', 0)} |",
        f"| claim_store selected | {st['claim_store_selected_count']} |",
        f"| claim wiki matched | {st['matched_wiki_claim_count']} |",
        f"| claim_store_to_wiki_join_rate | {st['claim_store_to_wiki_join_rate']} |",
        f"| source_cutoff_violations | {st['source_cutoff_violations']} |",
        "",
        "## Selected by directory",
        "",
    ]
    for d, n in sorted(st["selected_by_directory"].items()):
        lines.append(f"- `{d}` — {n}")
    lines += ["", "## source_type distribution", ""]
    for k, v in sorted(st["source_type_counts"].items()):
        lines.append(f"- `{k}` — {v}")
    lines += ["", "## Top selected wiki pages", ""]
    for p in st["selected_wiki_paths"][:20]:
        lines.append(f"- `{p}`")
    if len(st["selected_wiki_paths"]) > 20:
        lines.append(f"- ... ({len(st['selected_wiki_paths']) - 20} more)")
    lines += ["", "## Warnings", ""]
    if not pack["warnings"]:
        lines.append("- (none)")
    else:
        for w in pack["warnings"]:
            wt = w.get("warning_type", "?")
            other = {k: v for k, v in w.items() if k != "warning_type"}
            lines.append(f"- **{wt}** — `{json.dumps(other, ensure_ascii=False)}`")
    lines += ["", "## Invariants",
              "",
              "- LLM calls: **0**",
              "- debate prompt: **not injected** (R9-B.2 is debug-only)",
              "- operational files changed: **none**",
              "- claim_store / regime_memory / report_output: **read-only**",
              ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from market_research.report.wiki_context_pack_builder import (
        build_wiki_context_pack,
    )

    # R9-B.5 period_keys CSV parsing + 정합성 가드
    pk_csv = getattr(args, "period_keys", None)
    pk_list: list[str] | None = None
    if pk_csv:
        pk_list = [s.strip() for s in pk_csv.split(",") if s.strip()]
    ptype = getattr(args, "period_type", "monthly")
    if ptype == "monthly" and pk_list:
        raise SystemExit(
            "[period_keys] --period-keys 는 --period-type=quarterly 와만 사용 가능"
        )
    pack = build_wiki_context_pack(
        period_key=args.period,
        period_type=ptype,
        period_keys=pk_list,
        stage=args.stage,
        fund_code=args.fund_code,
        max_pages=args.max_pages,
        body_excerpt_chars=args.body_excerpt_chars,
        include_debate_memory=args.include_debate_memory,
    )

    out_path = Path(args.output) if args.output else _default_output_path(
        args.period, args.stage, args.fund_code,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(pack, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"[r9b2] wrote pack: {out_path}")
    if not args.no_report:
        md_path = out_path.with_suffix(".md")
        md_path.write_text(_render_report(pack), encoding="utf-8")
        print(f"[r9b2] wrote report: {md_path}")

    st = pack["source_trace"]
    print(f"[r9b2] considered={st['wiki_pages_considered']} "
          f"selected={st['wiki_pages_selected']} "
          f"claim_store={st['claim_store_selected_count']} "
          f"matched={st['matched_wiki_claim_count']} "
          f"join_rate={st['claim_store_to_wiki_join_rate']} "
          f"cutoff_violations={st['source_cutoff_violations']} "
          f"warnings={len(pack['warnings'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
