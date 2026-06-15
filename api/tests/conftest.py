import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# startup 워밍업이 테스트에서 절대 DB를 때리지 않도록 OFF (요구사항 #4).
# app import / lifespan 실행 전에 설정해야 한다.
os.environ["OCIO_WARMUP_ON_STARTUP"] = "false"

# 프로젝트 루트를 sys.path에 추가 (modules, config import 위해)
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from api.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
