# -*- coding: utf-8 -*-
"""Phase W 게이트 — Taxonomy v2 wiring 의 claim store md5 drift 0 검증.

코드 배선(OPTIONAL 필드 + normalize _remap + validator soft rule)이 기존 운영
claim 을 *실수로* 바꾸지 않음을 운영 데이터로 증명한다. (Phase R flag-ON 재추출은
신규필드를 의도적으로 부착 → 별 단계. 본 스크립트는 "merge 직후 ~ 재실행 전" 불변식.)

본 게이트는 "내 wiring 기여분(remap + OPTIONAL 필드 + soft validator)이 기존
운영 claim 에 inert" 함을 증명한다. 재-normalize 시 발생하는 `canonical_group_id`
null→계산 채움은 **R9-A.8 기존 동작**(claim_extractor.py:428, git HEAD 에서도 동일
재현 — 본 트랙 무관)이므로 허용 diff 로 화이트리스트.

검증 (운영 data/claims/{2026-01..05}.json 의 canonical 파일):
  1. affected_assets serialize 불변 (remap 이 8-class 에 idempotent)
  2. claim_id 불변
  3. 신규 OPTIONAL 키(primary_asset/regions/sectors) 가 기존 claim 에 주입 안 됨
  4. 재-normalize 의 serialize 필드 diff ⊆ {canonical_group_id} (pre-existing only)

비-canonical replay 파일(*.r9a4-*.json)은 제외. LLM 0, write 0 (read-only).

usage:  python -m debug.taxonomy.wiring_md5_check
exit 0 = PASS, 1 = drift 발견.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.analyze.claim_extractor import (  # noqa: E402
    normalize_claim, serialize_claim,
)
from market_research.core.asset_taxonomy import (  # noqa: E402
    article_primary_asset, article_primary_asset_v2, article_primary_asset_auto,
    _region_v2_enabled,
)

CLAIMS_DIR = PROJECT_ROOT / "market_research" / "data" / "claims"
NEWS_DIR = PROJECT_ROOT / "market_research" / "data" / "news"
# canonical 운영 파일만 (2026-MM.json). replay/variant(suffix 포함) 제외.
_CANON_RE = re.compile(r"^\d{4}-\d{2}\.json$")
_NEW_OPTIONAL = ("primary_asset", "regions", "sectors")
# R9-A.8 pre-existing auto-attach (본 트랙 무관) — 허용 diff 화이트리스트.
_ALLOWED_DIFF = {"canonical_group_id"}


def main() -> int:
    files = sorted(p for p in CLAIMS_DIR.glob("*.json") if _CANON_RE.match(p.name))
    if not files:
        print(f"[FAIL] canonical claim 파일 없음: {CLAIMS_DIR}")
        return 1

    total = 0
    aa_changed = 0       # affected_assets 변경 (remap 비-idempotent → FAIL)
    claim_id_changed = 0  # claim_id 변경 (FAIL)
    injected = 0          # 신규 optional 키 주입 (FAIL)
    unexpected = 0        # 화이트리스트 밖 필드 diff (FAIL)
    for fp in files:
        data = json.loads(fp.read_text(encoding="utf-8"))
        claims = data.get("claims") or []
        for c in claims:
            total += 1
            before = serialize_claim(c)
            renorm = normalize_claim(json.loads(json.dumps(c, ensure_ascii=False)))
            after = serialize_claim(renorm)

            # (1) affected_assets remap idempotency
            if before.get("affected_assets") != after.get("affected_assets"):
                aa_changed += 1
                print(f"[AA CHANGED] {fp.name} {c.get('claim_id')}")
                print(f"   before={before.get('affected_assets')}")
                print(f"   after ={after.get('affected_assets')}")
            # (2) claim_id 불변
            if c.get("claim_id") != renorm.get("claim_id"):
                claim_id_changed += 1
                print(f"[CLAIM_ID CHANGED] {fp.name} {c.get('claim_id')} "
                      f"→ {renorm.get('claim_id')}")
            # (3) 신규 optional 키 주입 금지
            for k in _NEW_OPTIONAL:
                if k in after and k not in c:
                    injected += 1
                    print(f"[INJECTED] {fp.name} {c.get('claim_id')} +{k}")
            # (4) 필드 diff ⊆ 화이트리스트
            diff = {k for k in set(before) | set(after)
                    if before.get(k) != after.get(k)}
            extra = diff - _ALLOWED_DIFF
            if extra:
                unexpected += 1
                print(f"[UNEXPECTED DIFF] {fp.name} {c.get('claim_id')} {sorted(extra)}")

    claim_ok = (aa_changed == 0 and claim_id_changed == 0
                and injected == 0 and unexpected == 0)
    print("─" * 60)
    print("[A] claim store md5 drift")
    print(f"files={len(files)}  claims={total}")
    print(f"affected_assets_changed={aa_changed}  claim_id_changed={claim_id_changed}  "
          f"injected_new_keys={injected}  unexpected_field_diff={unexpected}")
    print("(canonical_group_id null→fill 은 R9-A.8 pre-existing — 화이트리스트, 본 트랙 무관)")

    dry_ok = _check_dryrun_equivalence()

    ok = claim_ok and dry_ok
    print("─" * 60)
    print("RESULT:", "PASS — wiring 기여분 inert (claim md5 0 + flag OFF v2==v1)"
          if ok else "FAIL")
    return 0 if ok else 1


def _check_dryrun_equivalence() -> bool:
    """flag-gate 계약 — 운영 뉴스에서 Gate2 디스패처(article_primary_asset_auto)
    가 flag OFF 일 때 v1 과 100% 동일 (route_by_region 미발동). flag ON 일 때의
    v2 divergence(주로 cross-asset sector)는 shadow 로 분포만 보고.
    """
    from collections import Counter
    news_files = sorted(NEWS_DIR.glob("2026-*.json")) if NEWS_DIR.exists() else []
    total = 0
    auto_off_mismatch = 0   # flag OFF 에서 auto != v1 (있으면 계약 위반 → FAIL)
    v2_shadow_mismatch = 0  # v2 != v1 (shadow 분포 — FAIL 아님)
    shadow_pairs: Counter = Counter()
    flag_on = _region_v2_enabled()

    for fp in news_files:
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        arts = d if isinstance(d, list) else (
            d.get("articles") or d.get("news") or [])
        for a in arts:
            if not isinstance(a, dict):
                continue
            total += 1
            v1 = article_primary_asset(a)
            v2 = article_primary_asset_v2(a)
            auto = article_primary_asset_auto(a)
            # flag 가 현재 OFF 면 auto 는 v1 과 같아야 한다 (계약).
            if not flag_on and auto != v1:
                auto_off_mismatch += 1
            if v2 != v1:
                v2_shadow_mismatch += 1
                shadow_pairs[(v1, v2)] += 1

    print("[B] flag-gate 계약 + v2 shadow 분포")
    print(f"news_files={len(news_files)}  articles={total}  flag_on={flag_on}")
    print(f"auto(OFF)!=v1 mismatch={auto_off_mismatch}  (0 = 계약 OK)")
    print(f"v2!=v1 shadow_mismatch={v2_shadow_mismatch} "
          f"({100*v2_shadow_mismatch/max(total,1):.1f}% — flag ON 시 변경 예상분)")
    print("  shadow top (v1→v2):")
    for (a, b), n in shadow_pairs.most_common(6):
        # R-1(§8) 적용 후: 지정학→원자재에너지 고정매핑 제거됨. 남은 원자재에너지
        # mismatch 는 에너지_원자재 sector 직접매핑(정상 cross-asset).
        print(f"    {a} → {b}: {n}")
    # 계약: flag OFF 에서 auto==v1. flag 가 ON 이면 이 게이트는 스킵(정상 divergence).
    return (flag_on or auto_off_mismatch == 0)


if __name__ == "__main__":
    raise SystemExit(main())
