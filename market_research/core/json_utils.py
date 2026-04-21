# -*- coding: utf-8 -*-
"""
LLM JSON 응답 파싱 유틸리티
============================
Haiku/Sonnet/Opus의 JSON 응답에서 흔히 발생하는 오류를 자동 복구.

실패 패턴:
  - trailing comma: {"a": 1, }
  - missing comma between objects: [{"a":1} {"b":2}]
  - unescaped newlines in string values
  - truncated JSON (토큰 부족으로 잘림)
  - code block wrapper (```json ... ```)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path


def parse_json_response(text: str, expect: str = 'auto'):
    """
    LLM 텍스트 응답에서 JSON 추출 + 파싱.

    Parameters
    ----------
    text : str
        LLM 응답 원문
    expect : str
        'array' → [] 우선, 'object' → {} 우선, 'auto' → 둘 다 시도

    Returns
    -------
    dict | list | None
    """
    if not text or not text.strip():
        return None

    text = _strip_code_block(text)

    # 추출 순서 결정
    if expect == 'array':
        extractors = [_extract_array, _extract_object]
    elif expect == 'object':
        extractors = [_extract_object, _extract_array]
    else:
        # auto: 먼저 나오는 쪽 우선
        arr_pos = text.find('[')
        obj_pos = text.find('{')
        if arr_pos >= 0 and (obj_pos < 0 or arr_pos < obj_pos):
            extractors = [_extract_array, _extract_object]
        else:
            extractors = [_extract_object, _extract_array]

    for extractor in extractors:
        result = extractor(text)
        if result is not None:
            return result

    return None


def _strip_code_block(text: str) -> str:
    """```json ... ``` 코드블록 제거"""
    if '```' not in text:
        return text
    # 정상 코드블록
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # 닫는 ``` 없는 경우 (토큰 부족으로 잘림)
    match = re.search(r'```(?:json)?\s*\n?(.*)', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _extract_array(text: str):
    """[ ... ] 추출 + 복구"""
    start = text.find('[')
    if start < 0:
        return None
    end = text.rfind(']')
    if end <= start:
        # 잘린 배열 → 닫기 시도
        json_str = text[start:] + ']'
    else:
        json_str = text[start:end + 1]
    return _try_parse(json_str)


def _extract_object(text: str):
    """{ ... } 추출 + 복구"""
    start = text.find('{')
    if start < 0:
        return None
    end = text.rfind('}')
    if end <= start:
        # 잘린 객체 → 닫기 시도
        json_str = text[start:] + '}'
    else:
        json_str = text[start:end + 1]
    return _try_parse(json_str)


def _try_parse(json_str: str):
    """단계별 복구 시도"""
    # 1차: 그대로
    result = _safe_loads(json_str)
    if result is not None:
        return result

    # 2차: trailing comma 제거
    fixed = re.sub(r',\s*([}\]])', r'\1', json_str)
    result = _safe_loads(fixed)
    if result is not None:
        return result

    # 3차: 객체 간 쉼표 누락 복구  [{"a":1} {"b":2}] → [{"a":1}, {"b":2}]
    fixed2 = re.sub(r'}\s*{', '}, {', fixed)
    result = _safe_loads(fixed2)
    if result is not None:
        return result

    # 4차: 문자열 내 줄바꿈 이스케이프
    fixed3 = _escape_newlines_in_strings(fixed2)
    result = _safe_loads(fixed3)
    if result is not None:
        return result

    # 5차: 잘린 JSON — 마지막 완전한 객체까지만 파싱
    result = _parse_truncated(fixed2)
    if result is not None:
        return result

    return None


def _safe_loads(s: str):
    """json.loads wrapper — 실패 시 None"""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None


def _escape_newlines_in_strings(text: str) -> str:
    """JSON 문자열 값 내부의 raw 줄바꿈을 \\n으로 치환"""
    # 간단한 상태 머신: 쌍따옴표 안에서만 \n → \\n
    result = []
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            result.append(ch)
            escaped = False
            continue
        if ch == '\\' and in_string:
            result.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ch == '\n':
            result.append('\\n')
            continue
        result.append(ch)
    return ''.join(result)


def _parse_truncated(text: str):
    """
    잘린 배열에서 마지막 완전한 객체까지 파싱.
    예: [{"a":1}, {"b":2}, {"c":3  → [{"a":1}, {"b":2}]
    """
    if not text.startswith('['):
        return None

    # 완전한 {} 블록들을 찾기
    objects = []
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == '{' and depth == 0:
            start = i
            depth = 1
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                obj_str = text[start:i + 1]
                obj = _safe_loads(obj_str)
                if obj is not None:
                    objects.append(obj)
                start = None

    return objects if objects else None


# ═══════════════════════════════════════════════════════
# 월별 뉴스 JSON 안전 읽기/쓰기
# ═══════════════════════════════════════════════════════

def safe_read_news_json(filepath: str | Path) -> list[dict]:
    """
    월별 뉴스 JSON에서 articles 배열을 안전하게 읽기.

    실패 시 .bak에서 복구 시도. 둘 다 실패하면 빈 리스트 + 경고.
    기존 except:pass 패턴을 대체하여 데이터 손실 방지.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return []

    # 1차: 원본 파일 시도
    try:
        data = json.loads(filepath.read_text(encoding='utf-8'))
        articles = data.get('articles', [])
        if isinstance(articles, list):
            return articles
        print(f'  [경고] {filepath.name}: articles가 리스트가 아님 ({type(articles).__name__})')
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError) as e:
        print(f'  [경고] {filepath.name} 파싱 실패: {e}')

    # 2차: .bak 파일에서 복구 시도
    bak = filepath.with_suffix(filepath.suffix + '.bak')
    if bak.exists():
        try:
            data = json.loads(bak.read_text(encoding='utf-8'))
            articles = data.get('articles', [])
            if isinstance(articles, list):
                print(f'  [복구] {bak.name}에서 {len(articles)}건 복구')
                return articles
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError) as e:
            print(f'  [경고] {bak.name}도 파싱 실패: {e}')

    print(f'  [경고] {filepath.name}: 원본+백업 모두 실패 → 빈 리스트 (기존 데이터 보존 위해 쓰기 차단)')
    return []


