#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-admission SHA-bound Visual Lock PASS evidence.

A Visual Lock admission PASS is reusable only while all semantic bindings remain
identical: role/frame, pixel SHA, Resolved Frame Contract SHA, visual profile SHA,
and Story OS review version. This prevents unchanged passed pixels from being
re-reviewed just because a sibling admission changed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import story_json
import frame_contract
import production_ledger

REL = Path("meta/visual-lock-admissions.json")
GATES_REL = Path("meta/story-gates.json")
LEDGER_REL = Path("meta/production-ledger.json")
SCHEMA_VERSION = 1
ACCEPTED_ADMISSION_STATUSES = frozenset({"PASS", "WEAK_PASS"})


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _read(path: Path) -> dict:
    data = story_json.read_json(path, default={})
    return data if isinstance(data, dict) else {}


def load(ep: Path) -> dict:
    data = _read(Path(ep) / REL)
    if data.get("schema_version") != SCHEMA_VERSION:
        return {"schema_version": SCHEMA_VERSION, "updated_at": None, "items": {}}
    if not isinstance(data.get("items"), dict):
        data["items"] = {}
    return data


def _checks_pass(row: dict, required_checks: tuple[str, ...]) -> bool:
    checks = row.get("checks") or {}
    return row.get("issues") in ([], None) and all(checks.get(key) is True for key in required_checks)


def binding(asset: dict, *, profile_sha256: str, story_os_version: str) -> dict:
    row = {
        "id": str(asset.get("id") or ""),
        "role": str(asset.get("role") or ""),
        "frame": int(asset.get("frame") or 0),
        "sha256": str(asset.get("sha256") or "").lower(),
        "frame_contract_sha256": str(asset.get("frame_contract_sha256") or "").lower(),
        "profile_sha256": str(profile_sha256 or "").lower(),
        "story_os_version": str(story_os_version or ""),
    }
    revision_id = str(asset.get("production_revision_id") or "").strip()
    if revision_id:
        row["production_revision_id"] = revision_id
    return row


def valid_pass(ep: Path, asset: dict, *, profile_sha256: str, story_os_version: str) -> dict | None:
    data = load(ep)
    item = (data.get("items") or {}).get(str(asset.get("id") or ""))
    if not isinstance(item, dict) or item.get("status") not in ACCEPTED_ADMISSION_STATUSES:
        return None
    expected = binding(asset, profile_sha256=profile_sha256, story_os_version=story_os_version)
    for key, value in expected.items():
        actual = item.get(key)
        if key in {"sha256", "frame_contract_sha256", "profile_sha256"}:
            actual = str(actual or "").lower()
        if key == "frame_contract_sha256" and actual != value:
            if frame_contract.recorded_contract_matches_current(ep, expected["frame"], actual):
                continue
        if actual != value:
            return None
    review_row = item.get("review_row")
    return item if isinstance(review_row, dict) else None


def dirty_assets(ep: Path, assets: list[dict], *, profile_sha256: str, story_os_version: str) -> list[dict]:
    return [
        asset for asset in assets
        if valid_pass(ep, asset, profile_sha256=profile_sha256, story_os_version=story_os_version) is None
    ]


def reusable_review_rows(ep: Path, assets: list[dict], *, profile_sha256: str, story_os_version: str) -> list[dict]:
    rows: list[dict] = []
    for asset in assets:
        item = valid_pass(ep, asset, profile_sha256=profile_sha256, story_os_version=story_os_version)
        if item is None:
            continue
        row = dict(item["review_row"])
        row["admission_reused"] = True
        row["admission_evidence_at"] = item.get("reviewed_at")
        rows.append(row)
    return rows


def record_rows(
    ep: Path,
    *,
    rows: list[dict],
    assets: list[dict],
    profile_sha256: str,
    story_os_version: str,
    required_checks: tuple[str, ...],
    provenance: dict,
    attempt: int,
) -> None:
    ep = Path(ep)
    data = load(ep)
    items = data.setdefault("items", {})
    by_id = {str(asset.get("id") or ""): asset for asset in assets}
    for row in rows:
        rid = str(row.get("id") or "")
        asset = by_id.get(rid)
        if asset is None:
            continue
        entry = binding(asset, profile_sha256=profile_sha256, story_os_version=story_os_version)
        passed = _checks_pass(row, required_checks)
        entry.update({
            "status": "PASS" if passed else "FAIL",
            "reviewed_at": now(),
            "attempt": int(attempt),
            "review_row": dict(row),
            "provenance": dict(provenance or {}),
        })
        entry["review_row"].pop("admission_reused", None)
        entry["review_row"].pop("admission_evidence_at", None)
        items[rid] = entry
    data["updated_at"] = now()
    story_json.write_json(ep / REL, data)


