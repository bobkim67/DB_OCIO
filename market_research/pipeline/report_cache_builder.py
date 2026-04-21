# -*- coding: utf-8 -*-
"""Build JSON caches for the Streamlit report tab.

This keeps market_research processing in a batch lane and lets the UI consume
only precomputed JSON outputs.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/
CACHE_DIR = BASE_DIR / "data" / "report_cache"

if sys.stdout and sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from market_research.report.report_service import FUND_CONFIGS, analyze_report_context
except ModuleNotFoundError:
    import importlib.util

    def _load_module(module_name, file_path):
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    _report_service = _load_module(
        "market_research.report_service_cache_runtime",
        BASE_DIR / "report_service.py",
    )
    FUND_CONFIGS = _report_service.FUND_CONFIGS
    analyze_report_context = _report_service.analyze_report_context


def _to_jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def _month_dir(year: int, month: int) -> Path:
    return CACHE_DIR / f"{year}-{month:02d}"


def _build_shared_assets(year: int, month: int, month_dir: Path, force: bool = False):
    """enriched digest + news content pool 배치 생성 (월 1회, 펀드 무관).
    이미 파일이 존재하면 skip (force=True면 재생성)."""
    ed_path = month_dir / "enriched_digest.json"
    if force or not ed_path.exists():
        try:
            from market_research.pipeline.enriched_digest_builder import build_enriched_digest
            print(f"[report_cache] building enriched digest {year}-{month:02d}")
            enriched = build_enriched_digest(year, month)
            if enriched:
                ed_path.write_text(
                    json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[report_cache] enriched digest error: {exc}")
    else:
        print(f"[report_cache] enriched digest exists, skip ({ed_path.name})")

    pool_path = month_dir / "news_content_pool.json"
    if force or not pool_path.exists():
        try:
            from market_research.pipeline.news_content_pool_builder import build_news_content_pool
            print(f"[report_cache] building news content pool {year}-{month:02d}")
            pool = build_news_content_pool(year, month)
            if pool:
                pool_path.write_text(
                    json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[report_cache] news content pool error: {exc}")
    else:
        print(f"[report_cache] news content pool exists, skip ({pool_path.name})")


def build_report_cache(year: int, month: int, fund_codes=None, force_shared: bool = False):
    month_dir = _month_dir(year, month)
    month_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().isoformat(timespec="seconds")

    # 공유 자산 먼저 빌드 (enriched digest + news pool) — 이미 있으면 skip
    _build_shared_assets(year, month, month_dir, force=force_shared)

    codes = list(fund_codes or FUND_CONFIGS.keys())
    built = []

    for fund_code in codes:
        print(f"[report_cache] building {year}-{month:02d} {fund_code}")
        try:
            context = analyze_report_context(fund_code, year, month)
            payload = {
                "version": 2,
                "generated_at": generated_at,
                "fund_code": fund_code,
                "year": year,
                "month": month,
                "fund_config": _to_jsonable(FUND_CONFIGS.get(fund_code, {})),
                "context": _to_jsonable(context),
            }
            out_path = month_dir / f"{fund_code}.json"
            out_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            built.append(fund_code)
        except Exception as exc:
            print(f"[report_cache] skip {fund_code}: {exc}")

    catalog = {
        "version": 2,
        "generated_at": generated_at,
        "funds": {code: _to_jsonable(FUND_CONFIGS.get(code, {})) for code in FUND_CONFIGS},
        "months": sorted(
            [
                folder.name
                for folder in CACHE_DIR.iterdir()
                if folder.is_dir()
            ]
        ),
    }
    (CACHE_DIR / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return built


if __name__ == "__main__":
    now = datetime.now()
    # 사용법: python -m market_research.report_cache_builder [year] [month] [--force] [fund_codes...]
    args = sys.argv[1:]
    force = "--force" in args
    args = [a for a in args if a != "--force"]
    year = int(args[0]) if len(args) > 0 else now.year
    month = int(args[1]) if len(args) > 1 else now.month
    fund_codes = args[2:] if len(args) > 2 else None
    built = build_report_cache(year, month, fund_codes, force_shared=force)
    print(f"[report_cache] done: {len(built)} funds")
