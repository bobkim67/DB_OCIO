import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import (
    admin,
    admin_funds,
    brinson,
    funds,
    health,
    holdings,
    overview,
    report,
    report_ppt,
    sent_reports,
    transactions,
    warmup,
)
from .settings import get_settings


def _warmup_enabled() -> bool:
    """startup 워밍업 on/off. 기본 ON. pytest/conftest 는 OFF (요구사항 #4)."""
    return os.getenv("OCIO_WARMUP_ON_STARTUP", "true").strip().lower() not in (
        "0", "false", "no", "off", "",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _warmup_enabled():
        # 데몬 스레드를 즉시 반환하며 시작 → startup 비차단.
        # 멱등 가드는 warmup 모듈 내부(_run_lock/_started)에서 보장.
        from .warmup import start_warmup_background

        start_warmup_background()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="DB OCIO API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(funds.router, prefix="/api", tags=["funds"])
    app.include_router(overview.router, prefix="/api", tags=["overview"])
    app.include_router(holdings.router, prefix="/api", tags=["holdings"])
    app.include_router(admin.router, prefix="/api", tags=["admin"])
    app.include_router(admin_funds.router, prefix="/api", tags=["admin-funds"])
    app.include_router(report.router, prefix="/api", tags=["report"])
    app.include_router(report_ppt.router, prefix="/api", tags=["report-ppt"])
    app.include_router(sent_reports.router, prefix="/api", tags=["sent-reports"])
    app.include_router(brinson.router, prefix="/api", tags=["brinson"])
    app.include_router(transactions.router, prefix="/api", tags=["transactions"])
    app.include_router(warmup.router, prefix="/api", tags=["warmup"])

    # ── LAN 배포: 빌드된 React SPA(web/dist) 를 같은 서버/포트에서 서빙 ──
    # web/dist 가 있을 때만(개발 환경엔 없음 → Vite dev server 사용).
    # /api 라우터·/docs·/openapi.json 은 위에서 먼저 등록되어 우선 매칭됨.
    from pathlib import Path
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    _dist = Path(__file__).resolve().parent.parent / "web" / "dist"
    if _dist.is_dir():
        # 빌드 에셋(/assets/*)은 직접 서빙
        app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

        # 그 외 모든 경로는 SPA fallback — 실제 파일(ki-logo.png 등)있으면 그 파일,
        # 없으면 index.html 반환 → '/', '/dashboard' 등 어떤 경로로 들어와도 앱이 뜸.
        # (/api 는 위 라우터가 먼저 매칭. 혹시 안 잡힌 /api 경로는 404 JSON 유지.)
        from fastapi import HTTPException

        @app.get("/{full_path:path}", include_in_schema=False)
        async def _spa(full_path: str):
            if full_path.startswith("api/") or full_path == "api":
                raise HTTPException(status_code=404, detail="Not Found")
            target = _dist / full_path
            if full_path and target.is_file():
                return FileResponse(str(target))
            return FileResponse(str(_dist / "index.html"))
    return app


app = create_app()
