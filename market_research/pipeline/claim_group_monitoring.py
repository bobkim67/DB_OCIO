# -*- coding: utf-8 -*-
"""R9-A.17 — Claim group monitoring (LLM 0, production utility).

R9-A.14 G1 canonical_group_id (period + evset + sorted_assets) 기준으로
multi-run claim extraction 결과를 누적 집계하는 production utility.

R9-A.16 debug smoke (`debug/claims/r9a16_group_monitoring_summary.py`) 의
aggregation logic 을 재사용 가능한 함수로 승격. 운영 daily/monthly batch
및 tools/ entrypoint 에서 호출 가능.

Public API:
    build_claim_group_monitoring_summary(claims, *, stable_min_runs=2,
                                          strong_min_runs=3,
                                          run_id_field="run_id",
                                          monitoring_mode="multi_run") -> dict
    render_monitoring_markdown(period, source, summary) -> str
    write_monitoring_artifacts(out_dir, period, source, summary,
                                *, ts=None) -> dict[str, Path]

Monitoring modes (R9-A.19):
    - "multi_run" (default): N-run aggregation 의도. stable candidate
      해석 valid. within_run_duplicate = overmerge warning.
    - "single_batch": daily_update 단일 batch 의도. stable candidate
      reference-only. within_run_duplicate = same-batch repeated group
      diagnostic (overmerge failure 아님).

Invariants:
    - LLM 호출 0
    - filesystem write 0 (호출측이 결과 저장)
    - claims 의 stored canonical_group_id 를 그대로 사용 (normalize_claim 통과
      가정). outdated group_id 처리는 호출측 책임.
    - 기존 promotion_quality.jsonl / ledger schema 변경 0

Output dict 구조:
    {
        "total_groups": int,
        "stable_candidates": int,         # run_count ≥ stable_min_runs
        "strong_stable_candidates": int,  # run_count ≥ strong_min_runs
        "within_run_duplicate_count": int,
        "promoted_groups": int,
        "all_run_groups": int,            # run_count == total_runs
        "total_claims": int,
        "total_runs": int,
        "runs": list[str],
        "groups": list[dict],             # sorted (워크오더 §5)
        "overmerge_warnings": list[dict],
        "stable_min_runs": int,
        "strong_min_runs": int,
    }

Group dict 구조: (워크오더 §2)
    {
        "canonical_group_id": str,
        "run_count": int,
        "claim_count": int,
        "first_seen_run": str | None,
        "last_seen_run": str | None,
        "runs_touched": list[str],
        "evidence_set_hash": str | None,
        "affected_assets": list[str],
        "promoted_count": int,
        "promoted_rate": float,
        "direction_distribution": dict[str, int],
        "horizon_distribution": dict[str, int],
        "claim_type_distribution": dict[str, int],
        "promotion_rule_distribution": dict[str, int],
        "representative_claim": str,
        "sample_claim_texts": list[str],
        "stable_candidate": bool,
        "strong_stable_candidate": bool,
        "has_direction_variance": bool,
        "has_horizon_variance": bool,
        "has_claim_type_variance": bool,
        "member_claim_ids": list[str],
        "overmerge_warning": bool,
    }
"""
from __future__ import annotations

import collections
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


# 워크오더 §2 stable thresholds (R9-A.16 기본값과 동일)
DEFAULT_STABLE_MIN_RUNS: int = 2
DEFAULT_STRONG_MIN_RUNS: int = 3

# 워크오더 §4 — sample claim texts per group (representative + alternates)
SAMPLE_TEXTS_PER_GROUP: int = 3

