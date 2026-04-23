# DB OCIO Web

React + Vite + TypeScript. FastAPI(`api/`)와 dual-run.

## 실행

```bash
cd web
npm install
npm run dev
```

- 포트: http://127.0.0.1:5173
- `/api` → http://127.0.0.1:8000 (Vite proxy, rewrite 없음)
- FastAPI를 먼저 기동해야 정상 동작.

## Week 1 범위

- Overview 탭 1개만 구현
- auth/login 없음
- 전역상태 라이브러리 없음 (서버 상태는 react-query 전담)
- MUI/AppShell/테마 미도입
- Plotly는 클라이언트 조립 (서버가 Figure JSON 조립하지 않음)

## 타입

FastAPI Pydantic 스키마(`api/schemas/*`)가 `/openapi.json`으로 자동 노출되고,
`openapi-typescript`로 `src/api/generated/openapi.d.ts`를 생성한다.
`src/api/endpoints.ts`는 이 generated 타입을 DTO alias로 재노출하고 fetcher
함수만 유지한다.

### 재생성 방법

FastAPI가 `http://127.0.0.1:8000` 에서 **기동 중일 때만** 실행 가능:

```bash
# 1) 별도 터미널에서 FastAPI 기동
api/.venv/Scripts/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload

# 2) 재생성
cd web && npm run openapi:gen
```

산출물: `src/api/generated/openapi.d.ts` (**수동 수정 금지** — 파일 상단 주석 참고).
백엔드 스키마(`api/schemas/*.py`)를 변경하면 반드시 재생성 후 커밋.
