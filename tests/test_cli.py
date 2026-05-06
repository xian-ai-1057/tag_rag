"""CLI smoke tests for Phase 7.

Both scripts must exit with code 2 (argparse usage error convention) when
invoked with no arguments.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def test_ingest_no_args_exits_2():
    r = subprocess.run(
        [PYTHON, str(PROJECT_ROOT / "scripts" / "ingest.py")],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert r.returncode == 2


def test_ask_no_args_exits_2():
    r = subprocess.run(
        [PYTHON, str(PROJECT_ROOT / "scripts" / "ask.py")],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert r.returncode == 2
