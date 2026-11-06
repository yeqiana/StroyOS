#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from story_os_contract import canonical_stages
from story_os_contract import FOUR_ADMISSION_V21_POLICY
from incremental_frame_review import review_required as semantic_frame_review_required, verify_episode as verify_frame_semantic_episode
from final_acceptance import allows as acceptance_allows, visual_asset_for_frame
import identity_continuity  # STORY_OS_P1_1_IDENTITY_CONTINUITY
import character_visual_contract
import character_appearance_anchor
import story_semantic_trace  # STORY_OS_W22_STORY_SEMANTIC_TRACE
import story_dna_trace  # STORY_OS_V3_E003_STORY_DNA_TRACE
import visual_reality_score  # STORY_OS_V3_E005_VISUAL_REALITY_SCORE
import visual_profile_closure as visual_profile_closure  # STORY_OS_PHASE46_VISUAL_PROFILE_CLOSURE
import visual_profile_gate as visual_profile_gate  # STORY_OS_PHASE46_VISUAL_PROFILE_CLOSURE
import asset_boundary_gate
import production_queue_store
import scheduler_core
import frame_review_persistence
import episode_state_persistence
import production_ledger
import production_ledger_persistence

STATES = canonical_stages()
STATE_MIN = {name: idx for idx, name in enumerate(STATES)}
HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
CALIBRATION_ROLES = ("baseline", "worst_condition", "first_major_anomaly")
FOUR_ADMISSION_ROLES = (
    "ordinary_baseline",
    "worst_capture_condition",
    "first_major_anomaly",
    "high_impact_admission",
)
HARD_REVIEW_FIELDS = (
    "viewpoint_physics",
    "capture_profile_match",
    "not_cinematic",
    "album_test",
)
OPTIONAL_REVIEW_FIELDS = (
    "unplanned_recorder_absent",
    "identity_match",
    "key_prop_match",
    "location_match",
    "continuity_match",
    "defects_are_causal",
)
RED_FLAGS = {
    "centered_subject",
    "direct_gaze",
    "perfect_face_light",
    "clean_edges",
    "everything_fully_shown",
    "commercial_sharpness",
    "cinematic_or_promo",
}
HARD_FAILURES = {
    "impossible_viewpoint",
    "unexplained_camera_visible",
    "identity_drift",
    "key_prop_drift",
    "location_structure_drift",
    "sudden_cinematic_shift",
    "critical_text_error",
    "unexplained_third_person",
}


@dataclass
class Finding:
    level: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.code}: {self.message}"


def load_json(path: Path, findings: list[Finding], required: bool = True) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            findings.append(Finding("FAIL", "missing_json", str(path)))
        return None
    except json.JSONDecodeError as exc:
        findings.append(Finding("FAIL", "invalid_json", f"{path}: {exc}"))
        return None
    if not isinstance(data, dict):
        findings.append(Finding("FAIL", "invalid_json_root", f"{path}: top-level must be object"))
        return None
    return data