def record_direct_user_pass(
    ep: Path,
    *,
    asset: dict,
    review_row: dict,
    profile_sha256: str,
    story_os_version: str,
    user_statement: str,
    source_review_attempt: int,
) -> dict:
    """Record an explicit user visual-admission override.

    The automatic critic row is retained verbatim. The PASS status is a separate,
    SHA-bound authority entry whose provenance states that the user accepted the
    current pixels after seeing the known automatic defect. This keeps the
    machine review honest while allowing an explicit direct-user decision.
    """
    statement = str(user_statement or "").strip()
    if not statement:
        raise ValueError("direct user visual-admission statement is required")
    ep = Path(ep)
    data = load(ep)
    entry = binding(asset, profile_sha256=profile_sha256, story_os_version=story_os_version)
    entry.update({
        "status": "PASS",
        "reviewed_at": now(),
        "attempt": int(source_review_attempt),
        "review_row": dict(review_row),
        "provenance": {
            "approval_basis": "direct_user_visual_admission",
            "user_statement": statement,
            "automatic_review_status": "FAIL",
            "automatic_review_attempt": int(source_review_attempt),
        },
        "direct_user_override": {
            "accepted": True,
            "statement": statement,
            "accepted_at": now(),
            "known_automatic_defect": True,
        },
    })
    data.setdefault("items", {})[str(asset.get("id") or "")] = entry
    data["updated_at"] = now()
    story_json.write_json(ep / REL, data)
    return entry


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _current_profile_sha(ep: Path) -> str:
    ep = Path(ep).resolve()
    profile = _read(ep / "meta/visual-profile.json")
    raw = str(profile.get("profile_path") or "")
    if not raw:
        return ""
    path = Path(raw)
    if not path.is_absolute():
        path = ep.parents[1] / path
    return _sha256_file(path) if path.is_file() else ""


def _version_tuple(raw: object) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(raw or "").split("."))
    except Exception:
        return (0,)


def _current_story_os_version(ep: Path) -> str:
    versions: list[tuple[tuple[int, ...], str]] = []
    for rel in ("meta/episode-state.json", "meta/release-manifest.json", "meta/story-gates.json"):
        data = _read(Path(ep) / rel)
        raw = str(data.get("tool_version") or "")
        vt = _version_tuple(raw)
        if vt != (0,):
            versions.append((vt, raw))
    return max(versions, key=lambda x: x[0])[1] if versions else ""


def valid_pass_for_gate_row(ep: Path, review_row: dict) -> bool:
    """Fast candidate-pool guard using current calibration bindings.

    The latest review may contain a stochastic FAIL for an unchanged admission.
    A still-valid SHA-bound PASS registry entry wins until one of its bindings
    actually changes.
    """
    gates = _read(Path(ep) / GATES_REL)
    items = (((gates.get("visual") or {}).get("calibration") or {}).get("items") or [])
    rid = str(review_row.get("id") or "")
    gate = next((x for x in items if isinstance(x, dict) and str(x.get("id") or "") == rid), None)
    if gate is None:
        return False
    data = load(ep)
    entry = (data.get("items") or {}).get(rid)
    if not isinstance(entry, dict) or entry.get("status") not in ACCEPTED_ADMISSION_STATUSES:
        return False
    current_profile_sha = _current_profile_sha(ep)
    current_version = _current_story_os_version(ep)
    return (
        int(entry.get("frame") or 0) == int(gate.get("frame") or 0)
        and str(entry.get("sha256") or "").lower() == str(gate.get("sha256") or "").lower()
        and (
            str(entry.get("frame_contract_sha256") or "").lower()
            == str(gate.get("frame_contract_sha256") or "").lower()
            or frame_contract.recorded_contract_matches_current(
                ep, gate["frame"], str(entry.get("frame_contract_sha256") or ""))
        )
        and bool(current_profile_sha)
        and str(entry.get("profile_sha256") or "").lower() == current_profile_sha.lower()
        and bool(current_version)
        and str(entry.get("story_os_version") or "") == current_version
    )


