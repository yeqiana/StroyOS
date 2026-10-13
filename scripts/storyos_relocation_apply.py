#!/usr/bin/env python3
"""Single-shot, no-retry restore of an unchanged reviewed Episode after Git rename.

This module is ONLY called from an explicit acknowledged production command.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import storyos_codex_managed as native


def restore(episode: str, expected: dict, inspector) -> dict:
    base={"status":"REFUSED","model_calls":0,"image_calls":0,
          "mysql_writes_verified":False,"manifest_writes":0}
    ep=native.canonical_episode(episode)
    root=native.ROOT
    if (root/".git").is_file():
        return {**base,"status":"NOT_PRIMARY_CHECKOUT"}
    checkout=subprocess.run(["git","rev-parse","--show-toplevel"],cwd=root,
                            capture_output=True,text=True,timeout=15)
    if checkout.returncode!=0 or Path(checkout.stdout.strip()).resolve()!=root.resolve():
        return {**base,"status":"NOT_PRIMARY_CHECKOUT"}
    try:
        current=inspector(episode)
        fence=("review_sha256","manifest_sha256","review_request_id","source_relocation")
        if not current.get("can_recover_review") or any(current.get(k)!=expected.get(k) for k in fence):
            return {**base,"status":"EVIDENCE_CHANGED_BEFORE_APPLY"}
        # No authorized Driver may be running during a historical metadata repair.
        env=native.native_environment()
        rc,driver=native._probe(env,"episodes/_system/runtime_driver.py",
                                ["status",current["episode"],"--json"])
        if rc!=0 or not isinstance(driver,dict):
            return {**base,"status":"DRIVER_AUTHORITY_UNVERIFIED"}
        if driver.get("driver_state")=="RUNNING" or driver.get("liveness")=="ALIVE":
            return {**base,"status":"LIVE_DRIVER_REFUSE_MUTATION"}
        sys.path.insert(0,str(native.SYSTEM)) if str(native.SYSTEM) not in sys.path else None
        import story_review as review
        import review_record_persistence
        import story_json
        import storage_config
        if storage_config.episode_meta_store_config()["mode"]!="mysql":
            return {**base,"status":"MYSQL_AUTHORITY_REQUIRED"}
        manifest_path=ep/"meta/release-manifest.json"
        original_bytes=manifest_path.read_bytes()
        if hashlib.sha256(original_bytes).hexdigest()!=current["manifest_sha256"]:
            return {**base,"status":"MANIFEST_SHA_CHANGED"}
        payload=story_json.read_json(ep/review.REVIEW_REL)
        if not isinstance(payload,dict) or payload.get("summary",{}).get("passed") is not True:
            return {**base,"status":"ORIGINAL_REVIEW_PAYLOAD_MISSING"}
        # Reuse original review bytes/decision/provenance; never assign a new
        # Reviewer, model policy, Critic PASS, or review attempt.
        amended=story_json.read_json(manifest_path)
        for field,paths in current["source_relocation"].items():
            if amended["artifacts"].get(field)!=paths["old"]:
                return {**base,"status":"MANIFEST_PATH_CHANGED"}
            amended["artifacts"][field]=paths["new"]
        story_json.write_json(manifest_path,amended)
        try:
            saved=review.save_review(
                ep,payload,decision="PASS",
                source_sha256=hashlib.sha256(
                    (payload["story_sha256"]+"|"+payload["storyboard_sha256"]).encode("utf-8")
                ).hexdigest())
        except Exception as exc:
            # Do not roll back a manifest unless safe: a DB write may have
            # succeeded even if a response was lost. Keep both pieces for
            # explicit read-only reconciliation.
            return {**base,"status":"MYSQL_WRITE_OUTCOME_UNCERTAIN",
                    "manifest_writes":1,"failure_kind":type(exc).__name__}
        if saved.get("mysql_written") is not True:
            return {**base,"status":"MYSQL_PERSISTENCE_NOT_CONFIRMED",
                    "manifest_writes":1}
        loaded=review.load_review(ep)
        if not isinstance(loaded,dict) or loaded.get("critic_provenance",{}).get("request_id")!=current["review_request_id"]:
            return {**base,"status":"MYSQL_READBACK_MISMATCH","manifest_writes":1}
        errors=review.verify(ep)
        return {**base,"status":"RESTORED" if not errors else "RESTORED_REQUIRES_ADDITIONAL_GATES",
                "manifest_writes":1,"mysql_writes_verified":True,
                "review_payload_sha256":review.review_authority_sha256(ep),
                "verification_error_count":len(errors)}
    except Exception as exc:
        return {**base,"status":"RECOVERY_FAILED_CLOSED",
                "failure_kind":type(exc).__name__}
