#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Story OS timeout policy single source.

Every runtime role that needs a timeout default reads it here, and the YAML
section config/storyos.yaml:timeout_policy is the human-editable authority.
Values equal the historical defaults so behavior does not change until a
deliberate tuning decision is made. Clamp bounds reproduce the two existing
full-range cap semantics (fast frame scout 60..240, speculative image lane
60..600); VALID_RANGE additionally carries the provider channel bound of
image_worker_request (60..1200) used for config validation only.

- ``resolve(role, None)``: configured/CLI default path.
- ``resolve(role, explicit)``: an explicit CLI/library override wins as-is.
- ``clamp(role, value)``: reproduce the historical full-range clamps.
- ``cap(role, value)``: reproduce the historical upper-only forwarding caps.
"""
from __future__ import annotations

from typing import Any

import storyos_config

# role -> historical default seconds (behavior-preserving baseline).
DEFAULT_SECONDS: dict[str, int] = {
    "codex_supervisor_run": 7200,   # full-chain codex supervisor / DAG run
    "codex_scoped_step": 3600,      # single scoped codex step worker
    "image_worker_request": 600,    # one image backend request
    "image_lane_run": 600,          # scheduler/speculative image lane
    "visual_baseline_critic": 300,  # visual lock baseline critic
    "fast_scout": 240,              # fast frame scout
    "review_critic": 900,           # story/visual/caption review critics
    "serial_episode_review": 1500,  # one-shot episode recheck, historical budget
    "serial_source_revision_review": 1200,  # A13/A14/A15 source review, historical budget
    "codex_auth_probe": 30,         # read-only `codex login status` through the user bridge
    "image_tool_visibility_probe": 120,  # bounded native tool visibility text-only probe
    "driver_carrier_control": 60,   # register/query the Windows Driver carrier task
    "image_probe": 900,             # image provider capability probe
    "deep_semantic_review": 1800,   # frame semantic / incremental review
    "release_semantic": 1800,       # recent5 / release critic semantic build
    "isolated_ml_probe": 30,        # sidecar interpreter/dependency resolution
    "isolated_ml_worker": 180,      # isolated local ML request response budget
    "authority_lock": 30,            # short cross-process Authority/Queue file lock
    "phase5a_canary_run": 900,       # one prepared Phase5A production-subpath run
}
REQUIRED_ROLES: tuple[str, ...] = tuple(DEFAULT_SECONDS)

# role -> (min_seconds, max_seconds); absent role means no clamp.
CLAMP_BOUNDS: dict[str, tuple[int, int]] = {
    "fast_scout": (60, 240),
    "image_lane_run": (60, 600),
}

# role -> allowed default range when the YAML policy is validated; absent
# role means the default is unbounded. image_worker_request is validated by
# the provider channel bound (60..1200) that used to live only in the CLI.
VALID_RANGE: dict[str, tuple[int, int]] = {
    **CLAMP_BOUNDS,
    "image_worker_request": (60, 1200),
}


def _policy() -> dict[str, Any]:
    cfg = storyos_config.load_config()
    value = storyos_config.get_path(cfg, "timeout_policy")
    return value if isinstance(value, dict) else {}


def default_seconds(role: str) -> int:
    if role not in DEFAULT_SECONDS:
        raise ValueError(f"unknown timeout role: {role}")
    return DEFAULT_SECONDS[role]


def configured_seconds(role: str) -> int:
    """Resolve role timeout from YAML, falling back to the historical default."""
    if role not in DEFAULT_SECONDS:
        raise ValueError(f"unknown timeout role: {role}")
    value = _policy().get(role, DEFAULT_SECONDS[role])
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"timeout_policy.{role} must be a positive int")
    return value


def seconds(role: str) -> int:
    return configured_seconds(role)


def resolve(role: str, timeout: object = None) -> int:
    """Return an explicit API/CLI timeout, or the configured role default.

    CLI overrides keep priority: parser defaults are None and pass through
    here, so the YAML timeout_policy section is the only default authority
    (values preserve the historical defaults).
    """
    if timeout is None:
        return configured_seconds(role)
    value = int(timeout)
    if value <= 0:
        raise ValueError(f"timeout for role {role!r} must be a positive int")
    return value


def clamp(role: str, value: int) -> int:
    """Clamp value to the role bounds (identity when role is unbound)."""
    bounds = CLAMP_BOUNDS.get(role)
    if bounds is None:
        return int(value)
    low, high = bounds
    return max(low, min(high, int(value)))


def cap(role: str, value: int) -> int:
    """Upper-only forwarding cap (min(value, role high bound))."""
    bounds = CLAMP_BOUNDS.get(role)
    if bounds is None:
        raise ValueError(f"no upper bound for role: {role}")
    return min(bounds[1], int(value))


def self_test() -> None:
    cfg = storyos_config.load_config()
    policy = storyos_config.get_path(cfg, "timeout_policy") or {}
    for role in REQUIRED_ROLES:
        assert policy.get(role) == DEFAULT_SECONDS[role], role
        rng = VALID_RANGE.get(role)
        if rng is not None:
            assert rng[0] <= policy[role] <= rng[1], role
    assert clamp("fast_scout", 10_000) == 240
    assert clamp("fast_scout", 10) == 60
    assert clamp("image_lane_run", 10) == 60
    assert clamp("image_lane_run", 10_000) == 600
    assert clamp("review_critic", 123) == 123
    assert cap("fast_scout", 10) == 10
    assert cap("fast_scout", 300) == 240
    try:
        cap("review_critic", 1)
        raise AssertionError("cap of unbound role must raise")
    except ValueError:
        pass
    assert resolve("review_critic", None) == DEFAULT_SECONDS["review_critic"]
    assert resolve("review_critic", 42) == 42
    print("RUNTIME TIMEOUT POLICY SELF-TEST PASS")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("self-test")
    args = ap.parse_args()
    if args.cmd == "self-test":
        self_test()
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