# R9-A.19 — Monitoring mode semantics
#
#   "multi_run":
#       - 여러 fresh Haiku run 의 결과를 합쳐 N-run aggregation
#       - run_id 가 각 run 마다 distinct 하게 부여됨
#       - stable_candidate (run_count ≥ stable_min_runs) 해석 valid
#       - within_run_duplicate = overmerge warning (같은 run 안에 같은 group)
#       - R9-A.7~A.17 의 원래 의도. promotion_monthly_summary entrypoint
#         같은 multi-run aggregation 호출자.
#
#   "single_batch":
#       - 단일 daily_update batch 의 결과만 요약 (run_id 단일)
#       - stable_candidate / strong_stable_candidate 해석 제한 — 참고값
#       - within_run_duplicate = same-batch repeated group diagnostic
#         (overmerge failure 아님 — 단순히 같은 batch 내에 같은 evset+
#         assets 의 claim 이 2회 이상 나왔다는 진단)
#       - daily_update.py `--enable-group-monitoring` 같은 호출자.
MONITORING_MODE_MULTI_RUN: str = "multi_run"
MONITORING_MODE_SINGLE_BATCH: str = "single_batch"
ALLOWED_MONITORING_MODES: frozenset[str] = frozenset({
    MONITORING_MODE_MULTI_RUN,
    MONITORING_MODE_SINGLE_BATCH,
})
DEFAULT_MONITORING_MODE: str = MONITORING_MODE_MULTI_RUN

# within_run_duplicate semantics labels (mode 별)
_WITHIN_DUP_SEMANTICS = {
    MONITORING_MODE_MULTI_RUN: "overmerge_warning",
    MONITORING_MODE_SINGLE_BATCH: "same_batch_repeated_group_diagnostic",
}

# run_count interpretation labels
_RUN_COUNT_INTERPRETATION = {
    MONITORING_MODE_MULTI_RUN:
        "run_count is # of distinct Haiku runs in which a group appears",
    MONITORING_MODE_SINGLE_BATCH:
        "run_count is always 1 for a single batch — stable_candidate "
        "thresholds are not meaningful, treat run_count/claim_count as "
        "reference-only diagnostic",
}


def _select_representative_claim(claims_in_group: list[dict]) -> str:
    """대표 claim_text 선택 (워크오더 §4 우선순위).

    1. promoted=True 중 가장 긴 text
    2. 전체 중 가장 긴 text (짧지 않은 것)
    3. 첫 등장 claim_text (안정성)
    """
    if not claims_in_group:
        return ""
    promoted = [c for c in claims_in_group if c.get("promoted")]
    pool = promoted if promoted else claims_in_group
    best = pool[0]
    best_len = len(best.get("claim_text") or "")
    for c in pool[1:]:
        L = len(c.get("claim_text") or "")
        if L > best_len:
            best = c
            best_len = L
    return best.get("claim_text") or ""


def _detect_overmerge_warnings(
    claims: list[dict],
    *,
    run_id_field: str = "run_id",
) -> list[dict]:
    """같은 run 안에서 같은 canonical_group_id 가 2개 이상 등장 시 warning.

    R9-A.14 G1 정의로는 0건 기대 (R9-A.16 fixture-level 검증).
    """
    by_run_group: dict[tuple, list[str]] = {}
    for c in claims:
        if not isinstance(c, dict):
            continue
        gid = c.get("canonical_group_id")
        if not gid:
            continue
        key = (c.get(run_id_field), gid)
        by_run_group.setdefault(key, []).append(c.get("claim_id"))
    warnings = []
    for (run, gid), cids in by_run_group.items():
        if len(cids) >= 2:
            warnings.append({
                "run_id": run,
                "canonical_group_id": gid,
                "duplicate_claim_count": len(cids),
                "claim_ids": cids,
            })
    return warnings


