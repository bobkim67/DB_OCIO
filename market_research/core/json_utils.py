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
import re


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
