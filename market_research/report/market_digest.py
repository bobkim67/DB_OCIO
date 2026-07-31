# -*- coding: utf-8 -*-
"""TD(QTD/HTD/YTD) 시장 코멘트 병합본 압축 (2026-07-31 사용자 지시).

TD 기간은 시장 debate 를 따로 돌리지 않고 기간 내 월간 승인본을 시간순으로
이어붙여 쓴다(`admin_funds._merge_market_payloads`). 6~12개월이면 본문이
1.3~2.6만자로 커져 펀드 코멘트 프롬프트를 압도하므로, **월별 나열을 기간
전체의 시장 내러티브 하나로 재구성**한다.

요약은 기계적 재서술이라 Sonnet 을 쓴다 (운용보고 본문 생성은 Opus 4.8 유지 —
[[reference_llm_model_config]]). 실패하면 호출부가 원문 병합본을 그대로 쓴다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import anthropic

from market_research.core.constants import ANTHROPIC_API_KEY

DIGEST_MODEL = 'claude-sonnet-4-6'

# 이 길이 이하면 압축하지 않는다. 월간 시장 코멘트 1건 ≈ 2,100자 이므로
# 3개월(QTD ≈ 6.4천자)까지는 원문 그대로, 반기/연초누계부터 압축된다.
DIGEST_THRESHOLD_CHARS = 8000
DIGEST_TARGET_CHARS = 3000
# 한국어는 대략 토큰 1개 ≈ 1자라 목표 3,000자면 cap 을 넉넉히 둬야 한다.
# cap 에 걸려 잘린 요약은 채택하지 않는다([[reference_debate_token_cap]] — cap 잘림 오염).
DIGEST_MAX_TOKENS = 4000

_CACHE_DIR = Path(__file__).resolve().parents[2] / '.cache' / 'market_digest'


def _cache_path(body: str, model: str) -> Path:
    """원문 해시 기반 캐시 경로.

    기간이 아니라 **내용**으로 키를 잡아, 같은 소스를 쓰는 TD 기간끼리
    공유되고 시장 코멘트가 재승인되면 자동 무효화된다.
    """
    h = hashlib.sha256(f'{model}\n{body}'.encode('utf-8')).hexdigest()[:16]
    return _CACHE_DIR / f'{h}.json'


def _build_prompt(body: str, labels: list[str]) -> str:
    span = f'{labels[0]} ~ {labels[-1]}' if labels else '해당 기간'
    return f"""아래는 {span} 각 기간의 시장 코멘트 원문입니다.

{body}

---

위 내용을 **{span} 전체를 관통하는 하나의 시장 내러티브**로 재구성하세요.

지시:
- 월별 나열("1월에는 ~, 2월에는 ~") 금지. 국면 전환과 기간을 지배한 내러티브를
  중심으로 서술하고, 시점은 흐름을 설명하는 데 필요한 만큼만 언급한다.
- 자산군별 방향(국내외 주식·채권, 환율, 대체)과 그 원인을 반드시 보존한다.
- 원문에 없는 수치·사실·전망을 새로 만들지 않는다. 수치는 원문에 있는 것만 인용한다.
- 기간 말 시점의 시장 상태와 그 함의로 마무리한다.
- 한국어 3~4문단, 총 {DIGEST_TARGET_CHARS}자 내외. 머리말·제목·불릿 없이 본문만.
"""


def build_market_digest(body: str, labels: list[str], *,
                        model: str | None = None,
                        threshold: int = DIGEST_THRESHOLD_CHARS) -> dict | None:
    """병합 본문 → 기간 내러티브 1본.

    Parameters
    ----------
    body : 기간 라벨이 붙은 병합 본문 (`[2026-01]\\n...` 형태)
    labels : 소스 기간 라벨 (시간순)

    Returns
    -------
    dict | None
        `{'text', 'model', 'cost', 'source_chars', 'cached'}`.
        임계 미만이거나 압축 실패면 None (호출부는 원문 유지).
    """
    if not body or len(body) <= threshold:
        return None

    model = model or DIGEST_MODEL
    cache = _cache_path(body, model)
    if cache.exists():
        try:
            hit = json.loads(cache.read_text(encoding='utf-8'))
            if hit.get('text'):
                hit['cached'] = True
                return hit
        except Exception:
            pass   # 캐시 손상 → 재생성

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=model,
            max_tokens=DIGEST_MAX_TOKENS,
            messages=[{'role': 'user', 'content': _build_prompt(body, labels)}],
        )
        text = (resp.content[0].text or '').strip()
    except Exception:
        return None
    if not text:
        return None
    if getattr(resp, 'stop_reason', None) == 'max_tokens':
        # 문장 중간에서 끊긴 요약 — 캐시도 채택도 하지 않고 원문 병합본을 쓴다.
        return None

    usage = resp.usage
    out = {
        'text': text,
        'model': model,
        # Sonnet 4.6 = $3/Mtok in, $15/Mtok out
        'cost': usage.input_tokens * 3 / 1_000_000 + usage.output_tokens * 15 / 1_000_000,
        'source_chars': len(body),
        'source_periods': labels,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'cached': False,
    }
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass   # 캐시 실패는 무해 — 결과는 그대로 사용
    return out