def _aggregate_groups(
    claims: list[dict],
    *,
    run_id_field: str = "run_id",
    overmerged_group_ids: set[str] | None = None,
) -> dict[str, dict]:
    """canonical_group_id 별 aggregation."""
    overmerged_group_ids = overmerged_group_ids or set()
    groups: dict[str, dict] = {}
    for c in claims:
        if not isinstance(c, dict):
            continue
        gid = c.get("canonical_group_id")
        if not gid:
            continue
        g = groups.get(gid)
        if g is None:
            g = {
                "canonical_group_id": gid,
                "_runs_raw": [],
                "_claims": [],
                "evidence_set_hash": c.get("evidence_set_hash"),
                "affected_assets": list(c.get("affected_assets") or []),
                "_dir_counter": collections.Counter(),
                "_hor_counter": collections.Counter(),
                "_type_counter": collections.Counter(),
                "_rule_counter": collections.Counter(),
                "promoted_count": 0,
            }
            groups[gid] = g
        g["_runs_raw"].append(c.get(run_id_field))
        g["_claims"].append(c)
        g["_dir_counter"][c.get("direction") or "unknown"] += 1
        g["_hor_counter"][c.get("horizon") or "unknown"] += 1
        g["_type_counter"][c.get("claim_type") or "unknown"] += 1
        rule = c.get("promotion_rule")
        g["_rule_counter"][str(rule) if rule else "None"] += 1
        if c.get("promoted"):
            g["promoted_count"] += 1

    # Finalize per-group
    for gid, g in groups.items():
        ordered_runs: list[str] = []
        seen: set[str] = set()
        for run in g["_runs_raw"]:
            if run not in seen:
                seen.add(run)
                ordered_runs.append(run)
        n_claims = len(g["_claims"])
        g["run_count"] = len(ordered_runs)
        g["claim_count"] = n_claims
        g["first_seen_run"] = ordered_runs[0] if ordered_runs else None
        g["last_seen_run"] = ordered_runs[-1] if ordered_runs else None
        g["runs_touched"] = ordered_runs
        g["representative_claim"] = _select_representative_claim(g["_claims"])
        sample: list[str] = []
        seen_texts: set[str] = set()
        for c in g["_claims"]:
            t = c.get("claim_text") or ""
            if t and t not in seen_texts:
                seen_texts.add(t)
                sample.append(t)
            if len(sample) >= SAMPLE_TEXTS_PER_GROUP:
                break
        g["sample_claim_texts"] = sample
        g["direction_distribution"] = dict(g.pop("_dir_counter"))
        g["horizon_distribution"] = dict(g.pop("_hor_counter"))
        g["claim_type_distribution"] = dict(g.pop("_type_counter"))
        g["promotion_rule_distribution"] = dict(g.pop("_rule_counter"))
        g["promoted_rate"] = (
            round(g["promoted_count"] / n_claims, 4) if n_claims else 0.0
        )
        g["has_direction_variance"] = (
            len(g["direction_distribution"]) > 1
        )
        g["has_horizon_variance"] = (
            len(g["horizon_distribution"]) > 1
        )
        g["has_claim_type_variance"] = (
            len(g["claim_type_distribution"]) > 1
        )
        g["member_claim_ids"] = [c.get("claim_id") for c in g["_claims"]]
        g["overmerge_warning"] = (gid in overmerged_group_ids)
        # internal keys 정리
        del g["_runs_raw"]
        del g["_claims"]

    return groups


def _sort_key(g: dict) -> tuple:
    """워크오더 §5 stable candidate sorting key.

    우선순위:
        1. strong_stable_candidate desc
        2. run_count desc
        3. promoted_rate desc
        4. promoted_count desc
        5. affected_assets count desc
        6. canonical_group_id asc
    """
    return (
        0 if g.get("strong_stable_candidate") else 1,   # strong 위로
        -int(g.get("run_count", 0)),
        -float(g.get("promoted_rate", 0.0) or 0.0),
        -int(g.get("promoted_count", 0)),
        -len(g.get("affected_assets", []) or []),
        str(g.get("canonical_group_id") or ""),
    )


