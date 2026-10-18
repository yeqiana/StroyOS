"""Production ledger management commands (Story OS B4 split).

Management lane: init / authorize-* / accept-user-exception-candidate /
promote / lock / batch-begin / batch-end / audit / show. Shared library globals
are imported from production_ledger_core; the CLI facade re-exports these.
"""
from __future__ import annotations

from production_ledger_core import *  # noqa: F401,F403  (shared ledger globals)
import sys


def episode_dir(raw: str) -> Path:
    """Resolve an episode lazily during the ledger facade import cycle."""
    from production_ledger_core import episode_dir as resolve_episode_dir
    return resolve_episode_dir(raw)


def _freeze_visual_profile_after_promote(ep: Path, key: str) -> None:
    """Phase 4.6-B: the first formal production asset freezes the Visual Profile.

    Promotion is the one place where a reviewed frame candidate becomes the Episode
    approved asset, so it is the only honest moment to ask the canonical lifecycle
    for LOCKED -> FROZEN. The closure is advisory: any failure is reported and never
    aborts the promotion.
    """
    try:
        import visual_profile_closure as closure
        report = closure.freeze_on_first_asset_commit(ep, frame=key)
    except Exception as exc:  # a closure failure is never a production failure
        print(f"WARN: visual profile freeze hook failed for {key}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return
    status = report.get("status")
    if status == closure.RESULT_FROZEN:
        print(f"visual-profile: FROZEN by frame {key} ({closure.FREEZE_TRIGGER})")
    elif status == closure.RESULT_FAIL:
        print(f"WARN: visual profile freeze not applied for {key}: {report.get('code')} "
              f"{report.get('detail')}", file=sys.stderr)


def cmd_init(args: argparse.Namespace) -> None:
    ep = episode_dir(args.episode_dir)
    path = ep / LEDGER_FILE
    if path.exists() and not args.force:
        raise SystemExit(f"ledger already exists: {path}")
    data = init_ledger(ep, count=args.frame_count, ratio=args.aspect_ratio, overwrite=args.force)
    c = data["canvas"]
    print(f"initialized {path}")
    print(f"canvas: {c['aspect_ratio']} / {c['width']}脳{c['height']} ({c['source']})")


def cmd_authorize_user_locked_repair(args: argparse.Namespace) -> None:
    """Reopen a locked frame for its first ordinary repair after direct user scope approval."""
    ep = episode_dir(args.episode_dir)
    path, data = get_ledger(ep)
    key, frame = frame_obj(data, args.frame)
    if frame["status"] != "LOCKED":
        raise SystemExit(f"locked repair requires LOCKED, got {frame['status']}")
    if frame.get("content_repairs_used", 0) != 0:
        raise SystemExit("locked repair is only for a frame with no ordinary content repair")
    approval = args.approval_text.strip()
    if not approval:
        raise SystemExit("direct user approval text is required")
    frame.setdefault("superseded_locks", []).append({"at": now_iso(), "lock": frame.get("lock"), "approved_asset": frame.get("approved_asset")})
    frame["status"] = "REPAIR_AUTHORIZED"
    frame["repair_authorization"] = {"at": now_iso(), "note": args.reason, "user_approved": True, "delegated_auto_review": False, "approval_basis": "direct_user_review_locked_repair", "approval_text": approval}
    data["updated_at"] = now_iso()
    save_json(path, data)
    print(f"{key}: REPAIR_AUTHORIZED (direct-user locked-frame scope recorded)")


def cmd_authorize_user_passed_repair(args: argparse.Namespace) -> None:
    """Reopen a pre-lock PASSED frame when a later user-approved authority change invalidates it."""
    ep = episode_dir(args.episode_dir)
    path, data = get_ledger(ep)
    key, frame = frame_obj(data, args.frame)
    if frame["status"] != "PASSED":
        raise SystemExit(f"passed repair requires PASSED, got {frame['status']}")
    if frame.get("content_repairs_used", 0) != 0:
        raise SystemExit("passed repair is only for a frame with no ordinary content repair")
    approval = args.approval_text.strip()
    if not approval:
        raise SystemExit("direct user approval text is required")
    frame.setdefault("superseded_passes", []).append({
        "at": now_iso(),
        "current_candidate": frame.get("current_candidate"),
        "reviews": list(frame.get("reviews") or []),
        "reason": args.reason,
    })
    frame["status"] = "REPAIR_AUTHORIZED"
    frame["repair_authorization"] = {
        "at": now_iso(),
        "note": args.reason,
        "user_approved": True,
        "delegated_auto_review": False,
        "approval_basis": "direct_user_review_passed_repair",
        "approval_text": approval,
    }
    data["updated_at"] = now_iso()
    save_json(path, data)
    print(f"{key}: REPAIR_AUTHORIZED (direct-user passed-frame authority change recorded)")


def _refresh_authority_derived_caches(ep: Path) -> None:
    """Rebuild stale derived authority caches before resolving a new frame contract.

    Authority refresh is specifically entered because upstream authority changed.
    A derived cache must never create a circular prerequisite where the refreshed
    Frame Contract is required before the cache derived from that authority can be
    rebuilt. Only deterministic derived caches are touched here; locked source
    contracts and review evidence are never rewritten.
    """
    import character_appearance_anchor
    errors = character_appearance_anchor.verify(ep)
    rebuildable = {
        "CHARACTER_APPEARANCE_ANCHOR_STALE",
        "CHARACTER_APPEARANCE_ANCHOR_MISSING:run character_appearance_anchor.py build",
    }
    if errors and all(error in rebuildable for error in errors):
        character_appearance_anchor.build(ep, write=True)


def cmd_authorize_authority_refresh(args: argparse.Namespace) -> None:
    """Reopen a ready/passed frame after non-content authority or contract drift.

    This path is audit-only and does not consume the single content-repair budget.
    It exists for cases such as Frame Contract / authenticity / continuity authority
    updates where existing pixels must be regenerated against the new provenance.

    A LOCKED frame is admitted here too: a shared authority/contract repair that lands
    after the release lock still only re-renders the same content decision, so it must
    not consume the ordinary content-repair counter. The superseded lock is preserved.
    """
    ep = episode_dir(args.episode_dir)
    path, data = get_ledger(ep)
    key, frame = frame_obj(data, args.frame)
    if frame["status"] not in {"PASSED", "ORIGINAL_READY", "REPAIR_READY", "LOCKED", "NEEDS_USER"}:
        raise SystemExit(f"authority refresh requires PASSED/ORIGINAL_READY/REPAIR_READY/LOCKED/NEEDS_USER, got {frame['status']}")
    approval = args.approval_text.strip()
    if not approval:
        raise SystemExit("direct user approval text is required")
    _refresh_authority_derived_caches(ep)
    current_contract = current_frame_contract_provenance(ep, key)
    if not current_contract:
        raise SystemExit("current frame contract provenance missing")
    prior_lock = frame.get("lock") if frame["status"] == "LOCKED" else None
    if prior_lock:
        frame.setdefault("superseded_locks", []).append({"at": now_iso(), "lock": prior_lock, "approved_asset": frame.get("approved_asset")})
    frame.setdefault("authority_refresh_history", []).append({
        "at": now_iso(),
        "previous_status": frame.get("status"),
        "current_candidate": frame.get("current_candidate"),
        "reviews": list(frame.get("reviews") or []),
        "reason": args.reason,
    })
    frame["status"] = "AUTHORITY_REFRESH_AUTHORIZED"
    frame["authority_refresh_authorization"] = {
        "at": now_iso(),
        "reason": args.reason,
        "approval_text": approval,
        "approval_basis": "direct_user_authority_contract_refresh",
        "frame_contract_sha256": current_contract.get("contract_sha256"),
        "content_repair_budget_unchanged": True,
    }
    data["updated_at"] = now_iso()
    save_json(path, data)
    print(f"{key}: AUTHORITY_REFRESH_AUTHORIZED (content repair budget unchanged)")


def authorize_machine_contract_refresh(ep: Path, frame_number: int, *, reason: str) -> dict:
    """Reopen a candidate only when its recorded generation contract is provably stale.

    This is deterministic recovery, not a user semantic decision. The old
    candidate and attempt remain audit history and the content repair budget is
    unchanged.
    """
    ep = Path(ep).resolve()
    path, data = get_ledger(ep)
    key, frame = frame_obj(data, frame_number)
    allowed = {"PASSED", "ORIGINAL_READY", "REPAIR_READY", "LOCKED", "NEEDS_USER"}
    current_contract = current_frame_contract_provenance(ep, key) or {}
    if frame.get("status") == "AUTHORITY_REFRESH_AUTHORIZED":
        auth = frame.get("authority_refresh_authorization") or {}
        if (
            str(auth.get("approval_basis") or "") == "machine_verified_frame_contract_drift"
            and str(auth.get("frame_contract_sha256") or "").lower()
            == str(current_contract.get("contract_sha256") or "").lower()
        ):
            return {
                "status": "REUSED",
                "frame": int(frame_number),
                "frame_contract_sha256": current_contract.get("contract_sha256"),
            }
    if frame.get("status") not in allowed:
        raise ValueError(f"machine contract refresh requires {sorted(allowed)}, got {frame.get('status')}")
    if not current_contract:
        raise ValueError("current frame contract provenance missing")
    candidate = frame.get("current_candidate") or {}
    candidate_sha = str(candidate.get("sha256") or "").lower()
    if not candidate_sha:
        raise ValueError("machine contract refresh requires current candidate sha256")
    attempt = next(
        (
            row for row in reversed(frame.get("attempts") or [])
            if str(((row or {}).get("candidate") or {}).get("sha256") or "").lower() == candidate_sha
        ),
        None,
    )
    if not isinstance(attempt, dict):
        raise ValueError("machine contract refresh requires matching generation attempt")
    recorded = (attempt.get("request") or {}).get("frame_contract")
    errors = resolved_frame_contract.verify_recorded_provenance(ep, key, recorded)
    if not any("frame_contract_sha256 stale" in str(error) for error in errors):
        raise ValueError("machine contract refresh refused: current candidate is not stale against Frame Contract")
    previous_contract = str((recorded or {}).get("contract_sha256") or "")
    prior_status = str(frame.get("status") or "")
    prior_lock = frame.get("lock") if prior_status == "LOCKED" else None
    if prior_lock:
        frame.setdefault("superseded_locks", []).append({
            "at": now_iso(), "lock": prior_lock, "approved_asset": frame.get("approved_asset")
        })
    frame.setdefault("authority_refresh_history", []).append({
        "at": now_iso(),
        "previous_status": prior_status,
        "current_candidate": frame.get("current_candidate"),
        "reviews": list(frame.get("reviews") or []),
        "reason": reason,
        "authorization_basis": "machine_verified_frame_contract_drift",
        "previous_frame_contract_sha256": previous_contract,
        "current_frame_contract_sha256": current_contract.get("contract_sha256"),
    })
    frame["status"] = "AUTHORITY_REFRESH_AUTHORIZED"
    frame["authority_refresh_authorization"] = {
        "at": now_iso(),
        "reason": reason,
        "approval_basis": "machine_verified_frame_contract_drift",
        "frame_contract_sha256": current_contract.get("contract_sha256"),
        "previous_frame_contract_sha256": previous_contract,
        "candidate_sha256": candidate_sha,
        "verification_errors": list(errors),
        "content_repair_budget_unchanged": True,
    }
    data["updated_at"] = now_iso()
    save_json(path, data)
    return {
        "status": "AUTHORITY_REFRESH_AUTHORIZED",
        "frame": int(frame_number),
        "previous_frame_contract_sha256": previous_contract,
        "frame_contract_sha256": current_contract.get("contract_sha256"),
        "candidate_sha256": candidate_sha,
    }


def cmd_authorize_user_exception_repair(args: argparse.Namespace) -> None:
    """Record one explicit, non-delegable user exception after a hard repair failure.

    This does not reset the ordinary single-repair counter.  It exists so a
    directly quoted user exception is auditable rather than being disguised as
    an original request or silently accepted candidate.
    """
    ep = episode_dir(args.episode_dir)
    path, data = get_ledger(ep)
    key, frame = frame_obj(data, args.frame)
    if frame["status"] not in {"NEEDS_USER", "LOCKED", "PASSED"}:
        raise SystemExit(f"user exception repair requires NEEDS_USER, LOCKED, or downstream-invalidated PASSED; got {frame['status']}")
    if frame.get("content_repairs_used", 0) != 1:
        raise SystemExit("user exception repair requires exactly one ordinary content repair")
    if frame.get("user_exception_repairs_used", 0) >= 1:
        raise SystemExit("user exception repair limit reached")
    approval = args.approval_text.strip()
    if not approval:
        raise SystemExit("direct user approval text is required")
    prior_status = frame.get("status")
    prior_lock = frame.get("lock") if prior_status == "LOCKED" else None
    if prior_lock:
        frame.setdefault("superseded_locks", []).append({"at": now_iso(), "lock": prior_lock, "approved_asset": frame.get("approved_asset")})
        frame["lock"] = None
    if prior_status == "PASSED":
        frame.setdefault("superseded_passes", []).append({
            "at": now_iso(),
            "current_candidate": frame.get("current_candidate"),
            "approved_asset": frame.get("approved_asset"),
            "reviews": list(frame.get("reviews") or []),
            "reason": args.reason,
            "invalidation_basis": "later_downstream_actual_pixel_review",
        })
    if prior_status in {"PASSED", "LOCKED"}:
        # The downstream review explicitly invalidated the previously approved
        # pixels. Keep the old asset only inside superseded_* evidence; leaving
        # it active would make dependency checks treat a reopened baseline as
        # still approved and would leak a stale Pixel Master into dependents.
        frame["approved_asset"] = None
    frame["status"] = "EXCEPTION_REPAIR_AUTHORIZED"
    frame.setdefault("user_exception_authorizations", []).append({
        "at": now_iso(),
        "approval_text": approval,
        "reason": args.reason,
        "user_approved": True,
        "delegated_auto_review": False,
        "approval_basis": "direct_user_review_exception",
    })
    data["updated_at"] = now_iso()
    save_json(path, data)
    print(f"{key}: EXCEPTION_REPAIR_AUTHORIZED (direct user exception recorded)")


def mark_review_needs_user(ep: Path, frame_no: int | str, *, reason: str) -> dict:
    """Escalate an already accepted frame after a later machine review invalidates it.

    This records a *need for user authority* only.  It never fabricates user
    approval and never resets any repair counter.  The previously approved/locked
    asset is preserved under superseded evidence so downstream dependency checks
    cannot keep treating invalidated pixels as current authority.
    """
    ep = episode_dir(str(ep))
    path, data = get_ledger(ep)
    key, frame = frame_obj(data, frame_no)
    prior_status = str(frame.get("status") or "")
    if prior_status not in {"LOCKED", "PASSED", "WEAK_PASS"}:
        raise SystemExit(f"review escalation requires LOCKED, PASSED or WEAK_PASS, got {prior_status}")
    note = str(reason or "").strip()
    if not note:
        raise SystemExit("review escalation requires an evidence reason")

    if prior_status == "LOCKED":
        frame.setdefault("superseded_locks", []).append({
            "at": now_iso(),
            "lock": frame.get("lock"),
            "approved_asset": frame.get("approved_asset"),
            "reason": note,
        })
        frame["lock"] = None
    else:
        frame.setdefault("superseded_passes", []).append({
            "at": now_iso(),
            "current_candidate": frame.get("current_candidate"),
            "approved_asset": frame.get("approved_asset"),
            "reviews": list(frame.get("reviews") or []),
            "reason": note,
            "invalidation_basis": "later_downstream_actual_pixel_review",
        })
    frame["approved_asset"] = None
    frame.setdefault("reviews", []).append({
        "at": now_iso(),
        "decision": "needs_user",
        "notes": note,
    })
    frame.setdefault("review_escalations", []).append({
        "at": now_iso(),
        "from_status": prior_status,
        "to_status": "NEEDS_USER",
        "reason": note,
        "approval_granted": False,
        "basis": "later_machine_review_invalidated_accepted_pixels",
    })
    frame["status"] = "NEEDS_USER"
    data["updated_at"] = now_iso()
    save_json(path, data)
    return {"frame": key, "status": "NEEDS_USER", "from_status": prior_status}


def cmd_authorize_user_continuation_repair(args: argparse.Namespace) -> None:
    """Authorize exactly one additional content candidate after an explicit user continue decision.

    This is intentionally separate from the ordinary repair, authority refresh,
    and the one-shot user exception. It never resets those counters. Each call
    records the exact direct-user approval and authorizes one continuation
    generation transaction; another retry requires another explicit user
    decision plus a separate raw-candidate budget raise.
    """
    ep = episode_dir(args.episode_dir)
    path, data = get_ledger(ep)
    key, frame = frame_obj(data, args.frame)
    if frame["status"] != "NEEDS_USER":
        raise SystemExit(f"user continuation repair requires NEEDS_USER, got {frame['status']}")
    approval = args.approval_text.strip()
    if not approval:
        raise SystemExit("direct user approval text is required")
    frame["status"] = "USER_CONTINUATION_REPAIR_AUTHORIZED"
    frame.setdefault("user_continuation_authorizations", []).append({
        "at": now_iso(),
        "approval_text": approval,
        "reason": args.reason,
        "user_approved": True,
        "delegated_auto_review": False,
        "approval_basis": "direct_user_continuation_after_exhaustion",
        "continuation_index": int(frame.get("user_continuation_repairs_used") or 0) + 1,
    })
    data["updated_at"] = now_iso()
    save_json(path, data)
    print(f"{key}: USER_CONTINUATION_REPAIR_AUTHORIZED")


def _bounded_visual_candidate_acceptance_ready(ep: Path, key: str, frame: dict) -> tuple[bool, list[str]]:
    """Return whether the current NEEDS_USER pixels exhausted the bounded Visual Lock pool.

    This is a direct-user continuity lane, not a machine PASS. It is valid only when
    the current candidate is the exact SHA that the latest Visual Lock admission
    rejected and the automatic independent-candidate pool for the frame is exhausted.
    """
    import visual_lock_admission_state
    import visual_lock_candidate_pool

    frame_no = int(key)
    if frame_no not in set(visual_lock_candidate_pool.exhausted_frames(ep)):
        return False, []
    candidate_sha = str(((frame.get("current_candidate") or {}).get("sha256")) or "").lower()
    if not candidate_sha:
        return False, []
    admissions = visual_lock_admission_state.load(ep).get("items") or {}
    admission = next(
        (row for row in admissions.values()
         if isinstance(row, dict) and int(row.get("frame") or 0) == frame_no),
        None,
    )
    if not isinstance(admission, dict) or admission.get("status") != "FAIL":
        return False, []
    if str(admission.get("sha256") or "").lower() != candidate_sha:
        return False, []
    review_row = admission.get("review_row") or {}
    issues = [str(x) for x in (review_row.get("issues") or []) if str(x).strip()]
    if not issues:
        return False, []
    return True, issues


def cmd_accept_user_exception_candidate(args: argparse.Namespace) -> None:
    """Accept an already-generated exception candidate with direct user review.

    The ordinary repair and one direct-user exception remain fully recorded;
    this command only accepts that existing candidate and never resets either
    repair counter.
    """
    ep = episode_dir(args.episode_dir)
    path, data = get_ledger(ep)
    key, frame = frame_obj(data, args.frame)
    if frame["status"] != "NEEDS_USER":
        raise SystemExit(f"exception acceptance requires NEEDS_USER, got {frame['status']}")
    legacy_exception_lane = (
        frame.get("content_repairs_used", 0) == 1
        and frame.get("user_exception_repairs_used", 0) == 1
    )
    bounded_pool_lane, known_issues = _bounded_visual_candidate_acceptance_ready(ep, key, frame)
    if not legacy_exception_lane and not bounded_pool_lane:
        raise SystemExit("exception acceptance requires either one ordinary + one user-exception repair, or an exhausted SHA-bound Visual Lock candidate pool")
    approval = args.approval_text.strip()
    if not approval:
        raise SystemExit("direct user approval text is required")
    candidate = frame.get("current_candidate") or {}
    raw_path = candidate.get("path")
    if not raw_path:
        raise SystemExit("current exception candidate missing")
    candidate_path = (repo_root() / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path)
    if not candidate_path.is_file() or sha256_file(candidate_path) != str(candidate.get("sha256") or "").lower():
        raise SystemExit("current exception candidate missing or hash drifted")
    matching_attempt = None
    for attempt in reversed(frame.get("attempts") or []):
        if (attempt.get("candidate") or {}).get("sha256") == candidate.get("sha256"):
            matching_attempt = attempt
            break
    if not isinstance(matching_attempt, dict):
        raise SystemExit("current exception candidate has no matching generation attempt")
    verify_attempt_frame_contract_provenance(ep, key, matching_attempt)
    verify_attempt_visual_provenance(ep, matching_attempt)
    acceptance = {
        "at": now_iso(),
        "approval_text": approval,
        "reason": args.reason,
        "user_approved": True,
        "delegated_auto_review": False,
        "approval_basis": "direct_user_review_exception_acceptance",
        "acceptance_scope": ("bounded_visual_candidate_pool_exhausted" if bounded_pool_lane else "user_exception_repair"),
        "candidate_sha256": candidate["sha256"],
        "known_automatic_issues": known_issues,
    }
    frame.setdefault("user_exception_acceptances", []).append(acceptance)
    frame.setdefault("reviews", []).append({
        "at": acceptance["at"], "decision": "pass", "notes": "Direct user accepted existing exception candidate with known automatic issues preserved: " + args.reason,
        "approval_basis": acceptance["approval_basis"], "acceptance_scope": acceptance["acceptance_scope"],
        "candidate_sha256": candidate["sha256"], "known_automatic_issues": known_issues,
    })
    frame["status"] = "PASSED"
    data["updated_at"] = now_iso()
    save_json(path, data)
    print(f"{key}: PASSED (direct-user exception candidate acceptance recorded)")


def cmd_accept_after_retry_exhaustion(args: argparse.Namespace) -> None:
    """Record the user's explicit continuity override after bounded image retries.

    The existing, hash-bound candidate is retained; technical failures are not
    rewritten as successful generations. This decision only marks the frame
    accepted for production continuity and remains visible to final review.
    """
    ep = episode_dir(args.episode_dir)
    path, data = get_ledger(ep)
    key, frame = frame_obj(data, args.frame)
    if frame.get("status") != "TECH_FAILED":
        raise SystemExit(f"retry-exhaustion acceptance requires TECH_FAILED, got {frame.get('status')}")
    candidate = frame.get("current_candidate") or {}
    raw_path = candidate.get("path")
    if not raw_path:
        raise SystemExit("retry-exhaustion acceptance requires an existing candidate")
    candidate_path = (repo_root() / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
    if not candidate_path.is_file() or sha256_file(candidate_path) != str(candidate.get("sha256") or "").lower():
        raise SystemExit("retry-exhaustion candidate missing or hash drifted")
    matching = next((row for row in reversed(frame.get("attempts") or [])
                     if ((row.get("candidate") or {}).get("sha256") == candidate.get("sha256"))), None)
    if not isinstance(matching, dict) or matching.get("result") != "success":
        raise SystemExit("retry-exhaustion candidate has no successful source attempt")
    authority_refresh_fallback = False
    try:
        verify_attempt_frame_contract_provenance(ep, key, matching)
    except SystemExit:
        # The user explicitly authorized continuity after the new-contract
        # refresh exhausted its technical retries. Keep the old candidate
        # auditable; never rewrite its provenance as if it used the current
        # contract. Final semantic review applies the matching narrow exception.
        refresh = frame.get("authority_refresh_authorization") or {}
        current = current_frame_contract_provenance(ep, key) or {}
        if (frame.get("status") == "TECH_FAILED"
                and str(refresh.get("frame_contract_sha256") or "").lower()
                == str(current.get("contract_sha256") or "").lower()
                and str(refresh.get("frame_contract_sha256") or "").strip()):
            authority_refresh_fallback = True
        else:
            raise
    verify_attempt_visual_provenance(ep, matching)
    limit = int(storyos_config.get_path(storyos_config.load_config(), "production.technical_retry.max_attempts_per_item"))
    failures = []
    for attempt in reversed(frame.get("attempts") or []):
        if attempt.get("kind") != "repair":
            break
        if attempt.get("result") != "technical_failure":
            break
        failures.append(attempt)
    if len(failures) < limit:
        raise SystemExit(f"retry limit not reached: repair technical failures={len(failures)}, required={limit}")
    reason = str(args.reason or "").strip()
    if not reason:
        raise SystemExit("an auditable user-authorized reason is required")
    at = now_iso()
    decision = {
        "at": at,
        "decision": "pass",
        "notes": "User-authorized production-continuity acceptance after technical retry exhaustion: " + reason,
        "approval_basis": "direct_user_retry_exhaustion_override",
        "candidate_sha256": candidate["sha256"],
        "visual_quality_reviewed": False,
    }
    if authority_refresh_fallback:
        decision["authority_refresh_fallback"] = True
        decision["current_frame_contract_sha256"] = str(
            (frame.get("authority_refresh_authorization") or {}).get("frame_contract_sha256") or ""
        ).lower()
        decision["candidate_attempt_frame_contract_sha256"] = str(
            ((matching.get("request") or {}).get("frame_contract_sha256") or "")
        ).lower()
    frame.setdefault("reviews", []).append(decision)
    acceptance = {
        "at": at,
        "reason": reason,
        "candidate_sha256": candidate["sha256"],
        "technical_failures": len(failures),
        "required_failures": limit,
        "user_authorized": True,
        "visual_quality_reviewed": False,
    }
    if authority_refresh_fallback:
        acceptance["authority_refresh_fallback"] = True
        acceptance["current_frame_contract_sha256"] = decision["current_frame_contract_sha256"]
        acceptance["candidate_attempt_frame_contract_sha256"] = decision["candidate_attempt_frame_contract_sha256"]
    frame.setdefault("retry_exhaustion_acceptances", []).append(acceptance)
    frame["status"] = "PASSED"
    data["updated_at"] = at
    save_json(path, data)
    print(f"{key}: PASSED (user-authorized retry-exhaustion acceptance; candidate retained for final review)")


def force_pass_content_exhaustion(ep: Path, frame_number: str, reason: str) -> dict:
    """Accept an existing proven candidate once the content repair budget is spent."""
    path, data = get_ledger(ep)
    key, frame = frame_obj(data, frame_number)
    limit = content_repair_limit(data)
    used = int(frame.get("content_repairs_used") or 0)
    if used < limit:
        raise ValueError(f"frame {key} repair budget remains: {used}/{limit}")
    if frame.get("status") not in {"ORIGINAL_READY", "REPAIR_READY", "PASSED", "LOCKED", "NEEDS_USER"}:
        raise ValueError(f"frame {key} has no reviewable candidate: {frame.get('status')}")
    candidate = frame.get("current_candidate") or {}
    raw_path = candidate.get("path")
    candidate_sha = str(candidate.get("sha256") or "").lower()
    if not raw_path or not candidate_sha:
        raise ValueError(f"frame {key} has no candidate")
    candidate_path = (repo_root() / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
    if not candidate_path.is_file() or sha256_file(candidate_path) != candidate_sha:
        raise ValueError(f"frame {key} candidate missing or drifted")
    matching = next((a for a in reversed(frame.get("attempts") or [])
                     if (a.get("candidate") or {}).get("sha256") == candidate_sha and a.get("result") == "success"), None)
    if matching is None:
        raise ValueError(f"frame {key} has no successful generation attempt")
    verify_attempt_frame_contract_provenance(ep, key, matching)
    verify_attempt_visual_provenance(ep, matching)
    marker = {"at": now_iso(), "forced_pass": True, "basis": "direct_user_repair_exhaustion_policy",
              "reason": reason, "candidate_sha256": candidate_sha,
              "content_repairs_used": used, "content_repair_limit": limit,
              "visual_quality_reviewed": False}
    frame.setdefault("forced_passes", []).append(marker)
    frame.setdefault("reviews", []).append({"at": marker["at"], "decision": "pass",
        "forced_pass": True, "notes": reason, "candidate_sha256": candidate_sha})
    if frame["status"] != "LOCKED":
        frame["status"] = "PASSED"
    data["updated_at"] = marker["at"]
    save_json(path, data)
    return marker


def cmd_accept_user_contract_exception(args: argparse.Namespace) -> None:
    """Keep an existing candidate under an explicitly selected old contract.

    The candidate must already exist, its attempt must carry the old SHA, and
    the Episode sidecar must contain the direct-user contract exception. This
    changes only the ledger decision; it never rewrites the current contract.
    """
    ep = episode_dir(args.episode_dir)
    path, data = get_ledger(ep)
    key, frame = frame_obj(data, args.frame)
    allowed = {"TECH_FAILED", "AUTHORITY_REFRESH_AUTHORIZED", "ORIGINAL_READY", "REPAIR_READY", "PASSED", "WEAK_PASS", "NEEDS_USER"}
    if frame.get("status") not in allowed:
        raise SystemExit(f"contract exception acceptance requires one of {sorted(allowed)}, got {frame.get('status')}")
    approval = args.approval_text.strip()
    if not approval:
        raise SystemExit("direct user approval text is required")
    candidate = frame.get("current_candidate") or {}
    raw_path = candidate.get("path")
    candidate_sha = str(candidate.get("sha256") or "").lower()
    if not raw_path or not candidate_sha:
        raise SystemExit("current candidate missing")
    candidate_path = (repo_root() / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path)
    if not candidate_path.is_file() or sha256_file(candidate_path) != candidate_sha:
        raise SystemExit("current candidate missing or hash drifted")
    matching_attempt = next(
        (row for row in reversed(frame.get("attempts") or [])
         if str(((row or {}).get("candidate") or {}).get("sha256") or "").lower() == candidate_sha),
        None,
    )
    if not isinstance(matching_attempt, dict):
        raise SystemExit("current candidate has no matching generation attempt")
    request = matching_attempt.get("request") or {}
    recorded = request.get("frame_contract") or {}
    recorded_sha = str(recorded.get("contract_sha256") or "").lower()
    if not recorded_sha or not resolved_frame_contract.recorded_contract_matches_current(ep, key, recorded_sha):
        raise SystemExit("candidate is not bound to a current or explicitly user-approved contract exception")
    verify_attempt_visual_provenance(ep, matching_attempt)
    prior_status = str(frame.get("status") or "")
    acceptance = {
        "at": now_iso(),
        "approval_text": approval,
        "reason": args.reason,
        "user_approved": True,
        "delegated_auto_review": False,
        "approval_basis": "direct_user_contract_exception",
        "frame_contract_sha256": recorded_sha,
        "candidate_sha256": candidate_sha,
        "previous_status": prior_status,
    }
    frame.setdefault("contract_exception_acceptances", []).append(acceptance)
    frame.setdefault("reviews", []).append({
        "at": acceptance["at"],
        "decision": "pass",
        "notes": "Direct user selected the existing candidate under the explicitly approved original Frame Contract: " + args.reason,
        "approval_basis": acceptance["approval_basis"],
        "candidate_sha256": candidate_sha,
        "frame_contract_sha256": recorded_sha,
    })
    frame["status"] = "PASSED"
    data["updated_at"] = now_iso()
    save_json(path, data)
    print(f"{key}: PASSED (direct-user original-contract exception recorded)")


def cmd_promote(args: argparse.Namespace) -> None:
    ep = episode_dir(args.episode_dir)
    path, data = get_ledger(ep)
    key, frame = frame_obj(data, args.frame)
    if frame["status"] not in {"PASSED", "WEAK_PASS"}:
        raise SystemExit(f"promote requires PASSED/WEAK_PASS and refuses to overwrite LOCKED assets, got {frame['status']}")
    candidate_info = frame.get("current_candidate")
    if not isinstance(candidate_info, dict) or not candidate_info.get("path"):
        raise SystemExit("current candidate missing")
    src_raw = candidate_info["path"]
    src = (repo_root() / src_raw).resolve() if not Path(src_raw).is_absolute() else Path(src_raw)
    if not src.is_file():
        raise SystemExit(f"candidate file missing: {src}")
    approved_dir = ep / data["asset_roots"]["approved"]
    approved_dir.mkdir(parents=True, exist_ok=True)
    dst = approved_dir / f"{key}{safe_ext(src)}"
    shutil.copy2(src, dst)
    info = {
        "path": repo_relative(dst),
        "sha256": sha256_file(dst),
        "width": data["canvas"]["width"],
        "height": data["canvas"]["height"],
        "promoted_at": now_iso(),
        "source_sha256": candidate_info.get("sha256"),
    }
    frame["approved_asset"] = info
    data["updated_at"] = now_iso()
    save_json(path, data)
    print(f"{key}: approved -> {dst}")
    _freeze_visual_profile_after_promote(ep, key)


def cmd_lock(args: argparse.Namespace) -> None:
    ep = episode_dir(args.episode_dir)
    path, data = get_ledger(ep)
    key, frame = frame_obj(data, args.frame)
    approved = frame.get("approved_asset")
    if not isinstance(approved, dict) or not approved.get("sha256"):
        raise SystemExit("promote approved asset before locking")
    frame["lock"] = {"at": now_iso(), "sha256": approved["sha256"], "reason": args.reason}
    frame["status"] = "LOCKED"
    data["updated_at"] = now_iso()
    save_json(path, data)
    print(f"{key}: LOCKED sha256={approved['sha256']}")


def cmd_batch_begin(args: argparse.Namespace) -> None:
    ep = episode_dir(args.episode_dir)
    path, data = get_ledger(ep)
    frames = parse_frame_set(args.frames)
    valid = data.get("frames") or {}
    missing = [x for x in frames if x not in valid]
    if missing:
        raise SystemExit(f"unknown frames: {missing}")
    batch = {
        "batch_id": uuid.uuid4().hex[:10],
        "started_at": now_iso(),
        "ended_at": None,
        "frames": frames,
        "max_successes": args.max_successes,
        "note": args.note,
        "status": "open",
    }
    data.setdefault("batches", []).append(batch)
    data["updated_at"] = now_iso()
    save_json(path, data)
    print(f"batch {batch['batch_id']} open: {','.join(frames)}")


def cmd_batch_end(args: argparse.Namespace) -> None:
    ep = episode_dir(args.episode_dir)
    path, data = get_ledger(ep)
    for batch in reversed(data.get("batches") or []):
        if batch.get("batch_id") == args.batch_id:
            if batch.get("status") != "open":
                raise SystemExit("batch already closed")
            batch["status"] = "closed"
            batch["ended_at"] = now_iso()
            batch["summary"] = args.summary
            data["updated_at"] = now_iso()
            save_json(path, data)
            print(f"batch {args.batch_id} closed")
            return
    raise SystemExit(f"batch not found: {args.batch_id}")


def cmd_audit(args: argparse.Namespace) -> None:
    ep = episode_dir(args.episode_dir)
    _, data = get_ledger(ep)
    failures: list[str] = []
    warnings: list[str] = []
    expected = (data["canvas"]["width"], data["canvas"]["height"])
    for key, frame in (data.get("frames") or {}).items():
        status = frame.get("status")
        if status not in FRAME_STATES:
            failures.append(f"{key}: invalid status {status!r}")
        if frame.get("content_repairs_used", 0) > content_repair_limit(data):
            failures.append(f"{key}: content repair count exceeds frozen policy")
        exception_repairs = frame.get("user_exception_repairs_used", 0)
        approvals = frame.get("user_exception_authorizations") or []
        if exception_repairs > 1:
            failures.append(f"{key}: user exception repair count > 1")
        if exception_repairs and not any(
            item.get("user_approved") is True
            and item.get("approval_basis") == "direct_user_review_exception"
            and item.get("approval_text")
            for item in approvals if isinstance(item, dict)
        ):
            failures.append(f"{key}: user exception repair lacks direct user approval evidence")
        approved = frame.get("approved_asset")
        if isinstance(approved, dict) and approved.get("path"):
            p = (repo_root() / approved["path"]).resolve()
            if not p.is_file():
                failures.append(f"{key}: approved asset missing: {approved['path']}")
            else:
                dims = image_dimensions(p)
                if dims != expected:
                    failures.append(f"{key}: approved size {dims}, expected {expected}")
                actual = sha256_file(p)
                if actual != approved.get("sha256"):
                    failures.append(f"{key}: approved hash drift")
        lock = frame.get("lock")
        if isinstance(lock, dict) and isinstance(approved, dict) and lock.get("sha256") != approved.get("sha256"):
            failures.append(f"{key}: lock hash != approved hash")
        if args.require_passed and status not in ACCEPTED_LEDGER_STATES:
            failures.append(f"{key}: not passed ({status})")
        if status == "TECH_FAILED":
            warnings.append(f"{key}: pending technical retry")
    for item in warnings:
        print(f"[WARN] {item}")
    for item in failures:
        print(f"[FAIL] {item}")
    if failures:
        raise SystemExit(1)
    print(f"PASS: production ledger; canvas={data['canvas']['aspect_ratio']} {expected[0]}脳{expected[1]}")


def cmd_show(args: argparse.Namespace) -> None:
    ep = episode_dir(args.episode_dir)
    _, data = get_ledger(ep)
    if args.frame:
        key, frame = frame_obj(data, args.frame)
        print(json.dumps({key: frame}, ensure_ascii=False, indent=2))
    else:
        summary = {
            "canvas": data.get("canvas"),
            "frames": {k: v.get("status") for k, v in (data.get("frames") or {}).items()},
            "open_batches": [b for b in data.get("batches") or [] if b.get("status") == "open"],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