def load_production_ledger_authority(
    episode_dir: Path,
    findings: list[Finding],
    *,
    required: bool,
    invalid_code: str = "invalid_json",
) -> dict | None:
    """Read the complete Production Ledger authority without legacy fallback."""
    episode_dir = Path(episode_dir).resolve()
    try:
        data = production_ledger.load_authority(episode_dir, default=None)
    except production_ledger_persistence.ProductionLedgerAuthorityIncomplete:
        raise
    except Exception as exc:
        findings.append(
            Finding("FAIL", invalid_code, f"production ledger invalid: {exc}")
        )
        return None
    if data is None:
        if required:
            findings.append(
                Finding("FAIL", "missing_json", str(episode_dir / "meta/production-ledger.json"))
            )
        return None
    if not isinstance(data, dict):
        findings.append(
            Finding("FAIL", "invalid_json_root", "production ledger top-level must be object")
        )
        return None
    return data


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def repo_relative_path(repo_root: Path, raw: object, findings: list[Finding], where: str) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        findings.append(Finding("FAIL", "required_path", f"{where} must be a repository-relative path"))
        return None
    value = raw.strip()
    if "\\" in value or re.match(r"^[A-Za-z]:", value) or Path(value).is_absolute():
        findings.append(Finding("FAIL", "non_portable_path", f"{where}: {value}"))
        return None
    root = repo_root.resolve()
    path = (root / value).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        findings.append(Finding("FAIL", "path_outside_repo", f"{where}: {value}"))
        return None
    return path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check_hashed_asset(
    repo_root: Path,
    item: dict,
    findings: list[Finding],
    where: str,
    *,
    metadata_only: bool,
) -> None:
    path = repo_relative_path(repo_root, item.get("path") or item.get("asset_path"), findings, f"{where}.path")
    expected = str(item.get("sha256") or "")
    if not HEX64_RE.match(expected):
        findings.append(Finding("FAIL", "invalid_sha256", f"{where}.sha256 must be 64 hex chars"))
    if path is None or metadata_only:
        return
    if not path.is_file():
        findings.append(Finding("FAIL", "missing_asset", f"{where}: {path}"))
        return
    actual = sha256_file(path)
    if HEX64_RE.match(expected) and actual.lower() != expected.lower():
        findings.append(Finding("FAIL", "asset_hash_drift", f"{where}: expected={expected}, actual={actual}"))


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_authenticity_card(gates: dict, manifest: dict, findings: list[Finding]) -> None:
    visual = gates.get("visual") if isinstance(gates.get("visual"), dict) else {}
    card = visual.get("authenticity_card")
    if not isinstance(card, dict):
        findings.append(Finding("FAIL", "authenticity_card", "visual.authenticity_card must be object"))
        return
    for key in ("story_era", "location", "photographer", "shooting_reason"):
        if not nonempty(card.get(key)):
            findings.append(Finding("FAIL", "authenticity_field", f"visual.authenticity_card.{key} is required"))
    primary = card.get("primary_capture")
    if not isinstance(primary, dict) or not nonempty(primary.get("id")) or not nonempty(primary.get("device")):
        findings.append(Finding("FAIL", "primary_capture", "primary_capture requires non-empty id + device"))
    secondary = card.get("secondary_captures")
    if not isinstance(secondary, list):
        findings.append(Finding("FAIL", "secondary_captures", "secondary_captures must be array"))
    elif len(secondary) > 2:
        findings.append(Finding("FAIL", "secondary_capture_limit", "辅助采集设备最多 2 种"))
    elif secondary and not nonempty(card.get("secondary_source_explanation")):
        findings.append(Finding("FAIL", "secondary_capture_reason", "存在辅助采集源时必须解释剧情来源"))
    ratio = ((manifest.get("episode") or {}).get("aspect_ratio"))
    if card.get("aspect_ratio") != ratio:
        findings.append(Finding("FAIL", "authenticity_ratio", f"authenticity_card.aspect_ratio must equal manifest aspect_ratio={ratio!r}"))
    states = card.get("capture_states")
    if not isinstance(states, dict):
        findings.append(Finding("FAIL", "capture_states", "capture_states must be object"))
    else:
        for key in ("stable", "restricted", "lost_control"):
            if not nonempty(states.get(key)):
                findings.append(Finding("FAIL", "capture_state", f"capture_states.{key} is required"))
    rules = card.get("camera_rules")
    if not isinstance(rules, dict):
        findings.append(Finding("FAIL", "camera_rules", "camera_rules must be object"))
    else:
        if rules.get("current_device_may_be_fully_visible") is True and not nonempty(rules.get("current_device_visibility_explanation")):
            findings.append(Finding("FAIL", "camera_visibility", "当前第一视角设备完整入镜必须有物理解释"))
        if rules.get("photographer_may_be_fully_visible") is True and not nonempty(rules.get("photographer_visibility_explanation")):
            findings.append(Finding("FAIL", "photographer_visibility", "拍摄者完整入镜必须有镜面/固定机位/接拍等解释"))


def frame_total(manifest: dict) -> int | None:
    value = ((manifest.get("release") or {}).get("body_frame_count"))
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def check_calibration(repo_root: Path, gates: dict, manifest: dict, findings: list[Finding], *, metadata_only: bool) -> None:
    visual = gates.get("visual") if isinstance(gates.get("visual"), dict) else {}
    calibration = visual.get("calibration")
    if not isinstance(calibration, dict):
        findings.append(Finding("FAIL", "calibration", "visual.calibration must be object"))
        return
    if calibration.get("policy") == FOUR_ADMISSION_V21_POLICY:
        check_four_admission(repo_root, visual, manifest, findings, metadata_only=metadata_only)
        return
    total = frame_total(manifest)
    admissions = visual.get("admission_frames") if isinstance(visual.get("admission_frames"), list) else []
    seen: list[int] = []
    for role in CALIBRATION_ROLES:
        item = calibration.get(role)
        where = f"visual.calibration.{role}"
        if not isinstance(item, dict):
            findings.append(Finding("FAIL", "calibration_role", f"{where} must be object"))
            continue
        frame = item.get("frame")
        if total is None or isinstance(frame, bool) or not isinstance(frame, int) or not 1 <= frame <= total:
            findings.append(Finding("FAIL", "calibration_frame", f"{where}.frame must be within body frame range"))
        else:
            seen.append(frame)
            if frame not in admissions:
                findings.append(Finding("FAIL", "calibration_not_admission", f"frame {frame:02d} must be one of four visual admission frames"))
        if item.get("decision") != "passed":
            findings.append(Finding("FAIL", "calibration_not_passed", f"{where}.decision must be 'passed'"))
        check_hashed_asset(repo_root, item, findings, where, metadata_only=metadata_only)
    if len(seen) == 3 and len(set(seen)) != 3:
        findings.append(Finding("FAIL", "calibration_duplicate", "三张真实性校准必须是三个不同图号"))
    sheet = visual.get("calibration_contact_sheet")
    if not isinstance(sheet, dict):
        findings.append(Finding("FAIL", "calibration_sheet", "visual.calibration_contact_sheet must be object"))
    else:
        check_hashed_asset(repo_root, sheet, findings, "visual.calibration_contact_sheet", metadata_only=metadata_only)


