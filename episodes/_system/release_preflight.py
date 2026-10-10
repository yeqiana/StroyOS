#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Story OS V2.0.3.6 release-preflight hard gates.

Adds four P0 controls without adding an episode stage:
1) recent-5 evidence binding
2) optional/required series-lock SHA binding
3) final release semantic review bound to publish assets
4) AI/governance publication compliance evidence

Old episodes remain compatible unless explicitly enabled.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from story_os_contract import story_os_version
import caption_image_audit
import subtitle_layout
import visual_final_freeze
import runtime_router
import runtime_provenance
import product_review_adapter
import text_encoding_health
from fingerprint_semantics import (
    REVIEW_REL as RECENT5_SEMANTIC_REL,
    comparison_index as semantic_comparison_index,
    ensure_review as ensure_semantic_review,
    required as semantic_recent5_required,
    validate_review as validate_semantic_review,
    ProductReviewHostAction,
)
import story_json
import runtime_timeout_policy

from release_preflight_core import *
from release_preflight_recent5 import *
from release_preflight_series import *
from release_preflight_review import *
from release_preflight_verify import *

from release_preflight_review import _finalize_release_review

def cmd_project_verified_recent5(args: argparse.Namespace) -> int:
    """Project a genuinely verified Recent-5 PASS into Story Gate fields.

    This is not a Story Critic PASS. Only novelty review and the mechanism veto
    are projected; plot closure and four-lock differences still require their
    own grounded Story Gate evidence.
    """
    ep = ep_path(args.episode_dir)
    errors = verify_recent5_evidence(ep)
    if errors:
        raise ValueError("RECENT5_EVIDENCE_NOT_VERIFIED: " + "; ".join(errors[:5]))
    review_path = ep / RECENT5_REL
    review = read_json(review_path)
    fingerprint_path = ep / "meta/episode-fingerprint.json"
    fingerprint = read_json(fingerprint_path)
    manifest = read_json(ep / "meta/release-manifest.json")
    manifest_episode = (manifest.get("episode") or {}).get("id")
    if (review.get("decision") != "pass"
            or review.get("mechanism_veto") is not False
            or int(review.get("comparison_count") or 0) < 1
            or review.get("episode_id") != fingerprint.get("episode_id")
            or manifest_episode != fingerprint.get("episode_id")
            or review.get("candidate_fingerprint_sha256") != sha256_file(fingerprint_path)):
        raise ValueError("RECENT5_PASS_SOURCE_BINDING_INVALID")
    path = ep / "meta/story-gates.json"
    gates = read_json(path)
    story = gates.get("story")
    if not isinstance(story, dict):
        raise ValueError("STORY_GATE_STORY_SECTION_MISSING")
    binding = {
        "review_sha256": sha256_file(review_path),
        "fingerprint_sha256": sha256_file(fingerprint_path),
        "registry_sha256": review["registry_sha256"],
        "semantic_review_sha256": review.get("semantic_review_sha256"),
        "comparison_count": review["comparison_count"],
        "decision": "pass",
    }
    bindings = gates.setdefault("release_evidence_bindings", {})
    previous = bindings.get("recent5")
    if story.get("recent5_checked") is True and previous != binding:
        raise ValueError("EXISTING_RECENT5_STORY_GATE_BINDING_DRIFT")
    if previous is not None and previous != binding:
        raise ValueError("EXISTING_RECENT5_AUTHORITY_BINDING_DRIFT")
    story["recent5_checked"] = True
    story["mechanism_skin_swap_veto"] = review["mechanism_veto"]
    bindings["recent5"] = binding
    write_json(path, gates)
    print(json.dumps({"status": "PROJECTED_VERIFIED_RECENT5",
                      "story_review_unchanged": True,
                      "four_locks_unchanged": True,
                      "binding": binding}, ensure_ascii=False))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    ep = ep_path(args.episode_dir)
    release_evidence = verify_release_evidence(ep)
    groups = [
        ("recent5", verify_recent5_evidence(ep)),
        ("series_lock", verify_series_lock(ep)),
        ("visual_final_freeze", visual_final_freeze.verify(ep)),
        ("caption_image_audit", caption_image_audit.verify(ep)),
        *release_evidence.items(),
    ]
    failed = False
    for name, errors in groups:
        if errors:
            failed = True
            for e in errors:
                print(f"FAIL {name}: {e}")
        else:
            print(f"PASS {name}")
    return 2 if failed else 0