def safe_write_news_json(filepath: str | Path, data: dict) -> bool:
    """
    월별 뉴스 JSON 안전 쓰기.

    1) 기존 파일을 .bak으로 복사
    2) .tmp 파일에 쓰기
    3) .tmp → 원본으로 rename (atomic on POSIX, near-atomic on Windows)

    Returns: 성공 여부
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # 1) 기존 파일 백업
    if filepath.exists():
        bak = filepath.with_suffix(filepath.suffix + '.bak')
        try:
            shutil.copy2(filepath, bak)
        except OSError as e:
            print(f'  [경고] 백업 실패 ({bak.name}): {e}')

    # 2) 임시 파일에 쓰기
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix='.tmp', prefix=filepath.stem + '_',
        dir=str(filepath.parent))
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 3) 검증: 방금 쓴 파일이 유효한 JSON인지 확인
        with open(tmp_path, 'r', encoding='utf-8') as f:
            json.load(f)

        # 4) rename (Windows: 기존 파일 먼저 삭제 필요)
        if os.name == 'nt' and filepath.exists():
            filepath.unlink()
        os.rename(tmp_path, filepath)
        return True

    except Exception as e:
        print(f'  [오류] {filepath.name} 쓰기 실패: {e}')
        # 임시 파일 정리
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return False


def safe_read_json_list(filepath: str | Path) -> list:
    """
    JSON 배열 파일 안전 읽기 (narrative_candidates.json 등).
    .bak fallback 포함.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return []

    try:
        data = json.loads(filepath.read_text(encoding='utf-8'))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f'  [경고] {filepath.name} 파싱 실패: {e}')

    bak = filepath.with_suffix(filepath.suffix + '.bak')
    if bak.exists():
        try:
            data = json.loads(bak.read_text(encoding='utf-8'))
            if isinstance(data, list):
                print(f'  [복구] {bak.name}에서 {len(data)}건 복구')
                return data
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f'  [경고] {bak.name}도 파싱 실패: {e}')

    return []


def safe_write_json_list(filepath: str | Path, data: list) -> bool:
    """JSON 배열 파일 안전 쓰기 (.bak + .tmp→rename)."""
    filepath = Path(filepath)
    return safe_write_news_json(filepath, data)
