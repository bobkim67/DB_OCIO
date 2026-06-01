# -*- coding: utf-8 -*-
"""Balanced selector — 편향 완화 공통 선별 모듈 (shared infra).

문제: 순수 salience top-N 선별이 단발 고-salience 클러스터(예: 지정학·에너지)를
독점 → wiki event / claim / context pack 이 특정 이슈로 도배되고, 시간(주차)·
자산군 커버리지가 무너진다.

해법: 단일 selector 가 아래 4 제약으로 선별한다.
  (1) 주차 quota   — 각 주(week) 최소 ``min_per_week`` 보장
  (2) 자산군 quota — 핵심 자산군 각 최소 ``min_per_asset`` 보장
  (3) topic CAP    — 단일 토픽 상한 ``topic_cap_frac`` (default 25%)
                     + asset CAP ``asset_cap_frac`` (default 28%)
  (4) milestone rescue — record-high/마일스톤 보조 슬롯 ``milestone_slots``
                         (최신 우선 2 + salience 우선 나머지, salience/CAP 무관)
  → 잔여는 salience 로 채움.

item 타입에 비의존적 — 호출측이 key 콜백(salience/topic/asset/week/milestone/id)을
주입한다. 각 gate(이벤트/claim/article)는 자신의 adapter 로 콜백을 구성한다.

LLM 0, IO 0 — 순수 함수. trace(selected_reason)를 함께 반환해 감사 가능.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Hashable, Iterable

# OCIO 운용 보고 표준 7 핵심 자산군 (default). 호출측이 override 가능.
CORE_ASSETS: tuple[str, ...] = (
    "국내주식", "해외주식", "국내채권", "해외채권", "환율", "원자재에너지", "금대체",
)


@dataclass
class SelectionParams:
    """balanced_select 파라미터.

    n               : 최종 선별 개수
    min_per_week    : 주차별 최소 보장 (week_of 가 falsy 면 무시)
    min_per_asset   : 핵심 자산군별 최소 보장
    topic_cap_frac  : 단일 토픽 상한 비율 (ceil(n*frac))
    asset_cap_frac  : 단일 자산군 상한 비율 (fill 단계에만 적용; quota floor 는 예외)
    milestone_slots : 마일스톤 보조 슬롯 (0 이면 비활성)
    weeks           : 주차 quota 대상 week 값들
    """
    n: int
    min_per_week: int = 5
    min_per_asset: int = 4
    topic_cap_frac: float = 0.25
    asset_cap_frac: float = 0.28
    milestone_slots: int = 3
    weeks: tuple[int, ...] = (1, 2, 3, 4, 5)
    core_assets: tuple[str, ...] = CORE_ASSETS


@dataclass
class SelectionResult:
    selected: list[Any]
    reasons: dict[Hashable, str] = field(default_factory=dict)  # id -> selected_reason

    @property
    def selected_ids(self) -> list[Hashable]:
        return list(self.reasons.keys())


def balanced_select(
    items: Iterable[Any],
    params: SelectionParams,
    *,
    salience_of: Callable[[Any], float],
    topic_of: Callable[[Any], str],
    asset_of: Callable[[Any], str | None],
    id_of: Callable[[Any], Hashable],
    week_of: Callable[[Any], int | None] | None = None,
    milestone_of: Callable[[Any], bool] | None = None,
) -> SelectionResult:
    """제약 기반 균형 선별. (selected, reasons) 반환.

    선별 순서: milestone rescue → 주차 quota → 자산군 quota → salience fill.
    각 단계는 topic CAP 을 준수하며, fill 단계는 asset CAP 도 준수한다
    (quota floor 는 자산군 최소 보장이 목적이라 asset CAP 예외).
    """
    items = list(items)
    n = params.n
    if n <= 0 or not items:
        return SelectionResult(selected=[], reasons={})

    tcap = math.ceil(n * params.topic_cap_frac)
    acap = math.ceil(n * params.asset_cap_frac)
    by_sal = sorted(items, key=lambda x: salience_of(x) or 0.0, reverse=True)

    sel: dict[Hashable, Any] = {}
    tcount: Counter = Counter()
    acount: Counter = Counter()
    reasons: dict[Hashable, str] = {}

    def _add(x: Any, why: str) -> bool:
        i = id_of(x)
        if i in sel:
            return False
        sel[i] = x
        tcount[topic_of(x)] += 1
        a = asset_of(x)
        if a:
            acount[a] += 1
        reasons[i] = why
        return True

    def _topic_ok(x: Any) -> bool:
        return tcount[topic_of(x)] < tcap

    def _asset_ok(x: Any) -> bool:
        a = asset_of(x)
        return not (a and acount[a] >= acap)

    # (4) milestone rescue — 최신 우선 2 + salience 우선 나머지 (CAP 무관 보조)
    if milestone_of and params.milestone_slots > 0:
        ms = [x for x in items if milestone_of(x)]
        recent = sorted(ms, key=lambda x: ((week_of(x) if week_of else 0) or 0), reverse=True)
        salient = sorted(ms, key=lambda x: salience_of(x) or 0.0, reverse=True)
        picked, seen = [], set()
        for x in recent[:2] + salient[: max(0, params.milestone_slots - 2)]:
            if id_of(x) not in seen:
                seen.add(id_of(x))
                picked.append(x)
        for x in picked[: params.milestone_slots]:
            if len(sel) < n:
                _add(x, "milestone_rescue")

    # (1) 주차 quota
    if week_of and params.min_per_week > 0:
        byw: dict[int, list[Any]] = defaultdict(list)
        for x in by_sal:
            w = week_of(x)
            if w:
                byw[w].append(x)
        for w in params.weeks:
            have = sum(1 for x in sel.values() if week_of(x) == w)
            for x in byw.get(w, []):
                if have >= params.min_per_week or len(sel) >= n:
                    break
                if id_of(x) in sel:
                    continue
                if _topic_ok(x):
                    if _add(x, f"week_quota_W{w}"):
                        have += 1

    # (2) 자산군 quota (floor) — coverage 보장이 목적이라 topic/asset CAP 모두 예외.
    #     (milestone rescue 와 동일하게 floor 는 CAP 보다 우선. 실데이터에서는
    #      자산군별 대표 기사 토픽이 다양해 CAP 초과가 드묾.)
    if params.min_per_asset > 0:
        for asset in params.core_assets:
            have = acount[asset]
            if have >= params.min_per_asset:
                continue
            for x in by_sal:
                if have >= params.min_per_asset or len(sel) >= n:
                    break
                if id_of(x) in sel:
                    continue
                if asset_of(x) == asset:
                    if _add(x, f"asset_quota_{asset}"):
                        have += 1

    # (3) salience fill (topic + asset CAP 준수)
    for x in by_sal:
        if len(sel) >= n:
            break
        if id_of(x) in sel:
            continue
        if _topic_ok(x) and _asset_ok(x):
            _add(x, "salience_fill")

    # CAP 때문에 n 미달이면 CAP 무시하고 salience 로 마저 채움 (개수 보장)
    if len(sel) < n:
        for x in by_sal:
            if len(sel) >= n:
                break
            if id_of(x) in sel:
                continue
            _add(x, "salience_fill_relaxed")

    return SelectionResult(selected=list(sel.values()), reasons=reasons)
