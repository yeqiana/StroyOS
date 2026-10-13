#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fast, no-image M00 contract smoke test. Does not touch Episode/MySQL."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST = ROOT / "episodes" / "_system" / "test_m00_genre_neutral.py"

if __name__ == "__main__":
    cmd = [sys.executable, str(TEST), "-v"]
    print("M00_FAST_TEST (no provider, no image attempts)", flush=True)
    raise SystemExit(subprocess.call(cmd, cwd=ROOT))
