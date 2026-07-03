"""Put the repo root on sys.path so `contracts.*` and `backend.*` import as
namespace packages when this stream is run in isolation (matches the other
workstreams' conftests; the repo-root conftest does the same at integration)."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
