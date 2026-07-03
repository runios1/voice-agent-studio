"""Put the repo root on sys.path so `contracts.*` and `backend.*` import as namespace
packages (greenfield scaffold, no packaging config yet) — mirrors voice_runtime."""

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def anyio_backend():
    # Pin @pytest.mark.anyio tests to asyncio (trio isn't installed).
    return "asyncio"
