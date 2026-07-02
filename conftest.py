"""Repo-root conftest — puts the repository root on sys.path for test runs.

Additive, shared infra: every backend workstream imports the frozen `contracts/`
package and its own `backend/` package. With pytest's default "prepend" import
mode, the directory containing the topmost conftest.py is added to sys.path, so
`import contracts...` and `import backend...` resolve as namespace packages
without any per-stream path hacks. Introduced by WS2; harmless to the others.
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