def build_claim_group_monitoring_summary(
    claims: Iterable[dict],
    *,
    stable_min_runs: int = DEFAULT_STABLE_MIN_RUNS,
    strong_min_runs: int = DEFAULT_STRONG_MIN_RUNS,
    run_id_field: str = "run_id",
    monitoring_mode: str = DEFAULT_MONITORING_MODE,
) -> dict[str, Any]:
    """R9-A.17 — R9-A.14 G1 canonical_group_id 기반 N-run monitoring summary.

    Parameters
    ----------
    claims : iterable of dict
        각 dict 는 최소 다음 필드 포함:
            - canonical_group_id (str, R9-A.14 G1 정의)
            - {run_id_field} (str)  — 보통 "run_id"
            - claim_id (str)
            - claim_text (str)
            - affected_assets (list[str])
            - evidence_set_hash (str, optional)
            - direction / horizon / claim_type (str, taxonomy enum)
            - promotion_rule (str, optional — "A" / "B" / "C" / None)
            - promoted (bool, optional)
        invariant: claims 는 R9-A.14 (또는 더 최신) 정의로 normalize 된
        상태. outdated stored group_id 의 재계산은 호출측 책임.

    stable_min_runs : int, default 2
        stable candidate 최소 run_count (워크오더 §2).

    strong_min_runs : int, default 3
        strong stable candidate 최소 run_count (워크오더 §2).

    run_id_field : str, default "run_id"
        claim dict 안의 run 식별자 필드명.

    monitoring_mode : str, default "multi_run"
        R9-A.19 mode semantics. "multi_run" (N-run aggregation, stable
        candidate 해석 valid, within_run_dup = overmerge warning) 또는
        "single_batch" (단일 batch, stable_candidate_enabled=False,
        within_run_dup = same-batch diagnostic). 모듈 docstring 참조.
        invalid 값은 ValueError.

    Returns
    -------
    dict — 본 모듈 docstring 의 Output 구조 + 신규 R9-A.19 필드:
        - monitoring_mode (echo)
        - stable_candidate_enabled (bool)
        - within_run_duplicate_semantics (str)
        - run_count_interpretation (str)

    Raises
    ------
    ValueError : monitoring_mode 가 ALLOWED_MONITORING_MODES 외 값일 때.
    """
    if monitoring_mode not in ALLOWED_MONITORING_MODES:
        raise ValueError(
            f"invalid monitoring_mode: {monitoring_mode!r}. "
            f"allowed: {sorted(ALLOWED_MONITORING_MODES)}"
        )
    claim_list = [c for c in claims if isinstance(c, dict)]
    overmerge_warnings = _detect_overmerge_warnings(
        claim_list, run_id_field=run_id_field
    )
    overmerged_gids = {
        w["canonical_group_id"] for w in overmerge_warnings
    }
    groups = _aggregate_groups(
        claim_list,
        run_id_field=run_id_field,
        overmerged_group_ids=overmerged_gids,
    )

    # stable / strong stable flags
    for g in groups.values():
        rc = g["run_count"]
        g["stable_candidate"] = rc >= stable_min_runs
        g["strong_stable_candidate"] = rc >= strong_min_runs

    # Aggregate metrics
    n_groups = len(groups)
    stable_count = sum(1 for g in groups.values() if g["stable_candidate"])
    strong_count = sum(
        1 for g in groups.values() if g["strong_stable_candidate"]
    )
    promoted_groups = sum(
        1 for g in groups.values() if g["promoted_count"] > 0
    )

    runs_ordered: list[str] = []
    seen_runs: set[str] = set()
    for c in claim_list:
        r = c.get(run_id_field)
        if r is not None and r not in seen_runs:
            seen_runs.add(r)
            runs_ordered.append(r)
    n_runs = len(runs_ordered)
    all_run_groups = (
        sum(1 for g in groups.values() if g["run_count"] == n_runs)
        if n_runs > 0 else 0
    )

    # Sorted groups (워크오더 §5)
    sorted_groups = sorted(groups.values(), key=_sort_key)

    # R9-A.19 — Mode-dependent semantics
    stable_enabled = (monitoring_mode == MONITORING_MODE_MULTI_RUN)
    return {
        "total_groups": n_groups,
        "stable_candidates": stable_count,
        "strong_stable_candidates": strong_count,
        "within_run_duplicate_count": len(overmerge_warnings),
        "promoted_groups": promoted_groups,
        "all_run_groups": all_run_groups,
        "total_claims": len(claim_list),
        "total_runs": n_runs,
        "runs": runs_ordered,
        "groups": sorted_groups,
        "overmerge_warnings": overmerge_warnings,
        "stable_min_runs": stable_min_runs,
        "strong_min_runs": strong_min_runs,
        # R9-A.19 — Mode semantics
        "monitoring_mode": monitoring_mode,
        "stable_candidate_enabled": stable_enabled,
        "within_run_duplicate_semantics":
            _WITHIN_DUP_SEMANTICS[monitoring_mode],
        "run_count_interpretation":
            _RUN_COUNT_INTERPRETATION[monitoring_mode],
    }