def _parse_iso(raw: object) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
    except Exception:
        return None


def _critic_payload(path: Path) -> dict | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None
    payload = None
    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") != "item.completed":
            continue
        item = obj.get("item") or {}
        if item.get("type") != "agent_message":
            continue
        try:
            parsed = json.loads(str(item.get("text") or ""))
        except Exception:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("calibration"), list):
            payload = parsed
    return payload


def _latest_success_at(ledger_frame: dict, cutoff: dt.datetime) -> dict | None:
    latest = None
    latest_at = None
    for attempt in ledger_frame.get("attempts") or []:
        if not isinstance(attempt, dict) or attempt.get("result") != "success":
            continue
        completed = _parse_iso(attempt.get("completed_at"))
        candidate = attempt.get("candidate") or {}
        if completed is None or completed > cutoff or not candidate.get("sha256"):
            continue
        if latest_at is None or completed > latest_at:
            latest = attempt
            latest_at = completed
    return latest


def reconcile_historical_passes(
    ep: Path,
    *,
    assets: list[dict],
    profile_sha256: str,
    story_os_version: str,
    required_checks: tuple[str, ...],
) -> dict:
    """Recover valid per-frame PASS evidence from older critic logs.

    A historical PASS is accepted only when the latest successful candidate at
    that log's completion time is the exact current asset SHA and its generation
    request binds the exact current Frame Contract and visual profile SHA.
    Later stochastic re-reviews of the unchanged binding cannot erase it.
    """
    ep = Path(ep)
    ledger = production_ledger.load_authority(ep, default={}) or {}
    by_id = {str(asset.get("id") or ""): asset for asset in assets}
    recovered: dict[str, dict] = {}
    logs = sorted((ep / "meta").glob("visual-lock-critic-attempt-*.jsonl"), key=lambda p: p.stat().st_mtime)
    for log in logs:
        payload = _critic_payload(log)
        if payload is None:
            continue
        cutoff = dt.datetime.fromtimestamp(log.stat().st_mtime, tz=dt.timezone.utc).astimezone()
        for raw_row in payload.get("calibration") or []:
            if not isinstance(raw_row, dict) or not _checks_pass(raw_row, required_checks):
                continue
            rid = str(raw_row.get("id") or "")
            asset = by_id.get(rid)
            if asset is None or rid in recovered:
                continue
            frame = int(asset.get("frame") or 0)
            ledger_frame = ((ledger.get("frames") or {}).get(f"{frame:02d}") or {})
            latest = _latest_success_at(ledger_frame, cutoff)
            if latest is None:
                continue
            candidate = latest.get("candidate") or {}
            request = latest.get("request") or {}
            request_fc = str(request.get("frame_contract_sha256") or ((request.get("frame_contract") or {}).get("contract_sha256")) or "").lower()
            request_profile = str(((request.get("visual_profile") or {}).get("profile_sha256")) or "").lower()
            if str(candidate.get("sha256") or "").lower() != str(asset.get("sha256") or "").lower():
                continue
            if not frame_contract.recorded_contract_matches_current(ep, frame, request_fc):
                continue
            if request_profile != str(profile_sha256 or "").lower():
                continue
            row = dict(raw_row)
            row.update({
                "sha256": str(asset.get("sha256") or "").lower(),
                "frame_contract_sha256": str(asset.get("frame_contract_sha256") or "").lower(),
                "frame": frame,
                "role": str(asset.get("role") or ""),
            })
            provenance = {
                "reconciled_from_historical_critic": True,
                "log": log.relative_to(ep).as_posix(),
                "candidate_attempt_id": latest.get("attempt_id"),
                "candidate_completed_at": latest.get("completed_at"),
            }
            record_rows(
                ep,
                rows=[row],
                assets=assets,
                profile_sha256=profile_sha256,
                story_os_version=story_os_version,
                required_checks=required_checks,
                provenance=provenance,
                attempt=0,
            )
            restore_ledger_pass(
                ep,
                asset=asset,
                evidence_note=f"Visual Lock historical SHA-bound PASS reconciled from {log.name}",
            )
            recovered[rid] = {
                "frame": frame,
                "sha256": asset.get("sha256"),
                "frame_contract_sha256": asset.get("frame_contract_sha256"),
                "source_log": log.name,
            }
    return {"status": "PASS", "recovered": recovered, "dirty_frames": [int(x.get("frame") or 0) for x in assets if str(x.get("id") or "") not in recovered and valid_pass(ep, x, profile_sha256=profile_sha256, story_os_version=story_os_version) is None]}


