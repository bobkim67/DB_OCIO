# -*- coding: utf-8 -*-
"""R9-B.3 — Debate prompt preview (LLM-free dry-run).

Builds the shared debate context and renders the agent prompt without
calling any LLM. Surfaces R9-B.3 trace fields side-by-side so that
legacy vs wiki-context-pack-opt-in prompts can be compared.

사용:
    # legacy (default)
    python -m market_research.tools.preview_debate_prompt \\
        --period 2026-04 --agent bull

    # opt-in (builder 사용)
    python -m market_research.tools.preview_debate_prompt \\
        --period 2026-04 --use-wiki-context-pack

    # opt-in (외부 pack JSON load — schema/period 검증)
    python -m market_research.tools.preview_debate_prompt \\
        --period 2026-04 --use-wiki-context-pack \\
        --wiki-context-pack-path debug/wiki_context_pack/r9b2_2026-04_market.json

LLM 호출 0. 운영 wiki / claims / report_output / regime_memory 변경 0.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DEBUG_DIR = _REPO_ROOT / "debug" / "wiki_context_pack"
_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "R9-B.3 debate prompt preview (LLM-free). Compare legacy "
            "vs --use-wiki-context-pack prompts before committing to an "
            "actual debate run."
        )
    )
    p.add_argument("--period", required=True,
                   help="YYYY-MM, e.g. 2026-04 (monthly only)")
    p.add_argument("--agent", default="bull",
                   choices=("bull", "bear", "quant", "monygeek"),
                   help="agent persona to render (default: bull)")
    p.add_argument("--use-wiki-context-pack", action="store_true",
                   help="opt-in: inject wiki_context_pack as A. Wiki Primary "
                        "Context. default OFF (legacy parity).")
    p.add_argument("--wiki-context-pack-path", default=None,
                   help="path to pre-built pack JSON. valid only with "
                        "--use-wiki-context-pack. schema_version/period_key/"
                        "stage 검증 후 사용.")
    p.add_argument("--wiki-context-max-pages", type=int, default=12,
                   help="builder max_pages cap (default 12)")
    p.add_argument("--stage", default="market_debate",
                   choices=("market_debate", "quarterly_debate"),
                   help="stage (default market_debate)")
    p.add_argument("--output", default=None,
                   help="output path. default: "
                        "debug/wiki_context_pack/preview_{period}_{mode}.json")
    p.add_argument("--no-write", action="store_true",
                   help="stdout only — do not write any file.")
    return p.parse_args(argv)


def _load_pack_from_path(path_str: str) -> dict:
    p = Path(path_str)
    if not p.exists():
        raise SystemExit(f"[r9b3] pack path not found: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"[r9b3] failed to parse pack JSON: {p} — {e}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    m = _PERIOD_RE.match(args.period)
    if not m:
        raise SystemExit(
            f"[r9b3] --period must be YYYY-MM, got {args.period!r}"
        )
    year, month = int(m.group(1)), int(m.group(2))

    if args.wiki_context_pack_path and not args.use_wiki_context_pack:
        raise SystemExit(
            "[r9b3] --wiki-context-pack-path requires --use-wiki-context-pack"
        )

    # Lazy import — debate_engine 가 무거운 다운스트림 의존 보유. CLI 실행
    # 시점에만 load. read-only path 만 사용 (LLM 호출 0).
    from market_research.report import debate_engine as de

    # 1) build shared context (모든 raw block — news/indicators/graph/regime/...)
    context = de._build_shared_context(year, month, force_window_ids=None)

    # 2) opt-in 시 wiki pack 준비 + primary text 삽입
    prompt_context_mode = "legacy"
    wcp: dict[str, Any] | None = None
    wcp_trace: dict[str, Any] = {"wiki_context_pack_enabled": False}
    primary_text = ""
    if args.use_wiki_context_pack:
        period_key = args.period
        if args.wiki_context_pack_path:
            loaded = _load_pack_from_path(args.wiki_context_pack_path)
            de._validate_wiki_context_pack(
                loaded,
                expected_period=period_key,
                expected_stage=args.stage,
            )
            wcp = loaded
        else:
            wcp = de._build_wiki_context_pack_for_debate(
                period_key=period_key,
                stage=args.stage,
                fund_code=None,
                max_pages=args.wiki_context_max_pages,
            )
        primary_text = de._format_wiki_primary_context_for_prompt(wcp)
        wcp_trace = de._wiki_context_pack_trace(wcp)
        prompt_context_mode = "wiki_context_pack_opt_in"

    context["wiki_primary_context_text"] = primary_text
    context["_wiki_context_pack"] = wcp
    context["_prompt_context_mode"] = prompt_context_mode

    # 3) render prompt (no LLM call)
    prompt = de._build_agent_prompt(args.agent, context)

    # 4) compose preview payload
    raw_chars = (
        len(context.get("news_summary_text") or "")
        + len(context.get("indicators_text") or "")
        + len(context.get("timeseries_narrative_text") or "")
        + len(context.get("graph_paths_text") or "")
        + len(context.get("wiki_context_text") or "")
        + len(context.get("asset_coverage_text") or "")
    )
    payload = {
        "schema_version": "r9b-debate-preview-1.0.0",
        "period": args.period,
        "stage": args.stage,
        "agent": args.agent,
        "prompt_context_mode": prompt_context_mode,
        "wiki_primary_context_chars": len(primary_text),
        "raw_validation_context_chars": raw_chars,
        "prompt_chars_total": len(prompt),
        "trace": wcp_trace,
        "prompt": prompt,
        "wiki_primary_block_present": (
            de.WIKI_CONTEXT_PRIMARY_HEADING in prompt
        ),
        "raw_validation_heading_present": (
            de.WIKI_CONTEXT_RAW_HEADING in prompt
        ),
        "llm_calls": 0,
        "operational_files_changed": [],
    }

    # 5) print summary + optional write
    summary_keys = [
        "prompt_context_mode",
        "wiki_primary_context_chars",
        "raw_validation_context_chars",
        "prompt_chars_total",
        "wiki_primary_block_present",
        "raw_validation_heading_present",
        "llm_calls",
    ]
    for k in summary_keys:
        print(f"[r9b3] {k}: {payload[k]}")
    if wcp_trace.get("wiki_context_pack_enabled"):
        for tk in (
            "wiki_pages_selected",
            "wiki_source_type_counts",
            "selected_claim_ids",
            "selected_related_group_ids",
            "claim_store_to_wiki_join_rate",
            "source_cutoff_violations",
        ):
            print(f"[r9b3] trace.{tk}: {wcp_trace.get(tk)}")

    if args.no_write:
        return 0

    mode_short = "wcp" if args.use_wiki_context_pack else "legacy"
    out_path = (
        Path(args.output) if args.output
        else DEFAULT_DEBUG_DIR / f"preview_{args.period}_{mode_short}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"[r9b3] wrote preview: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