def check_four_admission(repo_root: Path, visual: dict, manifest: dict, findings: list[Finding], *, metadata_only: bool) -> None:
    """Validate the current four-frame Visual Lock; legacy three-frame calibration is separate."""
    calibration = visual.get("calibration") or {}
    items = calibration.get("items")
    if not isinstance(items, list) or len(items) != len(FOUR_ADMISSION_ROLES):
        findings.append(Finding("FAIL", "visual_lock_items", "four_admission_v21 requires exactly four calibration items"))
        return
    total = frame_total(manifest)
    by_role: dict[str, dict] = {}
    seen_frames: set[int] = set()
    for index, item in enumerate(items):
        where = f"visual.calibration.items[{index}]"
        if not isinstance(item, dict):
            findings.append(Finding("FAIL", "visual_lock_item", f"{where} must be object"))
            continue
        role = str(item.get("role") or "")
        if role not in FOUR_ADMISSION_ROLES or role in by_role:
            findings.append(Finding("FAIL", "visual_lock_role", f"{where}.role must be one distinct current Visual Lock role"))
            continue
        by_role[role] = item
        frame = item.get("frame")
        if total is None or isinstance(frame, bool) or not isinstance(frame, int) or not 1 <= frame <= total:
            findings.append(Finding("FAIL", "visual_lock_frame", f"{where}.frame must be within body frame range"))
        elif frame in seen_frames:
            findings.append(Finding("FAIL", "visual_lock_duplicate", "four Visual Lock frames must be distinct"))
        else:
            seen_frames.add(frame)
        if item.get("decision") != "passed":
            findings.append(Finding("FAIL", "visual_lock_not_passed", f"{where}.decision must be passed"))
        if not nonempty(item.get("frame_contract_sha256")):
            findings.append(Finding("FAIL", "visual_lock_contract", f"{where}.frame_contract_sha256 required"))
        check_hashed_asset(repo_root, item, findings, where, metadata_only=metadata_only)
    missing = set(FOUR_ADMISSION_ROLES) - set(by_role)
    if missing:
        findings.append(Finding("FAIL", "visual_lock_roles", "missing roles: " + ", ".join(sorted(missing))))
    admissions = visual.get("admission_frames")
    if isinstance(admissions, list) and admissions and set(admissions) != seen_frames:
        findings.append(Finding("FAIL", "visual_lock_admission_frames", "admission_frames must equal the four locked Visual Lock frames"))


def check_references(repo_root: Path, gates: dict, findings: list[Finding], *, metadata_only: bool, episode_dir: Path | None = None) -> None:
    visual = gates.get("visual") if isinstance(gates.get("visual"), dict) else {}
    refs = visual.get("references")
    if not isinstance(refs, dict):
        findings.append(Finding("FAIL", "reference_registry", "visual.references must be object"))
        return
    items = refs.get("items")
    if not isinstance(items, list):
        findings.append(Finding("FAIL", "reference_items", "visual.references.items must be array"))
        return
    ids: set[str] = set()
    passed_anchors: set[str] = set()
    for idx, item in enumerate(items):
        where = f"visual.references.items[{idx}]"
        if not isinstance(item, dict):
            findings.append(Finding("FAIL", "reference_item", f"{where} must be object"))
            continue
        rid = item.get("id")
        if not nonempty(rid) or rid in ids:
            findings.append(Finding("FAIL", "reference_id", f"{where}.id must be unique non-empty string"))
        else:
            ids.add(rid)
        if item.get("kind") not in {"identity", "prop", "location", "capture_style"}:
            findings.append(Finding("FAIL", "reference_kind", f"{where}.kind invalid"))
        if not nonempty(item.get("anchor")):
            findings.append(Finding("FAIL", "reference_anchor", f"{where}.anchor required"))
        if item.get("decision") != "passed":
            findings.append(Finding("FAIL", "reference_not_passed", f"{where}.decision must be passed"))
        else:
            passed_anchors.add(str(item.get("anchor")))
        check_hashed_asset(repo_root, item, findings, where, metadata_only=metadata_only)
    if refs.get("required") is True:
        required = refs.get("required_anchors")
        if not isinstance(required, list) or not required:
            findings.append(Finding("FAIL", "required_reference_anchors", "references.required=true requires required_anchors"))
        else:
            for anchor in required:
                if anchor not in passed_anchors:
                    findings.append(Finding("FAIL", "missing_reference_anchor", f"required reference anchor not passed: {anchor}"))

    # W-17: declaration-only validation is insufficient. Runtime queue evidence must
    # carry the same anchor contract when available.
    queue = None
    if episode_dir is not None:
        try:
            queue = scheduler_core.load_queue(Path(episode_dir))
        except Exception:
            queue = None
    else:
        queue_path = Path(gates.get("production_queue") or production_queue_store.REL)
        if not queue_path.is_absolute():
            queue_path = repo_root / queue_path
        if queue_path.exists():
            try:
                queue = json.loads(queue_path.read_text(encoding="utf-8-sig"))
            except Exception:
                queue = None
    if isinstance(queue, dict):
        for item in queue.get("items") or []:
            contract = item.get("reference_execution_contract") or {}
            roles = set(str(x) for x in contract.get("selected_roles") or [])
            for anchor in refs.get("required_anchors") or []:
                if str(anchor) not in roles:
                    findings.append(Finding("FAIL", "missing_execution_reference_anchor", f"runtime reference missing required anchor: {anchor}"))


