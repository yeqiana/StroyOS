#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读 Episode 审核效率统计：不新增 Gate，不把 Span 冒充付费模型调用。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import episode_performance as performance
import story_json


def build_report(plan: dict | None, telemetry: dict | None) -> dict:
    plan = plan if isinstance(plan, dict) else {}
    telemetry = telemetry if isinstance(telemetry, dict) else {}
    review = performance._review_summary(telemetry)
    full, patch = review["full"], review["patch"]
    reused, dirty = plan.get("reused_frames"), plan.get("dirty_frames")
    reused_count = len(reused) if isinstance(reused, list) else None
    dirty_count = len(dirty) if isinstance(dirty, list) else None
    count = reused_count + dirty_count if reused_count is not None and dirty_count is not None else None
    ratio = round(reused_count / count, 4) if count else None

    intervals = []
    span_count = 0
    incomplete = False
    for name, bucket in (telemetry.get("named_spans") or {}).items():
        if not str(name).startswith(("REVIEW_FULL_", "REVIEW_PATCH_")) or not isinstance(bucket, dict):
            continue
        for row in bucket.get("runs") or []:
            span_count += 1
            a, b = row.get("started_at"), row.get("ended_at")
            if performance.parse_ts(a) and performance.parse_ts(b) and performance.parse_ts(b) >= performance.parse_ts(a):
                intervals.append((a, b))
            else:
                incomplete = True
    wall = performance._interval_union_seconds(intervals) if span_count and not incomplete else None
    return {
        "schema_version": 1,
        "telemetry_only": True,
        "not_stage_gate": True,
        "review_plan": str(plan.get("action") or "UNKNOWN"),
        "review_scope_reason": plan.get("review_scope_reason"),
        "dirty_frame_count": dirty_count,
        "reused_frame_count": reused_count,
        "reuse_ratio": ratio,
        "full_review_spans": full["attempt_count"],
        "patch_review_spans": patch["attempt_count"],
        "review_span_wall_seconds": wall,
        "actual_model_review_calls": None,
        "actual_model_review_calls_note": "Span 不是经过核实的模型执行回执，不能据此推断模型调用量。",
        "status": "INCOMPLETE" if incomplete else ("OK" if plan and span_count else "UNKNOWN"),
    }


def report_episode(ep: Path) -> dict:
    ep = ep.resolve()
    raw_plan = story_json.read_json(ep / "meta/incremental-frame-review.json", default={})
    plan = raw_plan if isinstance(raw_plan, dict) else {}
    telemetry = performance.load(ep, create=False)
    return {"episode": str(ep), **build_report(plan, telemetry)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode_dir")
    args = parser.parse_args()
    ep = Path(args.episode_dir).resolve()
    if not ep.is_dir():
        parser.error("Episode directory not found")
    print(json.dumps(report_episode(ep), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
