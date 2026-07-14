"""Admin — 메모 탭 (자유 노트 여러 개, 서버 JSON 파일 저장, 2026-07-14).

저장소 = data/memos.json (gitignore — 사용자 데이터). LAN 사용자 공유.
인증 없는 내부망 전용 — Admin 탭과 동일하게 프론트 role-gate 만 적용.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_LOCK = threading.Lock()
_STORE = Path(__file__).resolve().parents[2] / 'data' / 'memos.json'


class MemoDTO(BaseModel):
    id: str
    title: str
    content: str
    created_at: str
    updated_at: str


class MemoListDTO(BaseModel):
    memos: list[MemoDTO]


class MemoBodyDTO(BaseModel):
    title: str = ''
    content: str = ''


def _load() -> list[dict]:
    if not _STORE.exists():
        return []
    try:
        return json.loads(_STORE.read_text(encoding='utf-8')).get('memos', [])
    except Exception:                     # noqa: BLE001 — 파손 시 빈 목록 (덮어쓰기 전 백업)
        _STORE.rename(_STORE.with_suffix('.json.corrupt'))
        return []


def _save(memos: list[dict]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps({'memos': memos}, ensure_ascii=False, indent=1),
                   encoding='utf-8')
    os.replace(tmp, _STORE)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


@router.get('/admin/memos', response_model=MemoListDTO)
def list_memos() -> MemoListDTO:
    with _LOCK:
        memos = _load()
    memos.sort(key=lambda m: m.get('updated_at', ''), reverse=True)
    return MemoListDTO(memos=[MemoDTO(**m) for m in memos])


@router.post('/admin/memos', response_model=MemoDTO)
def create_memo(body: MemoBodyDTO) -> MemoDTO:
    memo = {'id': uuid.uuid4().hex[:12], 'title': body.title, 'content': body.content,
            'created_at': _now(), 'updated_at': _now()}
    with _LOCK:
        memos = _load()
        memos.append(memo)
        _save(memos)
    return MemoDTO(**memo)


@router.put('/admin/memos/{memo_id}', response_model=MemoDTO)
def update_memo(memo_id: str, body: MemoBodyDTO) -> MemoDTO:
    with _LOCK:
        memos = _load()
        memo = next((m for m in memos if m['id'] == memo_id), None)
        if memo is None:
            raise HTTPException(404, f'메모 없음: {memo_id}')
        memo['title'] = body.title
        memo['content'] = body.content
        memo['updated_at'] = _now()
        _save(memos)
    return MemoDTO(**memo)


@router.delete('/admin/memos/{memo_id}')
def delete_memo(memo_id: str) -> dict:
    with _LOCK:
        memos = _load()
        rest = [m for m in memos if m['id'] != memo_id]
        if len(rest) == len(memos):
            raise HTTPException(404, f'메모 없음: {memo_id}')
        _save(rest)
    return {'deleted': memo_id}
