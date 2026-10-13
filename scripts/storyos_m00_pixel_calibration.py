#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone read-only CLI for M00 pixel calibration; never invokes provider."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "episodes" / "_system"))
from m00_pixel_audit import main

if __name__ == "__main__":
    raise SystemExit(main())