# ──────────────────────────────────────────────────────────────────
# Reporting helpers (R9-A.18 — daily_update + tools entrypoint 재사용)
# ──────────────────────────────────────────────────────────────────

def render_monitoring_markdown(
    period: str,
    source: str,
    summary: dict[str, Any],
) -> str:
    """summary dict → human-readable Markdown report.

    R9-A.17 의 promotion_monthly_summary entrypoint _render_md 를 module
    public 로 이관. tools/ entrypoint + daily_update Step 2.8 양쪽이 재사용.
    """
    L: list[str] = []
    L.append("# Claim group monitoring summary")
    L.append("")
    L.append(f"- period: {period}")
    L.append(f"- source: `{source}`")
    L.append(f"- total claims: {summary['total_claims']}")
    L.append(f"- total runs: {summary['total_runs']} "
             f"({', '.join(summary['runs'])})")
    L.append("- group_id 정의: R9-A.14 G1 — "
             "`period + evidence_set_hash + sorted_assets`")
    # R9-A.19 — Monitoring mode 명시
    mode = summary.get("monitoring_mode") or DEFAULT_MONITORING_MODE
    stable_enabled = summary.get("stable_candidate_enabled", True)
    within_sem = summary.get(
        "within_run_duplicate_semantics", "overmerge_warning"
    )
    L.append(f"- **monitoring_mode**: `{mode}`")
    L.append(f"- stable_candidate_enabled: {stable_enabled}")
    L.append(f"- within_run_duplicate_semantics: `{within_sem}`")
    if mode == MONITORING_MODE_SINGLE_BATCH:
        L.append("")
        L.append("> ⚠️ **single_batch mode** — 본 summary 는 단일 batch 결과. "
                 "stable_candidate / strong_stable_candidate 는 참고값이며, "
                 "within_run_duplicate 는 overmerge failure 가 아니라 "
                 "same-batch repeated group diagnostic 으로만 해석. "
                 "multi-run aggregation 은 tools/promotion_monthly_summary "
                 "entrypoint (multi_run mode) 사용.")
    L.append("")
    L.append("## Summary")
    L.append("")
    L.append("| metric | value |")
    L.append("|---|---|")
    L.append(f"| total groups | {summary['total_groups']} |")
    L.append(f"| stable (run≥{summary['stable_min_runs']}) | "
             f"**{summary['stable_candidates']}** |")
    L.append(f"| strong stable (run≥{summary['strong_min_runs']}) | "
             f"**{summary['strong_stable_candidates']}** |")
    L.append(f"| all-run groups | {summary['all_run_groups']} |")
    L.append(f"| promoted groups | {summary['promoted_groups']} |")
    L.append(f"| within-run duplicate count | "
             f"{summary['within_run_duplicate_count']} |")

    strong = [g for g in summary["groups"]
              if g.get("strong_stable_candidate")]
    stable_only = [g for g in summary["groups"]
                   if g.get("stable_candidate") and
                   not g.get("strong_stable_candidate")]

    if strong:
        L.append("")
        L.append(f"## Strong stable candidates "
                 f"(run≥{summary['strong_min_runs']}, total {len(strong)})")
        L.append("")
        for i, g in enumerate(strong, 1):
            gid_short = g["canonical_group_id"].split(":")[-1]
            L.append(f"### #{i} `{gid_short}`")
            L.append(f"- run_count: {g['run_count']} / "
                     f"claim_count: {g['claim_count']}")
            L.append(f"- runs_touched: {g['runs_touched']}")
            L.append(f"- evidence_set_hash: `{g['evidence_set_hash']}`")
            L.append(f"- affected_assets: {g['affected_assets']}")
            L.append(f"- promoted: {g['promoted_count']}/{g['claim_count']} "
                     f"(rate {g['promoted_rate']:.2f})")
            L.append(f"- direction: {g['direction_distribution']}")
            L.append(f"- horizon: {g['horizon_distribution']}")
            L.append(f"- claim_type: {g['claim_type_distribution']}")
            L.append(f"- promotion_rule: {g['promotion_rule_distribution']}")
            L.append(f"- representative_claim: {g['representative_claim']}")
            L.append("")

    if stable_only:
        L.append("")
        L.append(f"## Stable candidates "
                 f"(run≥{summary['stable_min_runs']}, "
                 f"non-strong, total {len(stable_only)})")
        L.append("")
        L.append("| group_id (hash) | runs | claims | assets | promoted | "
                 "dir | hor | type | representative |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for g in stable_only:
            gid_short = g["canonical_group_id"].split(":")[-1]
            assets = "+".join(g["affected_assets"])[:40]
            rep = (g["representative_claim"] or "")[:60].replace("|", "\\|")
            dir_d = ",".join(f"{k}={v}" for k, v in
                             g["direction_distribution"].items())
            hor_d = ",".join(f"{k}={v}" for k, v in
                             g["horizon_distribution"].items())
            type_d = ",".join(f"{k}={v}" for k, v in
                              g["claim_type_distribution"].items())
            L.append(
                f"| {gid_short} | {g['run_count']} | {g['claim_count']} | "
                f"{assets} | {g['promoted_count']}/{g['claim_count']} | "
                f"{dir_d} | {hor_d} | {type_d} | {rep} |"
            )

    dir_var = sum(1 for g in summary["groups"]
                  if g.get("has_direction_variance"))
    hor_var = sum(1 for g in summary["groups"]
                  if g.get("has_horizon_variance"))
    type_var = sum(1 for g in summary["groups"]
                   if g.get("has_claim_type_variance"))
    L.append("")
    L.append("## Enum variance diagnostics")
    L.append("")
    L.append(f"- direction variance groups: {dir_var}")
    L.append(f"- horizon variance groups: {hor_var}")
    L.append(f"- claim_type variance groups: {type_var}")

    if summary["overmerge_warnings"]:
        L.append("")
        L.append(f"## ⚠️ Overmerge warnings "
                 f"({len(summary['overmerge_warnings'])})")
        L.append("")
        L.append("| run_id | canonical_group_id | claim_count | claim_ids |")
        L.append("|---|---|---|---|")
        for w in summary["overmerge_warnings"]:
            L.append(
                f"| {w['run_id']} | {w['canonical_group_id']} | "
                f"{w['duplicate_claim_count']} | "
                f"{', '.join(w['claim_ids'][:3])} |"
            )
    else:
        L.append("")
        L.append("## Overmerge guardrail")
        L.append("")
        L.append("✅ overmerge 감지 0건 — within-run duplicate 없음.")

    L.append("")
    return "\n".join(L)


def write_monitoring_artifacts(
    out_dir: str | Path,
    period: str,
    source: str,
    summary: dict[str, Any],
    *,
    ts: str | None = None,
) -> dict[str, Path]:
    """summary 를 JSON + MD 두 파일로 저장.

    Parameters
    ----------
    out_dir : str | Path
        출력 디렉토리. 자동 mkdir.
    period : str
        Period (YYYY-MM) — 파일명에 포함.
    source : str
        원본 raw payload 경로/이름 (MD 리포트 메타에 표시).
    summary : dict
        `build_claim_group_monitoring_summary` 반환 dict.
    ts : str | None
        타임스탬프 (YYYYMMDD_HHMMSS). None 이면 now() 자동 생성.

    Returns
    -------
    dict — {"json": Path, "md": Path}
    """
    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)
    if ts is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir_p / f"claim_group_monitoring_{period}_{ts}.json"
    md_path = out_dir_p / f"claim_group_monitoring_{period}_{ts}.md"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    md_path.write_text(
        render_monitoring_markdown(period, source, summary),
        encoding="utf-8",
    )
    return {"json": json_path, "md": md_path}
