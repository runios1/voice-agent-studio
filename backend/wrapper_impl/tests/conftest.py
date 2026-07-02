"""Put the repo root on sys.path so `contracts.*` and `backend.*` import as
namespace packages (the repo has no packaging config yet — greenfield scaffold).

Mirrors the convention used by the other backend workstreams; a repo-root
conftest introduced during integration supersedes this harmlessly.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
