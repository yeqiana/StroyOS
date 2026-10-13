#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fast, no-image M00 contract smoke test. Does not touch Episode/MySQL."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENRE_TEST = ROOT / "episodes" / "_system" / "test_m00_genre_neutral.py"
PIXEL_TEST = ROOT / "tests" / "system" / "test_m00_pixel_audit.py"
REFERENCE_TEST = ROOT / "tests" / "system" / "test_m00_user_reference_staging.py"

if __name__ == "__main__":
    print("M00_FAST_TEST (contracts + actual-pixel safety, no provider, no image attempts)", flush=True)
    commands = (
        [sys.executable, str(GENRE_TEST), "-v"],
        [sys.executable, str(PIXEL_TEST), "-v"],
        [sys.executable, "-m", "pytest", "-q", str(REFERENCE_TEST)],
    )
    for argv in commands:
        rc = subprocess.call(argv, cwd=ROOT)
        if rc != 0:
            raise SystemExit(rc)
    print("M00_FAST_TEST PASS", flush=True)
