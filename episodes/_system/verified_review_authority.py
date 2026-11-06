"""Fail-closed gate for consuming generated Review projections.

This module does not grant Review authority. It only confirms that the existing
Final Semantic evidence and queue terminal record agree with the current
accepted ledger projection before downstream consumers reuse it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import frame_review_persistence
import frame_semantic_review
import production_ledger
import review_queue
import scheduler_core


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _queue_review_for_frame(queue: dict, *, logical_asset_key: str,
                            generation_key: str, candidate_sha256: str) -> list[dict]:
    return [row for row in (queue.get(review_queue.QUEUE_KEY) or [])
            if isinstance(row, dict)
            and row.get("review_kind") == review_queue.FINAL_SEMANTIC
            and str(row.get("logical_asset_key") or "") == logical_asset_key
            and str(row.get("generation_key") or "") == generation_key
            and str(row.get("artifact_sha256") or "").lower() == candidate_sha256.lower()]


def _phase5a_manifest_errors(
    ep: Path, *, review_key: str, generation_key: str, attempt_index: int,
    evidence_fingerprint: str, receipt: dict,
) -> list[str]:
    marker = ep / "meta" / "phase5a-canary.json"
    if not marker.is_file():
        return []
    # The review committer owns this manifest API. Until it is present, or while
    # a commit is only decided but its projections are incomplete, fail closed.
    try:
        import frame_semantic_review as semantic
        loader = getattr(semantic, "load_review_commit", None)
        path_builder = getattr(semantic, "review_commit_manifest_path", None)
        if not callable(loader) or not callable(path_builder):
            return ["Phase5A Review commit manifest API unavailable"]
        commit_id_builder = getattr(semantic, "review_commit_id", None)
        if not callable(commit_id_builder):
            return ["Phase5A Review commit identity API unavailable"]
        commit_id = commit_id_builder(
            review_key, generation_key, int(attempt_index), evidence_fingerprint)
        path = path_builder(ep, commit_id)
        if not Path(path).is_file():
            return ["Phase5A Review commit manifest missing"]
        manifest = loader(ep, commit_id)
    except Exception as exc:
        return [f"Phase5A Review commit manifest unreadable: {type(exc).__name__}"]
    if not isinstance(manifest, dict):
        return ["Phase5A Review commit manifest invalid"]
    if manifest.get("schema") != "phase5a-final-semantic-review-commit/v1":
        return ["Phase5A Review commit manifest schema mismatch"]
    receipt_raw = _canonical(receipt).encode("utf-8")
    if (str(manifest.get("review_commit_id") or "") != commit_id
            or str(manifest.get("review_item_id") or "") != review_key
            or str(manifest.get("generation_key") or "") != generation_key
            or int(manifest.get("attempt_index") or 0) != int(attempt_index)
            or str(manifest.get("evidence_fingerprint") or "") != evidence_fingerprint
            or hashlib.sha256(receipt_raw).hexdigest() != str(manifest.get("receipt_sha256") or "")):
        return ["Phase5A Review commit manifest identity or receipt mismatch"]
    if manifest.get("status") != "PROJECTIONS_APPLIED":
        return ["Phase5A Review commit projections incomplete"]
    return []


def _is_phase5a_test_only(ep: Path) -> bool:
    marker = Path(ep) / "meta" / "phase5a-canary.json"
    if not marker.is_file():
        return False
    try:
        value = json.loads(marker.read_text(encoding="utf-8-sig"))
    except Exception:
        return False
    return (
        isinstance(value, dict)
        and value.get("workspace_class") == "TEST_ONLY"
        and value.get("promotion_class") == "NON_PROMOTABLE"
        and value.get("canary_type") == "PHASE5A_COLLABORATIVE_REGRESSION"
    )


def _sha_bound_direct_user_authority(episode: Path, frames: dict) -> dict | None:
    """Separate final-pixel user authority, never a fabricated model Review PASS.

    The ordinary model review path remains mandatory without an *explicit*
    final-acceptance record covering every current image and all NEEDS_USER
    defects. In particular, an older acceptance for two frames cannot silently
    downgrade new defects elsewhere in the episode.
    """
    import final_acceptance

    acceptance = final_acceptance.valid(episode)
    if not acceptance or not acceptance.get("accepted_visual_assets"):
        return None
    if not (final_acceptance.allows(episode, "frame_semantic")
            and final_acceptance.allows(episode, "production_gate")):
        return None

    rows = {str(key).zfill(2): row for key, row in frames.items()}
    defects = {f"{int(item):02d}" for item in acceptance["known_defect_frames"]}
    assets = acceptance["accepted_visual_assets"]
    errors: list[str] = []
    if set(assets) != set(rows):
        errors.append("direct-user accepted asset set must equal the current full frame set")
    if not defects <= set(rows):
        errors.append("direct-user defect acceptance names unknown frames")
    for key, frame in sorted(rows.items()):
        if not isinstance(frame, dict):
            errors.append(f"frame {key}: ledger row missing")
            continue
        status = str(frame.get("status") or "").upper()
        if status not in production_ledger.ACCEPTED_LEDGER_STATES | {"NEEDS_USER"}:
            errors.append(f"frame {key}: unresolved generation state {status}")
            continue
        if status == "NEEDS_USER" and key not in defects:
            errors.append(f"frame {key}: existing semantic defect is not directly accepted")
            continue
        try:
            asset = final_acceptance.visual_asset_for_frame(episode, key)
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append(f"frame {key}: direct-user visual asset invalid: {exc}")
            continue
        approved = frame.get("approved_asset")
        source = (approved if status in production_ledger.ACCEPTED_LEDGER_STATES
                  and isinstance(approved, dict) and approved.get("path")
                  else frame.get("current_candidate"))
        expected = str((source or {}).get("sha256") or "").lower()
        if not expected or expected != str(asset.get("sha256") or "").lower():
            errors.append(f"frame {key}: user-accepted pixels differ from current ledger asset")
            continue
        if not any(
            attempt.get("result") == "success"
            and str((attempt.get("candidate") or {}).get("sha256") or "").lower() == expected
            for attempt in frame.get("attempts") or [] if isinstance(attempt, dict)
        ):
            errors.append(f"frame {key}: no successful generation attempt for accepted pixels")
    return {
        "status": "BLOCKED" if errors else "USER_ACCEPTED",
        "errors": errors,
        "frames": [] if errors else sorted(rows),
        "authority": "SHA_BOUND_DIRECT_USER_FINAL_ASSETS",
        "machine_review_pass": False,
        "known_defect_frames": sorted(defects),
    }


def verify_episode_review_authority(
    ep: Path, *, metadata_only: bool = False,
) -> dict:
    """Verify all accepted generated frames have matching Review PASS authority.

    Legacy episodes that predate the bound Review/Generation contract remain
    outside this gate. Direct-user acceptance continues through its own explicit
    acceptance authority; generated approved/LOCKED projections require a valid
    Final Semantic receipt and a terminal successful queue record.
    """
    episode = Path(ep).resolve()
    if not frame_semantic_review.phase4_contract.required(episode):
        return {"status": "NOT_REQUIRED", "errors": [], "frames": []}

    errors: list[str] = []
    verified_frames: list[str] = []
    ledger = production_ledger.load_authority(episode, default={}) or {}
    frames = ledger.get("frames") if isinstance(ledger, dict) else None
    if not isinstance(frames, dict):
        return {"status": "BLOCKED", "errors": ["production ledger frames missing"], "frames": []}

    # A fully SHA-bound direct-user final decision is its own release authority.
    # It does not convert missing/failed Model Review receipts to model PASS.
    # Phase5A TEST_ONLY still requires its exact test Review receipt.
    if not _is_phase5a_test_only(episode):
        direct_user = _sha_bound_direct_user_authority(episode, frames)
        if direct_user is not None:
            return direct_user

    # Reuse the canonical verifier for policy, frame/candidate identity, receipt,
    # and evidence-fingerprint validation. Production episodes require the normal
    # full review authority. The isolated Phase5A canary is intentionally one
    # TEST_ONLY / NON_PROMOTABLE frame and must be verified with its scoped
    # contract rather than being forced through FULL_FRAME_SET semantics.
    if _is_phase5a_test_only(episode):
        accepted_keys = [
            str(key).zfill(2) for key, row in frames.items()
            if isinstance(row, dict)
            and str(row.get("status") or "").upper() in production_ledger.ACCEPTED_LEDGER_STATES
        ]
        if len(accepted_keys) != 1:
            semantic_errors = ["Phase5A TEST_ONLY authority requires exactly one accepted frame"]
        else:
            scoped_frames = frame_semantic_review.frame_records(
                episode, require_files=not metadata_only, only_frames=accepted_keys)
            semantic_errors = frame_semantic_review.verify_scoped_review(
                episode, scoped_frames,
                review_scope=frame_semantic_review.PHASE5A_SINGLE_FRAME_SCOPE,
                metadata_only=metadata_only,
            )
    else:
        semantic_errors = frame_semantic_review.verify_episode(
            episode, metadata_only=metadata_only, write_audit=False)
    if semantic_errors:
        errors.extend("final semantic evidence invalid: " + str(error)
                      for error in semantic_errors)

    queue = scheduler_core.load_queue(episode)
    for raw_key, ledger_frame in sorted(frames.items(), key=lambda pair: str(pair[0])):
        if not isinstance(ledger_frame, dict):
            continue
        status = str(ledger_frame.get("status") or "").upper()
        if status not in production_ledger.ACCEPTED_LEDGER_STATES:
            continue
        key = str(raw_key).zfill(2)
        accepted = ledger_frame.get("approved_asset")
        if not isinstance(accepted, dict):
            errors.append(f"frame {key}: accepted ledger status has no approved asset")
            continue
        sha = str(accepted.get("sha256") or "").lower()
        binding = frame_semantic_review.current_generation_binding(
            episode, raw_key, accepted, ledger)
        logical_key = str(binding.get("logical_asset_key") or "")
        generation_key = str(binding.get("generation_key") or "")

        # A direct user's explicit final acceptance is a separate authority and
        # must bind the same pixels. It is not misrepresented as model Review.
        try:
            import final_acceptance
            user_acceptance = final_acceptance.visual_asset_for_frame(episode, raw_key)
        except Exception:
            user_acceptance = None
        if isinstance(user_acceptance, dict) and str(user_acceptance.get("sha256") or "").lower() == sha:
            verified_frames.append(key)
            continue

        if not logical_key or not generation_key or len(sha) != 64:
            errors.append(f"frame {key}: accepted projection lacks generation identity")
            continue
        review_data = frame_review_persistence.load(episode, int(raw_key))
        if not isinstance(review_data, dict):
            errors.append(f"frame {key}: Final Semantic review evidence missing")
            continue
        provenance = review_data.get("critic_provenance")
        receipt = provenance.get("model_execution_receipt") if isinstance(provenance, dict) else None
        if not isinstance(receipt, dict):
            errors.append(f"frame {key}: Model Execution Receipt missing")
            continue

        matches = _queue_review_for_frame(
            queue, logical_asset_key=logical_key, generation_key=generation_key,
            candidate_sha256=sha)
        phase3 = frame_semantic_review.phase3_context_hashes(episode, key)
        expected_queue_rows = [row for row in matches
                               if row.get("review_key") == review_data.get("review_item_id")]
        if len(expected_queue_rows) != 1:
            errors.append(f"frame {key}: matching Final Semantic queue item missing or ambiguous")
            continue
        queue_item = expected_queue_rows[0]
        expected_fingerprint = frame_semantic_review.review_evidence_fingerprint(
            {
                "logical_asset_key": logical_key,
                "generation_key": generation_key,
                "sha256": sha,
                "source_binding": frame_semantic_review.source_binding(episode, key),
            },
            contexts=frame_semantic_review.context_hashes(episode),
            phase3_contexts=phase3,
            policy_sha256=frame_semantic_review.bound_review_policy_sha256(episode),
            review_item_id=str(queue_item.get("review_key") or ""),
            attempt_index=int(queue_item.get("attempt_index") or 0),
            # The verified Phase3 contract is canonical. Older Review Queue rows
            # may carry an empty copied frame_contract_sha256.
            frame_contract_sha256=str(phase3.get("frame_contract_sha256") or ""),
            prompt_package_sha256=str(queue_item.get("prompt_package_sha256") or ""),
        )
        if not expected_fingerprint:
            errors.append(f"frame {key}: canonical review evidence fingerprint unavailable")
            continue
        receipt_errors = frame_semantic_review.validate_final_semantic_execution_receipt(
            receipt,
            {
                "review_item_id": queue_item.get("review_key"),
                "logical_asset_key": logical_key,
                "generation_key": generation_key,
                "attempt_index": queue_item.get("attempt_index"),
                "candidate_sha256": sha,
                "frame_contract_sha256": phase3.get("frame_contract_sha256"),
                "prompt_package_sha256": queue_item.get("prompt_package_sha256"),
                "model_policy_sha256": frame_semantic_review.bound_review_policy_sha256(episode),
                "evidence_fingerprint": expected_fingerprint,
            },
        )
        if receipt_errors:
            errors.extend(f"frame {key}: invalid Model Execution Receipt: {item}"
                          for item in receipt_errors)
            continue
        valid_queue = [row for row in matches
                       if row.get("status") == "finalized"
                       and isinstance(row.get("receipt"), dict)
                       and row["receipt"].get("status") == "SUCCESS"
                       and row["receipt"].get("review_outcome") == "PASS"
                       and str(review_data.get("review_item_id") or "") == str(row.get("review_key") or "")
                       and isinstance(row["receipt"].get("critic_receipt"), dict)
                       and _canonical(row["receipt"]["critic_receipt"]) == _canonical(receipt)]
        if len(valid_queue) != 1:
            errors.append(f"frame {key}: matching terminal successful Final Semantic queue record missing or ambiguous")
            continue
        manifest_errors = _phase5a_manifest_errors(
            episode,
            review_key=str(queue_item.get("review_key") or ""),
            generation_key=generation_key,
            attempt_index=int(queue_item.get("attempt_index") or 0),
            evidence_fingerprint=expected_fingerprint,
            receipt=receipt,
        )
        if manifest_errors:
            errors.extend(f"frame {key}: {error}" for error in manifest_errors)
            continue
        verified_frames.append(key)

    return {
        "status": "VERIFIED" if not errors else "BLOCKED",
        "errors": errors,
        "frames": verified_frames,
    }


def require_verified_episode_review_authority(ep: Path, *, metadata_only: bool = False) -> None:
    result = verify_episode_review_authority(ep, metadata_only=metadata_only)
    if result["status"] == "BLOCKED":
        raise ValueError("unverified Review projection: " + "; ".join(result["errors"][:8]))