def sync_gate_decisions(ep: Path) -> dict:
    """Project valid per-frame admission evidence back into story-gates decisions."""
    ep = Path(ep)
    gates_path = ep / GATES_REL
    gates = _read(gates_path)
    items = (((gates.get("visual") or {}).get("calibration") or {}).get("items") or [])
    registry = load(ep).get("items") or {}
    passed_frames: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("id") or "")
        entry = registry.get(rid)
        valid = (
            isinstance(entry, dict)
            and entry.get("status") in ACCEPTED_ADMISSION_STATUSES
            and int(entry.get("frame") or 0) == int(item.get("frame") or 0)
            and str(entry.get("sha256") or "").lower() == str(item.get("sha256") or "").lower()
            and str(entry.get("frame_contract_sha256") or "").lower() == str(item.get("frame_contract_sha256") or "").lower()
        )
        if valid:
            item["decision"] = "passed"
            if entry.get("status") == "WEAK_PASS":
                item["weak_pass"] = True
                item["weak_pass_reason"] = str((entry.get("weak_pass") or {}).get("weak_pass_reason") or "")
                item["approved_by_policy"] = str((entry.get("weak_pass") or {}).get("approved_by_policy") or "")
            passed_frames.append(int(item.get("frame") or 0))
    reviews = gates.setdefault("reviews", {})
    reviews["visual_admission"] = "passed" if items and all(
        isinstance(item, dict) and item.get("decision") == "passed" for item in items
    ) else "failed"
    story_json.write_json(gates_path, gates)
    return {"passed_frames": sorted(set(passed_frames)), "all_passed": reviews["visual_admission"] == "passed"}


def restore_ledger_pass(ep: Path, *, asset: dict, evidence_note: str) -> bool:
    """Reconcile a proven admission PASS into the canonical production ledger.

    This is intentionally stricter than the ordinary review command: it only
    restores the exact current candidate SHA and records explicit reconciliation
    evidence. It never changes the candidate or consumes/returns repair budget.
    """
    ep = Path(ep)
    path = ep / LEDGER_REL
    ledger = production_ledger.load_authority(ep, default={}) or {}
    frame_key = f"{int(asset.get('frame') or 0):02d}"
    frame = (ledger.get("frames") or {}).get(frame_key)
    if not isinstance(frame, dict):
        return False
    candidate = frame.get("current_candidate") or {}
    if str(candidate.get("sha256") or "").lower() != str(asset.get("sha256") or "").lower():
        return False
    if frame.get("status") in {"PASSED", "WEAK_PASS", "LOCKED"}:
        return True
    frame.setdefault("reviews", []).append({
        "at": now(),
        "decision": "pass",
        "notes": evidence_note,
        "reconciled": True,
        "candidate_sha256": str(asset.get("sha256") or "").lower(),
        "frame_contract_sha256": str(asset.get("frame_contract_sha256") or "").lower(),
    })
    frame["status"] = "PASSED"
    ledger["updated_at"] = now()
    production_ledger.save_json(path, ledger)
    return True


def restore_ledger_fail(ep: Path, *, asset: dict, evidence_note: str) -> bool:
    """Reconcile a current SHA-bound Visual Lock FAIL into NEEDS_USER.

    Independent Visual Lock candidates are provider-successful images, so the
    Production Ledger can temporarily be PASSED before the admission critic runs.
    A current FAIL admission must be able to reopen only that exact candidate for
    the bounded candidate pool. No stale pixel or Frame Contract binding is allowed.
    """
    ep = Path(ep)
    registry = load(ep)
    rid = str(asset.get("id") or "")
    entry = (registry.get("items") or {}).get(rid)
    if not isinstance(entry, dict) or entry.get("status") != "FAIL":
        return False
    if int(entry.get("frame") or 0) != int(asset.get("frame") or 0):
        return False
    if str(entry.get("sha256") or "").lower() != str(asset.get("sha256") or "").lower():
        return False
    if str(entry.get("frame_contract_sha256") or "").lower() != str(asset.get("frame_contract_sha256") or "").lower():
        return False

    path = ep / LEDGER_REL
    ledger = production_ledger.load_authority(ep, default={}) or {}
    frame_key = f"{int(asset.get('frame') or 0):02d}"
    frame = (ledger.get("frames") or {}).get(frame_key)
    if not isinstance(frame, dict):
        return False
    candidate = frame.get("current_candidate") or {}
    if str(candidate.get("sha256") or "").lower() != str(asset.get("sha256") or "").lower():
        return False
    if frame.get("status") == "NEEDS_USER":
        return True
    if frame.get("status") != "PASSED":
        return False
    frame.setdefault("reviews", []).append({
        "at": now(),
        "decision": "repair",
        "notes": evidence_note,
        "reconciled": True,
        "source": "visual_lock_admission_fail",
        "candidate_sha256": str(asset.get("sha256") or "").lower(),
        "frame_contract_sha256": str(asset.get("frame_contract_sha256") or "").lower(),
    })
    frame["status"] = "NEEDS_USER"
    ledger["updated_at"] = now()
    production_ledger.save_json(path, ledger)
    return True


