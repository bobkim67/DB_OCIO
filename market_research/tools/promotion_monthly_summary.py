# -*- coding: utf-8 -*-
"""R9-A.17 — Claim group monthly summary CLI entrypoint (LLM 0).

R9-A.14 G1 canonical_group_id 기준으로 multi-run claim raw payload 를
load → `build_claim_group_monitoring_summary` 호출 → diagnostics 영역에
JSON + Markdown 보고서 저장.

운영 daily_update.py 무변경 / 운영 ledger schema 무변경. 본 entrypoint 는
opt-in: 사용자가 명시적으로 실행할 때만 동작.

사용:
    python -m market_research.tools.promotion_monthly_summary \\
        --raw debug/claims/out/r9a11_raw_claims_20260513_105537.jsonl \\
        [--period 2026-04] \\
        [--out-dir debug/claims/out]

워크오더 §3 — 운영 반영 전 단계는 diagnostics 영역 (gitignored) 유지.

invariants:
    - LLM 호출 0
    - 운영 4 md5 + 08_Claims + ledger 변경 0
    - 입력 jsonl 의 stored canonical_group_id 는 R9-A.14 G1 정의로 재계산
      (R9-A.11 raw 의 R9-A.8 stored gid 와 같은 outdated 케이스 보정)
    - 결과는 gitignored 영역 (debug/claims/out/) 만
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from market_research.analyze.claim_extractor import (  # noqa: E402
    compute_canonical_group_id,
)
from market_research.pipeline.claim_group_monitoring import (  # noqa: E402
    DEFAULT_STABLE_MIN_RUNS,
    DEFAULT_STRONG_MIN_RUNS,
    build_claim_group_monitoring_summary,
    write_monitoring_artifacts,
)


def _recompute_group_id(claim: dict, period: str) -> str:
    """R9-A.14 G1 정의로 group_id 재계산.

    R9-A.11 raw jsonl 등의 stored canonical_group_id 는 그 시점 (R9-A.8/A.12
    이전 정의) 으로 산정되어 있을 수 있어 본 entrypoint 에서 항상 재계산.
    """
    return compute_canonical_group_id(
        period,
        claim.get("claim_text") or "",
        claim.get("affected_assets") or [],
        source_evidence_ids=claim.get("source_evidence_ids") or [],
        direction=claim.get("direction") or "unknown",
        horizon=claim.get("horizon") or "unknown",
        claim_type=claim.get("claim_type") or "outlook_view",
    )


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="R9-A.17 — Claim group monthly monitoring summary "
                    "(diagnostics 영역만, LLM 0)"
    )
    parser.add_argument(
        "--raw", required=True,
        help="Input raw claims jsonl path (R9-A.11 raw 또는 daily/monthly batch jsonl)",
    )
    parser.add_argument(
        "--period", default="2026-04",
        help="Period (YYYY-MM) — group_id 재계산 시 사용",
    )
    parser.add_argument(
        "--out-dir", default="debug/claims/out",
        help="Output directory (gitignored, diagnostics 전용 — 워크오더 §3)",
    )
    parser.add_argument(
        "--stable-min-runs", type=int, default=DEFAULT_STABLE_MIN_RUNS,
    )
    parser.add_argument(
        "--strong-min-runs", type=int, default=DEFAULT_STRONG_MIN_RUNS,
    )
    parser.add_argument(
        "--no-recompute-group-id", action="store_true",
        help="raw jsonl 의 stored canonical_group_id 그대로 사용 (default OFF — "
             "재계산이 안전한 default). R9-A.11 raw 처럼 outdated 정의의 "
             "stored gid 가 있다면 재계산 권장.",
    )
    args = parser.parse_args(argv)

    raw_path = Path(args.raw).resolve()
    if not raw_path.exists():
        raise SystemExit(f"raw jsonl 부재: {raw_path}")

    out_dir = (REPO / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = _load_jsonl(raw_path)
    print(f"Loaded: {len(rows)} rows from {raw_path}")

    # Recompute group_id with current R9-A.14 G1 definition (default).
    if not args.no_recompute_group_id:
        for r in rows:
            r["canonical_group_id"] = _recompute_group_id(r, args.period)
        print(f"Recomputed canonical_group_id with R9-A.14 G1 definition")

    summary = build_claim_group_monitoring_summary(
        rows,
        stable_min_runs=args.stable_min_runs,
        strong_min_runs=args.strong_min_runs,
    )

    print()
    print("─" * 72)
    print("Summary")
    print("─" * 72)
    print(f"  total claims                  : {summary['total_claims']}")
    print(f"  total runs                    : {summary['total_runs']}")
    print(f"  total groups                  : {summary['total_groups']}")
    print(f"  stable (run≥{summary['stable_min_runs']})        "
          f"      : {summary['stable_candidates']}")
    print(f"  strong stable (run≥{summary['strong_min_runs']}) "
          f"      : {summary['strong_stable_candidates']}")
    print(f"  all-run groups               : {summary['all_run_groups']}")
    print(f"  promoted groups              : {summary['promoted_groups']}")
    print(f"  overmerge warning count      : "
          f"{summary['within_run_duplicate_count']}")

    artifacts = write_monitoring_artifacts(
        out_dir, args.period, raw_path.name, summary,
    )

    print()
    print("=" * 72)
    print("Artifacts (diagnostics 영역 — gitignored, 운영 영역 변경 0)")
    print("=" * 72)
    print(f"  summary JSON: {artifacts['json']}")
    print(f"  summary MD :  {artifacts['md']}")
    print(f"  LLM cost: $0.00")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