def accepted_frame_attempt(frame: dict) -> dict | None:
    """The generation attempt whose pixels the frame currently accepts."""
    attempts = [a for a in (frame.get("attempts") or []) if isinstance(a, dict)]
    approved = frame.get("approved_asset") if isinstance(frame.get("approved_asset"), dict) else {}
    candidate = frame.get("current_candidate") if isinstance(frame.get("current_candidate"), dict) else {}
    for sha in (approved.get("source_sha256"), candidate.get("sha256")):
        token = str(sha or "")
        if not token:
            continue
        for attempt in reversed(attempts):
            if str((attempt.get("candidate") or {}).get("sha256") or "") == token:
                return attempt
    attempt_id = str(candidate.get("attempt_id") or "")
    if attempt_id:
        for attempt in reversed(attempts):
            if str(attempt.get("attempt_id") or "") == attempt_id:
                return attempt
    for attempt in reversed(attempts):
        if attempt.get("result") == "success":
            return attempt
    return None


def check_reference_execution_evidence(repo_root: Path, episode_dir: Path, gates: dict, findings: list[Finding], *, metadata_only: bool) -> None:
    """W-21: prove the declared identity anchor actually reached the provider.

    A reference registry only proves intent. This check reads the production ledger
    execution evidence and rejects a frame whose accepted attempt declared a
    reference anchor without proof that the same file (same SHA-256) was sent to the
    image provider and returned a receipt.

    Backward compatibility: only episodes whose story-gates declare
    references.required=true are in scope, and only attempts recorded after the
    ledger became reference-execution aware. Historical episodes keep passing.
    """
    visual = gates.get("visual") if isinstance(gates.get("visual"), dict) else {}
    registry = visual.get("references")
    if not isinstance(registry, dict) or registry.get("required") is not True:
        return
    if metadata_only:
        return
    ledger = load_production_ledger_authority(
        episode_dir,
        findings,
        required=False,
        invalid_code="reference_execution_ledger",
    )
    if not isinstance(ledger, dict):
        return
    marker = ledger.get("reference_execution_evidence")
    if not isinstance(marker, dict) or marker.get("schema_version") != 1:
        # Ledger produced before reference execution evidence existed: legacy scope.
        return
    enforced_from = str(marker.get("enforced_from") or "")
    authority: dict[str, str] = {}
    for item in registry.get("items") or []:
        if isinstance(item, dict) and item.get("path"):
            authority[str(item["path"])] = str(item.get("sha256") or "").lower()
    for key, frame in (ledger.get("frames") or {}).items():
        if not isinstance(frame, dict):
            continue
        attempt = accepted_frame_attempt(frame)
        if not isinstance(attempt, dict):
            continue
        declared = [row for row in ((attempt.get("request") or {}).get("references") or [])
                    if isinstance(row, dict) and row.get("path")]
        if not declared:
            continue
        started_at = str(attempt.get("started_at") or "")
        if enforced_from and started_at and started_at < enforced_from:
            continue
        evidence = attempt.get("reference_execution")
        if not isinstance(evidence, dict):
            findings.append(Finding("FAIL", "missing_reference_execution_receipt",
                                    f"frame {key}: reference-declared generation attempt has no reference_execution record"))
            continue
        if evidence.get("required") is not True:
            findings.append(Finding("FAIL", "reference_execution_not_required",
                                    f"frame {key}: reference_execution.required must be true"))
        if evidence.get("passed_to_provider") is not True:
            findings.append(Finding("FAIL", "reference_execution_not_passed",
                                    f"frame {key}: reference was not recorded as passed to the provider"))
        if not nonempty(evidence.get("provider_receipt_id")):
            findings.append(Finding("FAIL", "reference_execution_receipt_missing",
                                    f"frame {key}: reference_execution.provider_receipt_id required"))
        if evidence.get("verified") is not True:
            findings.append(Finding("FAIL", "reference_execution_not_verified",
                                    f"frame {key}: reference execution evidence is not verified"))
        executed: dict[str, str] = {}
        for row in evidence.get("selected_references") or []:
            if isinstance(row, dict) and row.get("path"):
                executed[str(row["path"])] = str(row.get("sha256") or "").lower()
        for row in declared:
            path = str(row["path"])
            expected = str(row.get("sha256") or "").lower()
            if path not in executed:
                findings.append(Finding("FAIL", "reference_execution_missing_anchor",
                                        f"frame {key}: declared reference {path} absent from provider execution evidence"))
                continue
            actual = executed[path]
            if actual != expected:
                findings.append(Finding("FAIL", "reference_execution_hash_drift",
                                        f"frame {key}: declared sha {expected[:12]} != executed sha {actual[:12]} for {path}"))
            elif authority.get(path) and authority[path] != actual:
                findings.append(Finding("FAIL", "reference_execution_hash_drift",
                                        f"frame {key}: current authority sha {authority[path][:12]} != executed sha {actual[:12]} for {path}"))


