#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""StoryOS 审核效率专项极速验收，离线运行，无付费模型调用。"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "tests/system/test_incremental_frame_reuse_phase4.py",
    "tests/system/test_review_efficiency_shadow_defaults.py",
    "tests/system/test_review_efficiency_report.py",
    "tests/system/test_episode_performance_review_metrics.py",
)

def main() -> int:
    return subprocess.call([sys.executable, "-m", "pytest", "-q", *TESTS], cwd=ROOT)

if __name__ == "__main__":
    raise SystemExit(main())
