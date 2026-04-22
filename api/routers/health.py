import time
from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()


def _ping_db() -> tuple[str, int]:
    """DB 접속 확인. modules.data_loader.get_connection 재사용.

    Returns:
        (status, latency_ms) — 실패 시 ("fail", -1)
    """
    from modules.data_loader import get_connection

    t0 = time.perf_counter()
    try:
        conn = get_connection("dt")
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        conn.close()
        return "ok", int((time.perf_counter() - t0) * 1000)
    except Exception:
        return "fail", -1


@router.get("/health")
def health() -> dict:
    db_status, latency = _ping_db()
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "time": datetime.now(timezone.utc).isoformat(),
        "version": "0.1.0",
        "db": {"status": db_status, "latency_ms": latency},
    }