def check_identity_continuity_evidence(repo_root: Path, episode_dir: Path, gates: dict, findings: list[Finding], *, metadata_only: bool) -> None:
    """P1-1: prove the declared identity anchor is preserved in the generated pixels.

    W-21 proved the reference file reached the provider. This check consumes the
    frame review identity_evidence to prove the frame was judged against the same
    anchor, with provenance. It never accepts "character-contract.json exists" as
    evidence; config presence alone does not pass.

    Backward compatibility mirrors W-21: only episodes whose story-gates declare
    references.required=true are in scope, and only attempts recorded after the
    ledger became identity-evidence aware. Historical episodes keep passing.
    """
    if metadata_only:
        return
    if not identity_continuity.identity_contract(episode_dir).get("required"):
        return
    ledger = load_production_ledger_authority(
        episode_dir,
        findings,
        required=False,
        invalid_code="identity_continuity_ledger",
    )
    if not isinstance(ledger, dict):
        return
    marker = ledger.get("identity_continuity_evidence")
    if not isinstance(marker, dict) or marker.get("schema_version") != 1:
        # Ledger produced before identity continuity evidence existed: legacy scope.
        return
    enforced_from = str(marker.get("enforced_from") or "")
    authority = identity_continuity.anchor_authority(episode_dir)
    frames = ledger.get("frames") if isinstance(ledger.get("frames"), dict) else {}
    for key in sorted(frames):
        frame = frames.get(key)
        if not isinstance(frame, dict):
            continue
        attempt = accepted_frame_attempt(frame)
        if not isinstance(attempt, dict):
            continue
        requirements = identity_continuity.attempt_identity_requirements(attempt, episode_dir)
        if not requirements:
            continue
        started_at = str(attempt.get("started_at") or "")
        if enforced_from and started_at and started_at < enforced_from:
            continue
        review = frame_review_persistence.load(episode_dir, int(key))
        evidence = identity_continuity.evidence_from_review(review)
        for code, message in identity_continuity.validate_frame(evidence, requirements, authority):
            findings.append(Finding("FAIL", code, f"frame {key}: {message}"))

def check_story_semantic_trace(repo_root: Path, episode_dir: Path, gates: dict, findings: list[Finding], *, metadata_only: bool) -> None:
    """W-22: prove each frame exists because of its declared story role.

    The Frame Contract publishes story_semantic_requirements per frame. This check
    consumes the frame review story_semantic_trace to prove the frame was judged
    against that role and the same Story Lock, with provenance. It never accepts
    "story-gates.story has a role map" as evidence; config presence alone does not
    pass.

    Backward compatibility mirrors W-21/P1-1: only episodes whose ledger was marked
    story-semantic-trace aware are in scope, and only attempts recorded after the
    marker. Historical episodes keep passing.

    W-23: an Episode that carries a valid meta/final-acceptance.json and lists a
    frame in known_defect_frames has already had that defect accepted directly by
    the user. Those frames are reported as WARN so the acceptance record, and not
    a silent edit of the evidence, is what lets production advance.
    """
    if metadata_only:
        return
    if not story_semantic_trace.required(episode_dir):
        return
    ledger = load_production_ledger_authority(
        episode_dir,
        findings,
        required=False,
        invalid_code="story_semantic_trace_ledger",
    )
    if not isinstance(ledger, dict):
        return
    marker = ledger.get("story_semantic_trace_evidence")
    if not isinstance(marker, dict) or marker.get("schema_version") != 1:
        # Ledger produced before the semantic trace existed: legacy scope.
        return
    enforced_from = str(marker.get("enforced_from") or "")
    frames = ledger.get("frames") if isinstance(ledger.get("frames"), dict) else {}
    full_sha_bound_user_authority = None
    for key in sorted(frames):
        frame = frames.get(key)
        if not isinstance(frame, dict):
            continue
        attempt = accepted_frame_attempt(frame)
        if not isinstance(attempt, dict):
            continue
        requirement = story_semantic_trace.frame_requirements(episode_dir, int(key))
        if not isinstance(requirement, dict) or requirement.get("required") is not True:
            continue
        started_at = str(attempt.get("started_at") or "")
        if enforced_from and started_at and started_at < enforced_from:
            continue
        review = frame_review_persistence.load(episode_dir, int(key))
        trace = story_semantic_trace.trace_from_review(review)
        expected_contract = story_semantic_trace.attempt_contract_sha(attempt)
        for code, message in story_semantic_trace.validate_frame(trace, requirement, expected_contract):
            if acceptance_allows(episode_dir, "story_semantic_trace", key):
                findings.append(Finding(
                    "WARN", "story_semantic_trace_accepted",
                    f"frame {key}: {code}: {message} accepted as known defect "
                    "(meta/final-acceptance.json)"))
            elif code == "story_semantic_trace_missing" and acceptance_allows(episode_dir, "story_semantic_trace"):
                # The user accepted all final image bytes by SHA; a missing
                # historical text-role trace remains a WARN, not a model PASS.
                # The separate authority verifier checks every current frame,
                # real successful attempt, and previously unaccepted defect.
                if full_sha_bound_user_authority is None:
                    import verified_review_authority
                    full_sha_bound_user_authority = verified_review_authority.verify_episode_review_authority(
                        episode_dir, metadata_only=False)
                if (full_sha_bound_user_authority.get("status") == "USER_ACCEPTED"
                        and key in full_sha_bound_user_authority.get("frames", [])):
                    findings.append(Finding(
                        "WARN", "story_semantic_trace_user_final_asset",
                        f"frame {key}: {message}; direct user accepted all final pixels "
                        "by SHA (not a model story-trace PASS)"))
                else:
                    findings.append(Finding("FAIL", code, f"frame {key}: {message}"))
            else:
                findings.append(Finding("FAIL", code, f"frame {key}: {message}"))


