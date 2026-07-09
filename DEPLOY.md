# DB OCIO 대시보드 — 배포 가이드

> 구성: **FastAPI 단일 서버(포트 8020)** 가 React 빌드 정적파일(SPA) + REST API 를 함께 서빙.
> DB 는 사내 MariaDB(192.168.195.55) **조회 전용** 접속.

## 요구사항

| 항목 | 값 |
|---|---|
| Python | 3.12+ (개발환경 3.14) |
| Node.js | 18+ (프론트 빌드 시에만 — 빌드 산출물(web/dist) 동봉 시 불필요) |
| 패키지 | `pip install -r api/requirements.txt` |
| 네트워크 | MariaDB 192.168.195.55:3306 접근 가능한 내부망 |

## 설정 (필수)

1. repo 루트에 `.env` 생성 — `.env.example` 복사 후 값 입력:

```
OCIO_DB_HOST=192.168.195.55
OCIO_DB_USER=solution
OCIO_DB_PASSWORD=<별도 전달>
ECOS_API_KEY=<선택 — 미설정 시 환율은 DB fallback>
```

2. (프론트 재빌드가 필요한 경우만) `cd web && npm install && npm run build` → `web/dist/` 생성.

## 실행

```bash
# 방법 1 — 배치 (Windows, 데일리 업데이트 질문 → 빌드 → 서버 기동)
scripts\launch_dashboard.bat

# 방법 2 — 서버만 직접 기동
python -m uvicorn api.main:app --host 0.0.0.0 --port 8020
```

접속: `http://<서버IP>:8020/`

- 첫 기동 시 백그라운드 워밍업(거래내역/Brinson 선계산)이 돌며, 콜드 상태의 첫 조회는 탭별로 수 초~2분 걸릴 수 있음. 이후 디스크 캐시(`.cache/`)로 빠름.
- `.cache/` 디렉토리는 서버가 자동 생성 (쓰기 권한 필요).

## 디렉토리 구성 (배포 최소셋)

```
api/            FastAPI 라우터·서비스 (+ requirements.txt)
modules/        DB 로딩·계산 레이어 (data_loader 등)
config/         펀드 메타/설정
market_research/  운용보고 조회가 import 하는 리서치 모듈 (데이터 제외)
web/            React 소스 + dist/ (빌드 산출물)
scripts/        기동 배치
docs/dashboard_features.md   탭별 기능 정리
.env.example    환경변수 템플릿
```

배포 불필요 (원본 repo 에만 존재): `General_Backtest/`(R 원본 참조), `MP_monitoring/`(R legacy),
`debug/`, `devlog/`, `market_research/data/`(리서치 산출물), `.cache/`, `node_modules/`.

## 운영 주의

- **인증 없음** — 내부망 전용 전제. 외부/전사 노출 시 리버스 프록시(인증·IP 제한) 뒤에 배치할 것. 특히 `/api/admin/*` (코멘트 생성/승인).
- **서비스화** — 현재 콘솔 세션 의존(.bat). 상시 운영 시 NSSM/작업스케줄러 등록 권장.
- **데이터 갱신** — DB 원장은 익일 새벽 적재. 리서치 배치(`python -m market_research.pipeline.daily_update`)는 운용보고 콘텐츠 생성용으로, 대시보드 서빙과 독립 (LLM API 키 필요).
- SAA/BM 구성 DB(solution.saa_bm_components) 수정 시 `.cache/brinson/` 삭제 + 서버 재시작 필요.
