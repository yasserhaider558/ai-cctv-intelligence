"""Pytest bootstrap.

The application uses flat top-level packages (``config``, ``ui``, ``detection``
...). Running ``pytest`` from the project root already puts this directory on
``sys.path``, but we insert it explicitly so the suite also works when invoked
from another working directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