def review_path(repo_root: Path, episode_dir: Path, gates: dict, key: str) -> Path:
    evidence = gates.get("production_evidence") if isinstance(gates.get("production_evidence"), dict) else {}
    raw = evidence.get("frame_review_dir", "meta/frame-reviews")
    base = Path(raw)
    if base.is_absolute():
        return base / f"{key}.json"
    return episode_dir / base / f"{key}.json"


def check_frame_review(episode_dir: Path, key: str, findings: list[Finding]) -> None:
    data = frame_review_persistence.load(episode_dir, int(key))
    if data is None:
        findings.append(Finding("FAIL", "frame_review_missing", f"frame review missing: {key}"))
        return
    if data.get("schema_version") != 1:
        findings.append(Finding("FAIL", "frame_review_schema", f"frame {key}: schema_version must be 1"))
    frame = str(data.get("frame") or "")
    if frame.zfill(2) != key:
        findings.append(Finding("FAIL", "frame_review_number", f"frame review frame must be {key}"))
    for field in HARD_REVIEW_FIELDS:
        if data.get(field) != "pass":
            findings.append(Finding("FAIL", "frame_review_hard_fail", f"{key}.{field} must be pass"))
    for field in OPTIONAL_REVIEW_FIELDS:
        if data.get(field) not in {"pass", "fail", "na"}:
            findings.append(Finding("FAIL", "frame_review_field", f"{key}.{field} must be pass/fail/na"))
        elif data.get(field) == "fail":
            findings.append(Finding("FAIL", "frame_review_fail", f"{key}.{field}=fail"))
    hard_failures = data.get("hard_failures_detected")
    if not isinstance(hard_failures, list) or any(x not in HARD_FAILURES for x in hard_failures):
        findings.append(Finding("FAIL", "hard_failures", f"{key}.hard_failures_detected contains invalid values"))
    elif hard_failures:
        findings.append(Finding("FAIL", "hard_failure_detected", f"{key}: hard failures detected: {hard_failures}"))
    detected = data.get("red_flags_detected")
    exempted = data.get("red_flags_exempted")
    if not isinstance(detected, list) or any(x not in RED_FLAGS for x in detected):
        findings.append(Finding("FAIL", "red_flags", f"{key}.red_flags_detected contains invalid values"))
        detected = []
    if not isinstance(exempted, list) or any(x not in RED_FLAGS for x in exempted):
        findings.append(Finding("FAIL", "red_flags", f"{key}.red_flags_exempted contains invalid values"))
        exempted = []
    if not set(exempted).issubset(set(detected)):
        findings.append(Finding("FAIL", "red_flag_exemption", f"{key}: exemptions must be a subset of detected flags"))
    if exempted:
        exc = data.get("intentional_exception")
        if not isinstance(exc, dict) or exc.get("enabled") is not True or not nonempty(exc.get("reason")):
            findings.append(Finding("FAIL", "red_flag_exception_reason", f"{key}: red-flag exemption requires pre-registered reason"))
    effective = len(set(detected) - set(exempted))
    if effective >= 3:
        findings.append(Finding("FAIL", "red_flag_threshold", f"{key}: effective photography red flags={effective} >= 3"))
    if data.get("decision") not in {"pass", "warning"}:
        findings.append(Finding("FAIL", "frame_review_decision", f"{key}.decision must be pass or warning before production gate"))


