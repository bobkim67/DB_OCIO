# DB OCIO API

FastAPI 백엔드 (읽기 API). Streamlit 프로토타입과 병행 운영.

## 전제

- Python 3.14 기준 (프로젝트 공용 venv와 **분리된** api 전용 venv 사용)
- DB 접속정보는 `modules/data_loader.py`의 `DB_CONFIG` + `get_connection()` 재사용
- streamlit 의존 없음 (Day 0 검증 완료, 2026-04-22)

## 전용 venv 생성 및 설치

Windows (git bash):

```bash
cd api
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
cd ..
```

## 실행

프로젝트 루트에서:

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

Week 1은 로컬바인딩(`127.0.0.1`)만 허용. 내부망 노출 금지.

## 엔드포인트 (Week 1)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/health` | 상태 + DB ping (`db.status`, `latency_ms`) |

## 설계 원칙 (docs/refactor_plan_react_fastapi.md 참조)

- 모든 라우터 `def` (sync). `async def` 금지 — pymysql/pandas blocking, FastAPI threadpool이 자동 오프로드.
- `datetime.now(timezone.utc)` 사용. `datetime.utcnow()` 금지.
- CORS: `allow_credentials=False`, origins 명시 리스트, methods GET/POST/OPTIONS.
- DB 접속정보를 `api/settings.py`에 중복 선언하지 않음. `modules.data_loader.get_connection` 재사용.
- `modules/auth.py`는 import 하지 않음 (streamlit 의존).
