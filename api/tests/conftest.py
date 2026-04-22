import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 프로젝트 루트를 sys.path에 추가 (modules, config import 위해)
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from api.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