def check_production(repo_root: Path, episode_dir: Path, gates: dict, manifest: dict, findings: list[Finding], *, metadata_only: bool) -> None:
    semantic_required = semantic_frame_review_required(episode_dir)
    from production_ledger import ACCEPTED_LEDGER_STATES, content_repair_limit
    ledger = load_production_ledger_authority(
        episode_dir,
        findings,
        required=True,
    )
    if ledger is None:
        return
    total = frame_total(manifest)
    frames = ledger.get("frames")
    if not isinstance(frames, dict) or total is None:
        findings.append(Finding("FAIL", "production_frames", "production ledger frames/body count invalid"))
        return
    if len(frames) != total:
        findings.append(Finding("FAIL", "production_frame_count", f"ledger frames={len(frames)}, manifest body_frame_count={total}"))
    for number in range(1, total + 1):
        key = f"{number:02d}"
        frame = frames.get(key)
        if not isinstance(frame, dict):
            findings.append(Finding("FAIL", "missing_production_frame", f"ledger missing frame {key}"))
            continue
        accepted_visual = None
        if acceptance_allows(episode_dir, "production_gate", key):
            try:
                accepted_visual = visual_asset_for_frame(episode_dir, key)
            except (OSError, RuntimeError, ValueError) as exc:
                findings.append(Finding("FAIL", "accepted_visual_asset", f"{key}: {exc}"))
        user_accepts_status = isinstance(accepted_visual, dict)
        if frame.get("status") not in ACCEPTED_LEDGER_STATES:
            if user_accepts_status:
                findings.append(Finding("WARN", "production_status_user_accepted", f"{key}: historical status={frame.get('status')!r}; current direct-user final publish asset accepted by SHA"))
            else:
                findings.append(Finding("FAIL", "production_status", f"{key}: status={frame.get('status')!r}, expected PASSED/WEAK_PASS/LOCKED"))
        if frame.get("content_repairs_used", 0) > content_repair_limit(ledger):
            findings.append(Finding("FAIL", "repair_limit", f"{key}: content_repairs_used exceeds frozen policy"))
        approved = accepted_visual if user_accepts_status else frame.get("approved_asset")
        if not isinstance(approved, dict):
            findings.append(Finding("FAIL", "approved_asset", f"{key}: approved_asset required"))
        else:
            where = "production.frames." + key + (".accepted_visual" if user_accepts_status else ".approved_asset")
            check_hashed_asset(repo_root, approved, findings, where, metadata_only=metadata_only)
        if frame.get("status") == "LOCKED" and not user_accepts_status:
            lock = frame.get("lock")
            if not isinstance(lock, dict) or not isinstance(approved, dict) or lock.get("sha256") != approved.get("sha256"):
                findings.append(Finding("FAIL", "lock_hash", f"{key}: lock hash must equal approved asset hash"))
        if not semantic_required and not metadata_only:
            check_frame_review(episode_dir, key, findings)

    if semantic_required:
        errors = verify_frame_semantic_episode(episode_dir, metadata_only=metadata_only, write_audit=False)
        if errors:
            if acceptance_allows(episode_dir, "frame_semantic"):
                findings.append(Finding("WARN", "frame_semantic_accepted", "direct user final-decision acceptance recorded; semantic FAIL accepted as known defects (meta/final-acceptance.json)"))
            else:
                for error in errors:
                    findings.append(Finding("FAIL", "frame_semantic_review", error))
        # A LOCKED ledger row and an approved file are projections. Stage
        # advancement must also prove the matching completed Review receipt and
        # terminal Review Queue authority for every generated accepted frame.
        try:
            import verified_review_authority
            authority = verified_review_authority.verify_episode_review_authority(
                episode_dir, metadata_only=metadata_only)
            if authority.get("status") == "BLOCKED":
                for error in authority.get("errors") or []:
                    findings.append(Finding("FAIL", "verified_review_authority", str(error)))
        except Exception as exc:
            findings.append(Finding(
                "FAIL", "verified_review_authority",
                f"review authority verifier unavailable: {type(exc).__name__}: {exc}"))


def check_visual_profile_for_production(repo_root: Path, episode_dir: Path, findings: list[Finding], *, metadata_only: bool) -> None:
    """Phase 4.6-A: consume the canonical Visual Profile production gate.

    Phase 4.3 already owns the question "may this Episode be produced with the profile
    it declared?" as visual_profile_gate. This check only carries that answer into
    machine_gate: it never reads the registry, never re-implements the lifecycle state
    machine, never re-checks selection evidence, and never confirms or freezes anything
    itself.

    Scope and backward compatibility: an Episode with no governed Visual Lock is
    reported as legacy_unmanaged by the gate and adds no finding, so a historical
    Episode cannot be retroactively failed. A governed Episode is asked for LOCKED
    (production stage) and, once a formal production asset has been committed, for
    FROZEN (release stage) through the same canonical gate. Metadata-only mode skips
    the check entirely, like the other execution-evidence checks.
    """
    if metadata_only:
        return
    errors = visual_profile_gate.verify_visual_profile_for_production(
        episode_dir, stage=visual_profile_gate.STAGE_PRODUCTION)
    for error in errors:
        code, _sep, detail = str(error).partition(": ")
        findings.append(Finding("FAIL", code.lower(), f"visual profile: {detail or code}"))

    if not visual_profile_closure.required_for_production(episode_dir):
        # Nothing is owed yet: either the Episode is unmanaged, or no formal
        # production asset has been committed, so FROZEN is not required.
        return
    result = visual_profile_gate.validate_visual_profile_for_production(
        episode=episode_dir, stage="release")
    for error in result.get("errors") or []:
        if error.get("code") != visual_profile_gate.ERROR_NOT_FROZEN:
            continue
        findings.append(Finding(
            "FAIL", "visual_profile_not_frozen",
            f"visual profile: committed production assets exist, {error.get('detail')}"))