def record_weak_pass(
    ep: Path,
    *,
    asset: dict,
    review_row: dict,
    profile_sha256: str,
    story_os_version: str,
    content_attempts: int,
    technical_attempts: int,
    failed_checks: list[str],
    issue_codes: list[str],
    reason: str,
    approved_by_policy: str = "attempt_over_3_auto_release",
) -> dict:
    """Persist a SHA-bound low-score acceptance without rewriting critic FAIL evidence."""
    ep = Path(ep)
    data = load(ep)
    rid = str(asset.get("id") or "")
    entry = binding(asset, profile_sha256=profile_sha256, story_os_version=story_os_version)
    prior = (data.get("items") or {}).get(rid)
    if approved_by_policy == "episode14_paid_2of2_soft_visual_quality" and (not isinstance(prior,dict) or prior.get("status") != "FAIL"):
        raise ValueError("EXHAUSTED_WEAK_PASS_REQUIRES_ORIGINAL_FAIL")
    weak = {
        "weak_pass": True,
        "weak_pass_reason": str(reason),
        "failed_checks": sorted({str(x) for x in failed_checks if str(x)}),
        "issue_codes": sorted({str(x) for x in issue_codes if str(x)}),
        "content_attempts": int(content_attempts),
        "technical_attempts": int(technical_attempts),
        "approved_by_policy": approved_by_policy,
    }
    if approved_by_policy == "episode14_paid_2of2_soft_visual_quality":
        weak["prior_independent_fail"] = dict(prior)
    entry.update({
        "status": "WEAK_PASS",
        "reviewed_at": now(),
        "attempt": int(content_attempts),
        "review_row": dict(review_row),
        "provenance": {"policy": approved_by_policy},
        "weak_pass": weak,
    })
    data.setdefault("items", {})[rid] = entry
    data["updated_at"] = now()
    story_json.write_json(ep / REL, data)
    return entry


def restore_ledger_weak_pass(ep: Path, *, asset: dict, weak_pass: dict) -> bool:
    """Accept only the exact current candidate SHA and retain the quality debt explicitly."""
    ep = Path(ep)
    path = ep / LEDGER_REL
    ledger = production_ledger.load_authority(ep, default={}) or {}
    frame_key = f"{int(asset.get('frame') or 0):02d}"
    frame = (ledger.get("frames") or {}).get(frame_key)
    if not isinstance(frame, dict):
        return False
    candidate = frame.get("current_candidate") or {}
    if str(candidate.get("sha256") or "").lower() != str(asset.get("sha256") or "").lower():
        return False
    audit = dict(weak_pass or {})
    audit["weak_pass"] = True
    audit["approved_by_policy"] = str(audit.get("approved_by_policy") or "attempt_over_3_auto_release")
    audit["accepted_at"] = now()
    frame["weak_pass"] = audit
    frame.setdefault("reviews", []).append({
        "at": audit["accepted_at"],
        "decision": "weak_pass",
        "notes": str(audit.get("weak_pass_reason") or "content attempts exceeded speed policy"),
        "candidate_sha256": str(asset.get("sha256") or "").lower(),
        "frame_contract_sha256": str(asset.get("frame_contract_sha256") or "").lower(),
        "approved_by_policy": audit["approved_by_policy"],
    })
    frame["status"] = "WEAK_PASS"
    ledger["updated_at"] = now()
    production_ledger.save_json(path, ledger)
    return True