def cmd_prepare_auto(args: argparse.Namespace) -> int:
    ep = ep_path(args.episode_dir)
    if not guard_required(ep):
        cmd_enable(argparse.Namespace(episode_dir=str(ep), reason=f"full-auto postflight on V{story_os_version()}"))
    try:
        data = build_recent5(ep, codex=args.codex, timeout=args.timeout)
        write_json(ep / RECENT5_REL, data)
        if data["decision"] != "pass":
            print(f"FAIL recent5: max={data['max_similarity_score']} decision={data['decision']}")
            return 3
    except ProductReviewHostAction as exc:
        print(json.dumps(exc.request, ensure_ascii=False, indent=2))
        return product_review_adapter.HOST_ACTION_REQUIRED_RC
    except Exception as exc:
        print("FAIL recent5:", exc)
        return 3

    if series_lock_required(ep):
        errors = verify_series_lock(ep)
        if errors:
            for e in errors:
                print("FAIL series_lock:", e)
            return 3

    cmd_init_compliance(argparse.Namespace(episode_dir=str(ep), force=False))
    try:
        visual_final_freeze.ensure(ep)
    except Exception as exc:
        print("FAIL visual_final_freeze:", exc)
        return 3
    try:
        caption_ok,_caption_data=caption_image_audit.ensure(ep,codex_raw=args.codex,timeout=min(args.timeout,runtime_timeout_policy.seconds("review_critic")))
        if not caption_ok:
            print("FAIL caption_image_audit: unsupported caption/image pair")
            return 3
    except caption_image_audit.ProductReviewHostAction as exc:
        print(json.dumps(exc.request, ensure_ascii=False, indent=2))
        return product_review_adapter.HOST_ACTION_REQUIRED_RC
    except Exception as exc:
        print("FAIL caption_image_audit:", exc)
        return 3
    if verify_release_semantic(ep):
        rc = cmd_run_release_critic(argparse.Namespace(
            episode_dir=str(ep), codex=args.codex, timeout=args.timeout
        ))
        if rc != 0:
            return rc
    return cmd_verify(argparse.Namespace(episode_dir=str(ep)))

def self_test() -> int:
    import tempfile

    score, veto, _ = similarity(
        {"dimensions": {k: "x" for k in FINGERPRINT_KEYS}},
        {"dimensions": {k: "x" for k in FINGERPRINT_KEYS}},
    )
    assert score == 100 and veto
    assert version_tuple("2.0.3.6") >= MIN_CONTRACT

    # Regression: sibling episode count must never imply shared continuity.
    with tempfile.TemporaryDirectory() as raw:
        parent = Path(raw) / "category"
        ep1 = parent / "01"
        ep2 = parent / "02"
        for ep in (ep1, ep2):
            (ep / "meta").mkdir(parents=True, exist_ok=True)
            write_json(ep / "meta/episode-state.json", {"tool_version": "2.0.3.5.1"})
        assert series_lock_required(ep1) is False
        write_json(parent / "meta/series-continuity.json", {
            "schema_version": 1,
            "enabled": True,
            "series_id": "self-test-series",
        })
        assert series_lock_required(ep1) is True

    print("RELEASE PREFLIGHT SELF-TEST PASS")
    return 0

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("bootstrap-registry")

    p = sub.add_parser("enable")
    p.add_argument("episode_dir")
    p.add_argument("--reason", default="manual enable")

    p = sub.add_parser("project-verified-recent5")
    p.add_argument("episode_dir")

    p = sub.add_parser("build-recent5")
    p.add_argument("episode_dir")
    p.add_argument("--codex")
    p.add_argument("--timeout", type=int, default=None)

    p = sub.add_parser("declare-series")
    p.add_argument("series_dir")
    p.add_argument("--series-id")

    p = sub.add_parser("init-series-lock")
    p.add_argument("series_dir")
    p.add_argument("--source", required=True)

    p = sub.add_parser("bind-series")
    p.add_argument("episode_dir")

    p = sub.add_parser("init-compliance")
    p.add_argument("episode_dir")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("run-release-critic")
    p.add_argument("episode_dir")
    p.add_argument("--codex")
    p.add_argument("--timeout", type=int, default=None)

    p = sub.add_parser("finalize-review")
    p.add_argument("episode_dir")
    p.add_argument("--runtime", choices=["WORK", "WEB"], default="WORK")

    p = sub.add_parser("prepare-auto")
    p.add_argument("episode_dir")
    p.add_argument("--codex")
    p.add_argument("--timeout", type=int, default=None)

    p = sub.add_parser("verify")
    p.add_argument("episode_dir")

    sub.add_parser("self-test")

    args = ap.parse_args()
    args.timeout = runtime_timeout_policy.resolve("release_semantic", getattr(args, "timeout", None))
    if args.cmd == "bootstrap-registry":
        return cmd_bootstrap_registry(args)
    if args.cmd == "enable":
        return cmd_enable(args)
    if args.cmd == "project-verified-recent5":
        try:
            return cmd_project_verified_recent5(args)
        except (OSError, ValueError, KeyError) as exc:
            print("RECENT5 STORY GATE PROJECTION BLOCKED:", exc)
            return 3
    if args.cmd == "build-recent5":
        return cmd_build_recent5(args)
    if args.cmd == "declare-series":
        return cmd_declare_series(args)
    if args.cmd == "init-series-lock":
        return cmd_init_series_lock(args)
    if args.cmd == "bind-series":
        return cmd_bind_series(args)
    if args.cmd == "init-compliance":
        return cmd_init_compliance(args)
    if args.cmd == "run-release-critic":
        return cmd_run_release_critic(args)
    if args.cmd == "finalize-review":
        return finalize_product_release_review(ep_path(args.episode_dir), args.runtime)
    if args.cmd == "prepare-auto":
        return cmd_prepare_auto(args)
    if args.cmd == "verify":
        return cmd_verify(args)
    return self_test()

if __name__ == "__main__":
    raise SystemExit(main())

# STORY_OS_V2_6_0_PERFORMANCE_RUNTIME