def validate(episode_dir: Path, target: str, *, metadata_only: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    gates = load_json(episode_dir / "meta/story-gates.json", findings)
    manifest = load_json(episode_dir / "meta/release-manifest.json", findings)
    if gates is None or manifest is None:
        return findings
    contract = gates.get("machine_contract")
    if not isinstance(contract, dict) or contract.get("strict") is not True:
        findings.append(Finding("WARN", "machine_gate_legacy", "machine_contract.strict is not enabled; legacy compatibility mode"))
        return findings
    if contract.get("version") != 1:
        findings.append(Finding("FAIL", "machine_contract", "machine_contract.version must be 1"))
        return findings
    if target not in STATE_MIN:
        findings.append(Finding("FAIL", "target", f"unknown target state: {target}"))
        return findings
    idx = STATE_MIN[target]
    repo_root = repo_root_from_script()
    if idx >= STATE_MIN["STORYBOARD_LOCKED"] and character_appearance_anchor.required(episode_dir):
        for error in character_visual_contract.validate(episode_dir, require_locked=True):
            findings.append(Finding("FAIL", "character_visual_contract", error))
    if idx >= STATE_MIN["VISUAL_CALIBRATED"]:
        check_authenticity_card(gates, manifest, findings)
        check_calibration(repo_root, gates, manifest, findings, metadata_only=metadata_only)
        check_references(repo_root, gates, findings, metadata_only=metadata_only, episode_dir=episode_dir)
    if idx >= STATE_MIN["PRODUCTION_PASSED"]:
        for error in asset_boundary_gate.verify_episode(episode_dir):
            findings.append(Finding("FAIL", "asset_boundary", error))
        check_reference_execution_evidence(repo_root, episode_dir, gates, findings, metadata_only=metadata_only)
        check_identity_continuity_evidence(repo_root, episode_dir, gates, findings, metadata_only=metadata_only)
        check_story_semantic_trace(repo_root, episode_dir, gates, findings, metadata_only=metadata_only)
        check_visual_profile_for_production(repo_root, episode_dir, findings, metadata_only=metadata_only)
        check_production(repo_root, episode_dir, gates, manifest, findings, metadata_only=metadata_only)
    if idx >= STATE_MIN["PUBLISH_READY"] and not metadata_only:
        # New evidence gates activate only once the production has opted in by
        # creating its evidence file. Historical episodes are audited by the
        # dedicated regression command; we never create a compatibility PASS.
        if (episode_dir / story_dna_trace.REL).is_file():
            for error in story_dna_trace.verify(episode_dir):
                findings.append(Finding("FAIL", "story_dna_trace", error))
        if (episode_dir / visual_reality_score.REL).is_file():
            for error in visual_reality_score.verify(episode_dir):
                findings.append(Finding("FAIL", "visual_reality_score", error))
    return findings


def current_state(episode_dir: Path) -> str:
    data = episode_state_persistence.load(episode_dir) or {}
    state = data.get("current_state")
    if state not in STATE_MIN:
        raise SystemExit(f"invalid current_state in {episode_dir}: {state!r}")
    return state


def discover_episode_dirs(repo_root: Path) -> list[Path]:
    import episode_discovery
    return episode_discovery.iter_episode_roots(repo_root / "episodes")


def print_findings(ep: Path, target: str, findings: list[Finding]) -> bool:
    failed = any(x.level == "FAIL" for x in findings)
    print(f"=== {'FAIL' if failed else 'PASS'} MACHINE GATE {target} :: {ep} ===")
    if findings:
        for item in findings:
            print(item)
    else:
        print("[PASS] clean")
    return not failed


def main() -> int:
    p = argparse.ArgumentParser(description="DALI CAT Story OS V1.5 machine-enforced evidence gate")
    p.add_argument("episode_dir", nargs="?")
    p.add_argument("--all", action="store_true", help="validate all tracked episodes at their current state")
    p.add_argument("--target", choices=STATES)
    p.add_argument("--metadata-only", action="store_true")
    args = p.parse_args()
    if bool(args.episode_dir) == bool(args.all):
        p.error("provide exactly one episode_dir or --all")
    if args.all and args.target:
        p.error("--target is only valid for one episode")
    ok = True
    if args.all:
        episodes = discover_episode_dirs(repo_root_from_script())
        for ep in episodes:
            target = current_state(ep)
            ok = print_findings(ep, target, validate(ep, target, metadata_only=args.metadata_only)) and ok
    else:
        ep = Path(args.episode_dir).resolve()
        target = args.target or current_state(ep)
        ok = print_findings(ep, target, validate(ep, target, metadata_only=args.metadata_only))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
