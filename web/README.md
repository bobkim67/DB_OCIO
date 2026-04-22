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

`src/api/endpoints.ts`에 수동 정의. FastAPI `api/schemas/*` 와 1:1 매칭.
openapi-typescript 전환은 Week 2+.
