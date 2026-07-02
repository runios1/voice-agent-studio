"""Test bootstrap for Workstream 5.

Adds the repo root to sys.path so `contracts.*` and `backend.security.*` import
without an installed package (Phase-1 scaffold has no top-level packaging yet).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
