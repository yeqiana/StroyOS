#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import codex_critic_runner
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from story_os_contract import story_os_version
import propagation_core_gate  # STORY_OS_V2_5_PROPAGATION_CORE
import runtime_router
import runtime_provenance
import product_review_adapter
import story_json
import runtime_timeout_policy
import episode_state_persistence
import review_record_persistence
import review_policy_binding
import story_review_rubric_migration
import story_review_a10_source_revision
import runtime_request

ROOT = Path(__file__).resolve().parents[2]
REVIEW_REL = Path("meta/story-semantic-review.json")
REVIEW_TYPE = "STORY_SEMANTIC"
EXPORT_REL = Path("meta/runtime/review-exports/story-semantic.json")
CANDIDATE_REL = Path("meta/.story-semantic-review.candidate.json")
STORYBOARD_EXCEPTION_REL = Path("meta/runtime/storyboard-review-exceptions.json")
TARGET_CONTRACT = (2, 0, 3, 2)

CONTRACT_FIELDS = [
    "protagonist",
    "presence_reason",
    "personal_stake",
    "core_anomaly",
    "rule",
    "trigger",
    "direct_consequence",
    "midpoint_reframe",
    "climax_choice",
]
BLIND_FIELDS = [
    "protagonist_and_reason",
    "core_anomaly_rule",
    "worsening_choice",
    "climax_resolution",
    "ending_reinterpretation",
]
HARD_CHECKS = [
    "clarity",
    "causal_chain",
    "mechanism_consistency",
    "motivation_stake",
    "trigger_consequence",
    "midpoint_reframe",
    "climax_payoff",
    "ending_payoff",
    "storyboard_information_gain",
    "delete_frame_test",
]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict:
    return story_json.read_json(path)


def write_json(path: Path, data: dict) -> None:
    story_json.write_json(path, data)



def load_review(ep: Path) -> dict | None:
    ep = Path(ep).resolve()
    return review_record_persistence.load_latest(
        ep, REVIEW_TYPE, legacy_path=ep / REVIEW_REL
    )


def review_authority_sha256(ep: Path) -> str | None:
    return review_record_persistence.authority_sha256(
        Path(ep).resolve(), REVIEW_TYPE, legacy_path=Path(ep).resolve() / REVIEW_REL
    )


def save_review(
    ep: Path,
    data: dict,
    *,
    decision: str,
    source_sha256: str | None = None,
) -> dict:
    data = review_policy_binding.attach_bound_policy_sha(Path(ep).resolve(), data)
    provenance = data.get("critic_provenance") or {}
    return review_record_persistence.save(
        Path(ep).resolve(),
        REVIEW_TYPE,
        REVIEW_REL,
        data,
        decision=decision,
        reviewer_type=str(provenance.get("runtime") or "") or None,
        source_sha256=source_sha256,
    )


def materialize_review_export(ep: Path, data: dict | None = None) -> Path | None:
    return review_record_persistence.materialize_export(
        Path(ep).resolve(),
        REVIEW_TYPE,
        payload=data,
        filename="story-semantic.json",
    )


def version_tuple(raw: object) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(raw or "").split("."))
    except ValueError:
        return (0,)


def episode_contract_version(ep: Path) -> str:
    versions = []
    try:
        state = episode_state_persistence.load(Path(ep).resolve()) or {}
        raw = str(state.get("tool_version") or "")
        vt = version_tuple(raw)
        if vt != (0,):
            versions.append((vt, raw))
    except Exception:
        pass
    for rel in ("meta/release-manifest.json", "meta/story-gates.json"):
        p = ep / rel
        if not p.is_file():
            continue
        try:
            raw = str(read_json(p).get("tool_version") or "")
            vt = version_tuple(raw)
            if vt != (0,):
                versions.append((vt, raw))
        except Exception:
            continue
    return max(versions, key=lambda x: x[0])[1] if versions else story_os_version()


def review_required(ep: Path) -> bool:
    try:
        if version_tuple(
            (episode_state_persistence.load(Path(ep).resolve()) or {}).get("tool_version")
        ) >= TARGET_CONTRACT:
            return True
    except Exception:
        pass
    p = Path(ep).resolve() / "meta/release-manifest.json"
    if p.is_file():
        try:
            return version_tuple(read_json(p).get("tool_version")) >= TARGET_CONTRACT
        except Exception:
            pass
    return False


def repo_file(raw: object, where: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{where} missing")
    rel = Path(raw.strip())
    p = rel.resolve() if rel.is_absolute() else (ROOT / rel).resolve()
    try:
        p.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"{where} escapes repository") from exc
    if not p.is_file():
        raise ValueError(f"{where} missing: {raw}")
    return p


def story_paths(ep: Path) -> tuple[Path, Path]:
    manifest = read_json(ep / "meta/release-manifest.json")
    artifacts = manifest.get("artifacts") or {}
    return (
        repo_file(artifacts.get("story"), "manifest.artifacts.story"),
        repo_file(artifacts.get("storyboard"), "manifest.artifacts.storyboard"),
    )


def validate_payload(data: dict, *, story_sha: str, storyboard_sha: str, version: str) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if data.get("story_os_version") != version:
        errors.append("story_os_version mismatch")
    if str(data.get("story_sha256") or "").lower() != story_sha.lower():
        errors.append("story_sha256 mismatch")
    if str(data.get("storyboard_sha256") or "").lower() != storyboard_sha.lower():
        errors.append("storyboard_sha256 mismatch")

    provenance = data.get("critic_provenance") or {}
    errors.extend(runtime_provenance.validate_critic_provenance(provenance))
    caption_sha = str(provenance.get("subtitle_source_sha256") or "")
    if caption_sha and (len(caption_sha) != 64 or any(ch not in "0123456789abcdef" for ch in caption_sha.lower())
                        or data.get("subtitle_source_sha256") != caption_sha):
        errors.append("review subtitle source SHA binding mismatch")
    attempt = provenance.get("attempt")
    continuation = (
        attempt == 3
        and provenance.get("direct_user_continuation_review") is True
        and provenance.get("review_scope") == "LOCKED_DOCUMENTARY_POLICY_REVISION"
        and provenance.get("review_epoch") == 2
        and provenance.get("epoch_attempt") == 1
        and all(isinstance(provenance.get(key), str)
                and len(provenance[key]) == 64
                and all(ch in "0123456789abcdef" for ch in provenance[key].lower())
                for key in ("previous_review_sha256", "previous_rubric_sha256", "current_rubric_sha256"))
        and provenance.get("previous_rubric_sha256") != provenance.get("current_rubric_sha256")
    )
    source_revision = (
        attempt == 4
        and provenance.get("direct_user_continuation_review") is True
        and provenance.get("review_scope") == "LOCKED_DOCUMENTARY_SOURCE_REVISION"
        and provenance.get("review_epoch") == 3
        and provenance.get("epoch_attempt") == 1
        and all(isinstance(provenance.get(k), str)
                and len(provenance[k]) == 64
                and all(ch in "0123456789abcdef" for ch in provenance[k].lower())
                for k in ("previous_review_sha256", "previous_storyboard_sha256", "current_rubric_sha256"))
        and provenance.get("previous_storyboard_sha256") != storyboard_sha
    )
    symbolic_remediation = (
        attempt == 5
        and provenance.get("direct_user_continuation_review") is True
        and provenance.get("review_scope") == "LOCKED_DOCUMENTARY_SYMBOLIC_REMEDIATION"
        and provenance.get("review_epoch") == 4
        and provenance.get("epoch_attempt") == 1
        and all(isinstance(provenance.get(k), str)
                and len(provenance[k]) == 64
                and all(ch in "0123456789abcdef" for ch in provenance[k].lower())
                for k in ("previous_review_sha256", "previous_storyboard_sha256",
                          "previous_rubric_sha256", "current_rubric_sha256"))
        and provenance.get("previous_storyboard_sha256") != storyboard_sha
        and provenance.get("previous_rubric_sha256") != provenance.get("current_rubric_sha256")
    )
    paired_caption = (
        attempt == 6
        and provenance.get("direct_user_continuation_review") is True
        and provenance.get("review_scope") == "LOCKED_PHOTO_TEXT_CAPTION_REVIEW"
        and provenance.get("review_epoch") == 5
        and provenance.get("epoch_attempt") == 1
        and all(isinstance(provenance.get(k), str)
                and len(provenance[k]) == 64
                and all(c in "0123456789abcdef" for c in provenance[k].lower())
                for k in ("previous_review_sha256", "previous_rubric_sha256",
                          "current_rubric_sha256", "subtitle_source_sha256"))
        and provenance.get("previous_rubric_sha256") != provenance.get("current_rubric_sha256")
        and provenance.get("subtitle_source_sha256") == data.get("subtitle_source_sha256")
    )
    # A normal photo-text source correction after Critic #2 is a NEW
    # user-directed review epoch. Never overwrite #2 or borrow the legacy
    # documentary policy-continuation (#3-#6) identities.
    photo_text_repair = (
        attempt == 7
        and provenance.get("direct_user_continuation_review") is True
        and provenance.get("review_scope") == "PHOTO_TEXT_SOURCE_REPAIR_AFTER_FAIL"
        and provenance.get("review_epoch") == 6
        and provenance.get("epoch_attempt") == 1
        and all(isinstance(provenance.get(k), str)
                and len(provenance[k]) == 64
                and all(ch in "0123456789abcdef" for ch in provenance[k].lower())
                for k in ("previous_review_sha256", "previous_storyboard_sha256",
                          "current_rubric_sha256", "subtitle_source_sha256"))
        and provenance.get("previous_storyboard_sha256") != storyboard_sha
        and provenance.get("subtitle_source_sha256") == data.get("subtitle_source_sha256")
    )
    character_source_repair = (
        attempt == 8
        and provenance.get("direct_user_continuation_review") is True
        and provenance.get("review_scope") == "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAIL"
        and provenance.get("review_epoch") == 7
        and provenance.get("epoch_attempt") == 1
        and all(isinstance(provenance.get(k), str)
                and len(provenance[k]) == 64
                and all(ch in "0123456789abcdef" for ch in provenance[k].lower())
                for k in ("previous_review_sha256", "previous_story_sha256",
                          "previous_storyboard_sha256", "new_character_authority_sha256",
                          "character_attestation_sha256", "current_rubric_sha256",
                          "subtitle_source_sha256"))
        and provenance.get("previous_story_sha256") != story_sha
        and provenance.get("previous_storyboard_sha256") != storyboard_sha
        and data.get("subtitle_source_sha256") == provenance.get("subtitle_source_sha256")
    )
    concept_selection_revision = (
        attempt == 3
        and provenance.get("direct_user_continuation_review") is True
        and provenance.get("review_scope") == "CONCEPT_SELECTION_SOURCE_REVISION"
        and provenance.get("review_epoch") == 2
        and provenance.get("epoch_attempt") == 1
        and all(isinstance(provenance.get(k), str) and len(provenance[k]) == 64
                and all(ch in "0123456789abcdef" for ch in provenance[k].lower())
                for k in ("previous_review_sha256", "previous_story_sha256",
                          "previous_storyboard_sha256", "concept_candidates_sha256",
                          "concept_review_sha256", "current_rubric_sha256",
                          "subtitle_source_sha256"))
        and provenance.get("previous_story_sha256") != story_sha
        and provenance.get("previous_storyboard_sha256") != storyboard_sha
        and data.get("subtitle_source_sha256") == provenance.get("subtitle_source_sha256")
    )
    concept_selection_source_repair = (
        attempt == 4
        and provenance.get("direct_user_continuation_review") is True
        and provenance.get("review_scope") == "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL"
        and provenance.get("review_epoch") == 3
        and provenance.get("epoch_attempt") == 1
        and all(isinstance(provenance.get(k), str) and len(provenance[k]) == 64
                and all(ch in "0123456789abcdef" for ch in provenance[k].lower())
                for k in ("previous_review_sha256", "previous_story_sha256",
                          "previous_storyboard_sha256", "concept_candidates_sha256",
                          "concept_review_sha256", "current_rubric_sha256",
                          "subtitle_source_sha256"))
        and provenance.get("previous_story_sha256") != story_sha
        and provenance.get("previous_storyboard_sha256") != storyboard_sha
        and data.get("subtitle_source_sha256") == provenance.get("subtitle_source_sha256")
    )
    concept_selection_source_repair_a5 = (
        attempt == 5
        and provenance.get("direct_user_continuation_review") is True
        and provenance.get("review_scope") == "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL_A5"
        and provenance.get("review_epoch") == 4
        and provenance.get("epoch_attempt") == 1
        and all(isinstance(provenance.get(k), str) and len(provenance[k]) == 64
                and all(ch in "0123456789abcdef" for ch in provenance[k].lower())
                for k in ("previous_review_sha256", "previous_story_sha256",
                          "previous_storyboard_sha256", "concept_candidates_sha256",
                          "concept_review_sha256", "current_rubric_sha256",
                          "subtitle_source_sha256"))
        and provenance.get("previous_story_sha256") != story_sha
        and provenance.get("previous_storyboard_sha256") != storyboard_sha
        and data.get("subtitle_source_sha256") == provenance.get("subtitle_source_sha256")
    )
    migrated_rubric_epoch = (
        attempt == 9
        and provenance.get("direct_user_continuation_review") is True
        and provenance.get("review_scope") == story_review_rubric_migration.REVIEW_SCOPE
        and provenance.get("review_epoch") == 8
        and provenance.get("epoch_attempt") == 1
        and all(isinstance(provenance.get(k),str)
                and len(provenance[k])==64
                and all(ch in "0123456789abcdef" for ch in provenance[k].lower())
                for k in ("previous_review_sha256","previous_review_request_sha256",
                          "previous_standard_sha256","current_standard_sha256",
                          "current_rubric_sha256"))
        and provenance.get("previous_standard_sha256") != provenance.get("current_standard_sha256")
    )
    a10_source_epoch = (
        attempt == 10
        and provenance.get("direct_user_continuation_review") is True
        and provenance.get("review_scope") == story_review_a10_source_revision.REVIEW_SCOPE
        and provenance.get("review_epoch") == 9
        and provenance.get("epoch_attempt") == 1
        and all(isinstance(provenance.get(k),str)
                and len(provenance[k]) == 64
                and all(c in "0123456789abcdef" for c in provenance[k].lower())
                for k in ("previous_a9_ticket_sha256",
                          "previous_a9_candidate_sha256",
                          "previous_storyboard_sha256","subtitle_source_sha256",
                          "current_rubric_sha256"))
        and provenance.get("previous_storyboard_sha256") != storyboard_sha
        and provenance.get("subtitle_source_sha256") == data.get("subtitle_source_sha256")
    )
    if attempt not in {1, 2} and not (
        continuation or source_revision or symbolic_remediation or paired_caption
        or photo_text_repair or character_source_repair or concept_selection_revision
        or concept_selection_source_repair or concept_selection_source_repair_a5 or migrated_rubric_epoch or a10_source_epoch
    ):
        errors.append("critic attempt must be 1 or 2 unless explicitly authorized policy continuation or SHA-bound source/caption revision")
    revisions = ({9} if a10_source_epoch else
                 {8} if migrated_rubric_epoch else
                 {0, 1, 2, 3, 4} if concept_selection_source_repair_a5 else
                 {0, 1, 2, 3} if concept_selection_source_repair else
                 {0, 1, 2} if concept_selection_revision else
                 {0, 1, 2, 3, 4, 5, 6, 7} if character_source_repair else
                 {0, 1, 2, 3, 4, 5, 6} if photo_text_repair else
                 {0, 1, 2, 3, 4, 5} if paired_caption else
                 {0, 1, 2, 3, 4} if symbolic_remediation else
                 {0, 1, 2, 3} if source_revision else
                 {0, 1, 2} if continuation else {0, 1})
    if data.get("revision_count") not in revisions:
        errors.append("revision_count invalid for critic review scope")
    elif attempt in {1, 2, 3, 4, 5, 6} and data.get("revision_count") != attempt - 1:
        errors.append("revision_count must equal critic attempt - 1")

    contract = data.get("contract") or {}
    for key in CONTRACT_FIELDS:
        if not str(contract.get(key) or "").strip():
            errors.append(f"contract.{key} missing")
    reinterpret = contract.get("ending_recontextualization")
    if not isinstance(reinterpret, list) or len([x for x in reinterpret if str(x).strip()]) < 3:
        errors.append("ending must recontextualize at least 3 concrete earlier facts")

    blind = data.get("blind_retell") or {}
    for key in BLIND_FIELDS:
        if not str(blind.get(key) or "").strip():
            errors.append(f"blind_retell.{key} missing")

    checks = data.get("hard_checks") or {}
    for key in HARD_CHECKS:
        if checks.get(key) is not True:
            errors.append(f"hard_checks.{key} must be true")

    issue_codes = data.get("issue_codes")
    if not isinstance(issue_codes, list):
        errors.append("issue_codes must be a list")
    elif issue_codes:
        errors.append("issue_codes must be empty for PASS")

    summary = data.get("summary") or {}
    if summary.get("passed") is not True:
        errors.append("summary.passed must be true")
    return errors


def _storyboard_sha_exception_matches(ep: Path, reviewed_sha: str, current_sha: str) -> bool:
    """Allow only an explicit user-approved, structure-preserving storyboard rebind."""
    path = Path(ep).resolve() / STORYBOARD_EXCEPTION_REL
    if not path.is_file():
        return False
    try:
        data = read_json(path)
    except Exception:
        return False
    if data.get("exception_type") != "direct_user_storyboard_revision":
        return False
    if data.get("user_approved") is not True or data.get("delegated_auto_review") is not False:
        return False
    if not str(data.get("user_statement") or "").strip():
        return False
    for row in data.get("items") or []:
        if not isinstance(row, dict):
            continue
        if (
            str(row.get("from_storyboard_sha256") or "").lower() == str(reviewed_sha).lower()
            and str(row.get("to_storyboard_sha256") or "").lower() == str(current_sha).lower()
            and row.get("user_approved") is True
            and row.get("delegated_auto_review") is False
        ):
            return True
    return False


def verify(ep: Path) -> list[str]:
    if not review_required(ep):
        return []
    data = load_review(ep)
    if not isinstance(data, dict):
        return ["meta/story-semantic-review.json missing"]
    try:
        story, storyboard = story_paths(ep)
    except Exception as exc:
        return [str(exc)]
    current_storyboard_sha = sha256_file(storyboard)
    caption_sha = str(data.get("subtitle_source_sha256") or "")
    if caption_sha:
        captions = ep / "docs/subtitles.yaml"
        if not captions.is_file() or caption_sha != sha256_file(captions):
            return ["current captions SHA does not match reviewed subtitle source"]
    errors = validate_payload(
        data,
        story_sha=sha256_file(story),
        storyboard_sha=current_storyboard_sha,
        version=episode_contract_version(ep),
    )
    if (data.get("critic_provenance") or {}).get("review_scope") == "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAIL":
        import character_contract
        prov = data["critic_provenance"]
        rev = (character_contract.load(ep) or {}).get("source_revision") or {}
        if (character_contract.validate(ep, require_locked=True)
                or rev.get("scope") != "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAILED_A7"
                or rev.get("previous_review_authority_sha256") != prov.get("previous_review_sha256")
                or rev.get("previous_story_sha256") != prov.get("previous_story_sha256")
                or rev.get("story_sha256") != data.get("story_sha256")
                or rev.get("storyboard_sha256") != data.get("storyboard_sha256")
                or rev.get("attestation_sha256") != prov.get("character_attestation_sha256")
                or character_contract.authority_sha256(ep) != prov.get("new_character_authority_sha256")):
            errors.append("Character Story source revision binding stale or missing")
    if "storyboard_sha256 mismatch" in errors and _storyboard_sha_exception_matches(
        ep, str(data.get("storyboard_sha256") or ""), current_storyboard_sha
    ):
        errors.remove("storyboard_sha256 mismatch")
    if (data.get("critic_provenance") or {}).get("direct_user_continuation_review") is True:
        provenance = data["critic_provenance"]
        scope = provenance.get("review_scope")
        manifest_by_scope = {
            "CONCEPT_SELECTION_SOURCE_REVISION":
                "meta/runtime/story-review-concept-selection-source-revision-a3.json",
            "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL":
                "meta/runtime/story-review-concept-selection-source-repair-after-fail-a4.json",
            "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL_A5":
                "meta/runtime/story-review-concept-selection-source-repair-after-fail-a5.json",
            "LOCKED_DOCUMENTARY_POLICY_REVISION":
                "meta/runtime/story-review-policy-continuation-a3.json",
            "LOCKED_DOCUMENTARY_SOURCE_REVISION":
                "meta/runtime/story-review-source-revision-a4.json",
            "LOCKED_DOCUMENTARY_SYMBOLIC_REMEDIATION":
                "meta/runtime/story-review-symbolic-remediation-a5.json",
            "LOCKED_PHOTO_TEXT_CAPTION_REVIEW":
                "meta/runtime/story-review-paired-caption-a6.json",
            "PHOTO_TEXT_SOURCE_REPAIR_AFTER_FAIL":
                "meta/runtime/story-review-photo-text-source-repair-a7.json",
            "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAIL":
                "meta/runtime/story-review-character-source-repair-a8.json",
            story_review_rubric_migration.REVIEW_SCOPE:
                story_review_rubric_migration.EPOCH_REL,
            story_review_a10_source_revision.REVIEW_SCOPE:
                story_review_a10_source_revision.EPOCH_REL,
        }
        rel = manifest_by_scope.get(scope)
        if rel is None:
            errors.append("unsupported independent Story Review continuation scope")
        else:
            try:
                evidence = read_json(Path(ep) / rel)
                uses_old_board = scope in {
                    "LOCKED_DOCUMENTARY_SOURCE_REVISION",
                    "LOCKED_DOCUMENTARY_SYMBOLIC_REMEDIATION",
                    "PHOTO_TEXT_SOURCE_REPAIR_AFTER_FAIL",
                    "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAIL",
                    "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL",
                    "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL_A5",
                }
                old_rubric = scope in {
                    "LOCKED_DOCUMENTARY_SYMBOLIC_REMEDIATION",
                    "LOCKED_PHOTO_TEXT_CAPTION_REVIEW",
                }
                subtitles = scope in {
                    "LOCKED_PHOTO_TEXT_CAPTION_REVIEW",
                    "PHOTO_TEXT_SOURCE_REPAIR_AFTER_FAIL",
                    "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAIL",
                    "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL",
                    "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL_A5",
                    story_review_a10_source_revision.REVIEW_SCOPE,
                }
                story_revised = scope == "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAIL"
                concept_revised = scope in {
                    "CONCEPT_SELECTION_SOURCE_REVISION",
                    "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL",
                    "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL_A5",
                }
                if (evidence.get("global_review_attempt") != provenance.get("attempt")
                        or evidence.get("review_scope") != scope
                        or evidence.get("review_epoch") != provenance.get("review_epoch")
                        or evidence.get("epoch_attempt") != provenance.get("epoch_attempt")
                        or evidence.get("previous_review_sha256") != provenance.get("previous_review_sha256")
                        or evidence.get("current_rubric_sha256") != provenance.get("current_rubric_sha256")
                        or evidence.get("story_sha256") != sha256_file(story)
                        or evidence.get("storyboard_sha256") != sha256_file(storyboard)
                        or (uses_old_board and evidence.get("previous_storyboard_sha256") != provenance.get("previous_storyboard_sha256"))
                        or (old_rubric and evidence.get("previous_rubric_sha256") != provenance.get("previous_rubric_sha256"))
                        or (subtitles and not (ep / "docs/subtitles.yaml").is_file())
                        or (subtitles and evidence.get("subtitle_source_sha256") != provenance.get("subtitle_source_sha256"))
                        or (subtitles and evidence.get("subtitle_source_sha256") != sha256_file(ep / "docs/subtitles.yaml"))
                        or (story_revised and evidence.get("previous_story_sha256") != provenance.get("previous_story_sha256"))
                        or (story_revised and evidence.get("new_character_authority_sha256") != provenance.get("new_character_authority_sha256"))
                        or (story_revised and evidence.get("character_attestation_sha256") != provenance.get("character_attestation_sha256"))
                        or (concept_revised and evidence.get("previous_story_sha256") != provenance.get("previous_story_sha256"))
                        or (concept_revised and evidence.get("previous_storyboard_sha256") != provenance.get("previous_storyboard_sha256"))
                        or (concept_revised and evidence.get("concept_candidates_sha256") != provenance.get("concept_candidates_sha256"))
                        or (concept_revised and evidence.get("concept_review_sha256") != provenance.get("concept_review_sha256"))
                        or (concept_revised and evidence.get("selected_id") != provenance.get("selected_concept_id"))
                        or (concept_revised and evidence.get("subtitle_source_sha256") != provenance.get("subtitle_source_sha256"))
                        or evidence.get("current_rubric_sha256") != _review_rubric_digest(Path(__file__).read_text(encoding="utf-8-sig"))):
                    errors.append("policy continuation authority or current rubric SHA mismatch")
                if concept_revised:
                    import concept_ambition
                    concept_path = ep / concept_ambition.REVIEW_REL
                    candidates_path = ep / concept_ambition.CANDIDATES_REL
                    if (concept_ambition.verify(ep)
                            or not concept_path.is_file() or not candidates_path.is_file()
                            or evidence.get("concept_review_sha256") != sha256_file(concept_path)
                            or evidence.get("concept_candidates_sha256") != sha256_file(candidates_path)
                            or evidence.get("subtitle_source_sha256") != sha256_file(ep / "docs/subtitles.yaml")
                            or evidence.get("previous_review_sha256") != provenance.get("previous_review_sha256")
                            or evidence.get("story_sha256") != sha256_file(story)
                            or evidence.get("storyboard_sha256") != sha256_file(storyboard)):
                        errors.append("concept-selection source revision binding stale or invalid")
                if scope == "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL":
                    previous = review_record_persistence.load_attempt(
                        Path(ep).resolve(), REVIEW_TYPE, 3, legacy_path=Path(ep) / REVIEW_REL
                    )
                    previous_provenance = (previous or {}).get("critic_provenance") or {}
                    previous_digest = (review_record_persistence._payload_content_sha(previous)
                                       if isinstance(previous, dict) else None)
                    if (not isinstance(previous, dict)
                            or previous_provenance.get("attempt") != 3
                            or (previous.get("summary") or {}).get("passed") is not False
                            or previous_digest != evidence.get("previous_review_sha256")
                            or evidence.get("previous_story_sha256") != previous.get("story_sha256")
                            or evidence.get("previous_storyboard_sha256") != previous.get("storyboard_sha256")
                            or evidence.get("previous_issue_codes") != previous.get("issue_codes")):
                        errors.append("attempt 4 continuation is not bound to the immutable failed attempt 3")
                if scope == "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL_A5":
                    previous = review_record_persistence.load_attempt(
                        Path(ep).resolve(), REVIEW_TYPE, 4, legacy_path=Path(ep) / REVIEW_REL
                    )
                    previous_provenance = (previous or {}).get("critic_provenance") or {}
                    previous_digest = (review_record_persistence._payload_content_sha(previous)
                                       if isinstance(previous, dict) else None)
                    if (not isinstance(previous, dict)
                            or previous_provenance.get("attempt") != 4
                            or previous_provenance.get("review_scope") != "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL"
                            or (previous.get("summary") or {}).get("passed") is not False
                            or previous_digest != evidence.get("previous_review_sha256")
                            or evidence.get("previous_story_sha256") != previous.get("story_sha256")
                            or evidence.get("previous_storyboard_sha256") != previous.get("storyboard_sha256")
                            or evidence.get("previous_issue_codes") != previous.get("issue_codes")):
                        errors.append("attempt 5 continuation is not bound to the immutable failed attempt 4")
            except (OSError, ValueError, KeyError, RuntimeError):
                errors.append("policy continuation manifest missing or invalid")
    if ((data.get("critic_provenance") or {}).get("review_scope")
            == story_review_rubric_migration.REVIEW_SCOPE):
        if not story_review_rubric_migration.validate_epoch(
                ep, data.get("critic_provenance") or {}):
            errors.append("migrated rubric epoch source SHA or durable authority mismatch")
    if ((data.get("critic_provenance") or {}).get("review_scope")
            == story_review_a10_source_revision.REVIEW_SCOPE):
        if not story_review_a10_source_revision.validate_epoch(
                ep, data.get("critic_provenance") or {}):
            errors.append("A10 source revision SHA or immutable A9 receipt mismatch")
    if propagation_core_gate.required(ep):
        errors.extend(propagation_core_gate.verify(ep))
    return errors


def resolve_codex(raw: str | None) -> Path:
    import codex_cli_contract
    return codex_cli_contract.resolve_path(raw)


def command_prefix(codex: Path) -> list[str]:
    import codex_cli_contract
    return codex_cli_contract.command_prefix(codex)


def _locked_documentary_rubric(ep: Path) -> bool:
    """Only user-locked stories explicitly scoped as real-life/non-anomalous."""
    try:
        request = runtime_request.authority_for_episode(Path(ep).resolve())
        story_input = (request or {}).get("story_input") if isinstance(request, dict) else None
        return (
            isinstance(story_input, dict)
            and story_input.get("mode") == "locked_story"
            and story_input.get("allow_structure_rewrite") is False
            and not propagation_core_gate.anomaly_applicable(ep)
        )
    except Exception:
        return False


def critic_prompt(ep: Path, story: Path, storyboard: Path, candidate: Path, attempt: int) -> str:
    rel_ep = ep.relative_to(ROOT).as_posix()
    rel_story = story.relative_to(ROOT).as_posix()
    rel_board = storyboard.relative_to(ROOT).as_posix()
    rel_captions = (ep / "docs/subtitles.yaml").relative_to(ROOT).as_posix()
    rel_out = candidate.relative_to(ROOT).as_posix()
    ordinary_life_override = "" if propagation_core_gate.anomaly_applicable(ep) else """
ORDINARY-LIFE OVERRIDE (takes precedence over anomaly-specific rules below):
- This Episode is explicitly locked as anomaly_applicable=false. Do NOT invent horror, mystery, paranormal behavior, investigation, anomaly rules, or an abnormal response merely to satisfy generic schema wording.
- Evaluate whether the ordinary-day arc, relationships, spatial progression, midpoint route change, emotional/visual peak, ending payoff and delete-frame density are coherent and production-worthy.
- contract.core_anomaly / rule / trigger / direct_consequence and blind_retell.core_anomaly_rule must be non-empty explicit NOT_APPLICABLE statements explaining that the no-anomaly design is intentional.
- hard_checks.mechanism_consistency means the Episode remains consistently non-anomalous; hard_checks.trigger_consequence means ordinary actions have readable ordinary responses/consequences rather than an abnormal mechanism.
- ending_recontextualization may pay off at least three earlier ordinary-life facts, objects, or relationship beats; it does not need a twist.
- V2.5 anomaly propagation_core is NOT required for this explicitly ordinary-life Episode. Omit it rather than fabricating an abnormal_response.
"""
    concept_context = ""
    if attempt in {3, 4}:
        authority = ep / (
            "meta/runtime/story-review-concept-selection-source-revision-a3.json"
            if attempt == 3 else
            "meta/runtime/story-review-concept-selection-source-repair-after-fail-a4.json"
        )
        if authority.is_file():
            selection = read_json(authority)
            if attempt == 3:
                concept_context = f"""
AUTHORIZED CONCEPT-SELECTION SOURCE REVISION:
Concept Ambition selected {selection.get('selected_id')} ({selection.get('selected_title')}). The prior Story Critic PASS belongs to a different source SHA and must not influence this decision. Review the current story and storyboard independently; passing the separate concept gate does not imply this story passes.
"""
            else:
                issues = ", ".join(selection.get("previous_issue_codes") or []) or "(none recorded)"
                concept_context = f"""
AUTHORIZED POST-FAIL CONCEPT-SELECTION SOURCE REPAIR:
Concept Ambition selected {selection.get('selected_id')} ({selection.get('selected_title')}). This is one fresh review after the preserved Story Critic attempt 3 FAIL. Its issue codes were: {issues}. Review the current story, storyboard, and matching captions independently against the rubric, with special attention to whether these failures were actually repaired. The prior PASS and failed review belong to different source SHAs; neither decides this review. This one-time attempt cannot be retried.
"""
    prompt = f"""You are an adversarial Story Critic in a fresh isolated session.
Do NOT rewrite the story. Do NOT score it politely. Your job is to find reasons it should NOT enter production.
{concept_context}
Read:
- {rel_story}
- {rel_board}
- {rel_captions} (current authored caption source by frame number; evaluate each scene WITH its matching caption, and do not infer user approval or a subtitle lock)
- standards/制作规范_正式版.md
- standards/创作执行强制规范_V2.0.3.2.md
- standards/story_regressions/cases.json
- standards/传播核与动作回应链规范_V1.0.md

This is critic attempt {attempt}. Ignore propagation scores and author self-evaluation.
{ordinary_life_override}
Hard rules:
1. A viewer must be able to explain protagonist, why they are here, their personal stake, the ONE core anomaly rule, trigger, direct consequence, midpoint reframe, climax choice/cost, result and aftermath.
2. The main events must be explainable by one coherent underlying anomaly mechanism. If an object first returns by itself, later guides people, then suddenly "marks the next person" without one established rule explaining all three, mechanism_consistency=false.
3. Causality must read as reality goal -> rule/setup -> meaningful choice/violation -> direct consequence -> forced next action -> climax choice/cost -> result -> aftermath. A warning revealed only after the violation cannot retroactively create a meaningful choice unless the story established the rule another way.
4. "I found them", "the door opened", "the monster appeared", "the photo changed" are discoveries/setup, not a climax by themselves. The climax needs choice, cost, relationship change, rule payoff, identity turn or irreversible consequence.
5. The ending must recontextualize at least THREE concrete earlier facts. Introducing a brand-new anomaly behavior at the end is not payoff.
6. In any run of 5 storyboard frames, at least one frame must add new evidence, causal turn or cognitive upgrade. Apply the delete-frame test.
7. Perform a BLIND RETELL from your own understanding. If you need "maybe / perhaps / unclear" to explain the core mechanism or climax, clarity/mechanism_consistency must fail.
8. PASS only when every hard check is true and issue_codes is empty.
9. V2.5 PROPAGATION CORE: identify one ordinary protagonist action that causes a direct abnormal response and a visible consequence.
10. Write a <=10-second retell sentence; avoid lore-heavy explanation.
11. Bind trigger_frame, response_frame and payoff_frame to actual storyboard frames. Default trigger <=50%; if later, explain why.
12. Golden examples are structural references only; do not copy location + prop + trigger action + climax surface together.
<!-- STORY_OS_V2_5_PROPAGATION_CORE -->

Write ONLY valid JSON to {rel_out}. Do not modify any other repository file.
Required JSON shape:
{{
  "contract": {{
    "protagonist": "...",
    "presence_reason": "...",
    "personal_stake": "...",
    "core_anomaly": "...",
    "rule": "...",
    "trigger": "...",
    "direct_consequence": "...",
    "midpoint_reframe": "...",
    "climax_choice": "...",
    "ending_recontextualization": ["earlier fact 1", "earlier fact 2", "earlier fact 3"]
  }},
  "propagation_core": {{
    "retell_sentence": "...",
    "protagonist_action": "...",
    "abnormal_response": "...",
    "consequence": "...",
    "response_latency": "immediate",
    "visual_causality": "strong",
    "retellable_in_10s": true,
    "social_send_impulse": "strong",
    "trigger_frame": 9,
    "response_frame": 10,
    "payoff_frame": 14,
    "late_trigger_exception_reason": "",
    "surface_copy_guard": {{
      "structural_reference_only": true,
      "copied_surface_elements": []
    }}
  }},
  "blind_retell": {{
    "protagonist_and_reason": "...",
    "core_anomaly_rule": "...",
    "worsening_choice": "...",
    "climax_resolution": "...",
    "ending_reinterpretation": "..."
  }},
  "hard_checks": {{
    "clarity": true,
    "causal_chain": true,
    "mechanism_consistency": true,
    "motivation_stake": true,
    "trigger_consequence": true,
    "midpoint_reframe": true,
    "climax_payoff": true,
    "ending_payoff": true,
    "storyboard_information_gain": true,
    "delete_frame_test": true
  }},
  "issue_codes": [],
  "notes": ["specific evidence or failure notes"],
  "summary": {{"passed": true}}
}}
If any hard rule fails, set its boolean false, add specific codes such as STORY_COMPREHENSION_FAIL, CAUSAL_CHAIN_BROKEN, MECHANISM_CONTRADICTION, CLIMAX_DISCOVERY_ONLY, ENDING_PAYOFF_TOO_WEAK, STORYBOARD_STALL, and set summary.passed=false.
Episode: {rel_ep}
"""
    if _locked_documentary_rubric(ep):
        # Replace incompatible anomaly-oriented *instructions*, not the review
        # authority, mandatory fields, true/false checks or independent critic.
        # The original full rubric remains unchanged for authored/mystery stories.
        start = prompt.index("Hard rules:\n")
        end = prompt.index("Write ONLY valid JSON", start)
        documentary_rules = """LOCKED NON-ANOMALOUS DOCUMENTARY HARD RULES:
1. Do not rewrite any user-locked scene, subtitle, character, age, amount, diagnosis, legal outcome or frame count. Check exact source fidelity.
2. Check real chronology and age arithmetic. A visual casting age may differ from chronological age only when clearly identified as appearance; never silently excuse a numerical contradiction.
3. In cumulative real-life hardship, disaster, illness and accidents can be independently caused; judge the credibility of each asserted relation and the accumulation of financial/caregiving consequences, not a fictional shared mechanism.
4. The midpoint may be a grounded change of stakes or role, not a supernatural revelation. The emotional peak may be a loss; any closing moral choice must come from the actual words, not invented actions.
5. An open ending with debts unpaid can be a truthful payoff. Revisit three concrete earlier facts; do not imply forgiveness, legal relief, new income, or a happy rescue unless the source states it.
6. This is a locked 25-frame PHOTO-TEXT carousel, not a standalone silent-image show. Evaluate each visual + the exact corresponding user subtitle as one unit. A deliberately quiet image may supply emotional pacing while its paired subtitle introduces a new claim or decision. Fail redundancy only when the combined pair adds no distinct factual, visual, emotional or chronological information. Do not demand deleting a user-locked frame when its subtitle carries unique content.
7. Treat suicide, cancer, disability and poverty with dignity; avoid sensationalism and unearned blame.
8. For the schema's anomaly/rule/trigger/core_anomaly_rule fields, give explicit non-empty NOT_APPLICABLE explanations. Do not invent paranormal phenomena or an abnormal response. propagation_core is not required here.
8a. User-authored locked storyboard imagery is an authoritative *visual brief*, not an assertion that each prop was independently documented in the prose story. A visibly symbolic object or composite shot may appear even without a narrated physical discovery. Do NOT mistake such a visual metaphor for new forensic evidence. Fail when the storyboard or its production notes asserts that an undocumented object was actually recovered, identified, investigated or used as real proof.
9. Evaluate every hard check truthfully. If source facts are contradictory, or any check fails, give specific issue_codes and summary.passed=false.
"""
        prompt = prompt[:start] + documentary_rules + "\n" + prompt[end:]
        # The generic example requires an invented abnormal-response object.
        # Omit that optional shape entirely for non-anomalous locked stories.
        example_start = prompt.index('  "propagation_core": {')
        example_end = prompt.index('  "blind_retell": {', example_start)
        prompt = prompt[:example_start] + prompt[example_end:]
    return prompt


def _finalize_review(ep: Path, data: dict, *, attempt: int, before_story: str, before_board: str, provenance: dict) -> int:
    data["schema_version"] = 1
    data["story_os_version"] = episode_contract_version(ep)
    data["story_sha256"] = before_story
    data["storyboard_sha256"] = before_board
    data["revision_count"] = attempt - 1
    data["critic_provenance"] = provenance
    if provenance.get("subtitle_source_sha256"):
        data["subtitle_source_sha256"] = provenance["subtitle_source_sha256"]
    errors = validate_payload(
        data,
        story_sha=before_story,
        storyboard_sha=before_board,
        version=episode_contract_version(ep),
    )
    decision = "PASS" if not errors else "FAIL"
    source_sha = hashlib.sha256(
        f"{before_story}|{before_board}".encode("utf-8")
    ).hexdigest()
    save_review(ep, data, decision=decision, source_sha256=source_sha)
    (ep / (story_review_a10_source_revision.CANDIDATE_REL
           if attempt == 10 else CANDIDATE_REL)).unlink(missing_ok=True)
    if propagation_core_gate.required(ep):
        errors.extend(propagation_core_gate.verify(ep))
    if errors:
        print("STORY SEMANTIC REVIEW FAIL")
        for error in errors:
            print("FAIL:", error)
        for code in data.get("issue_codes") or []:
            print("ISSUE:", code)
        return 2
    print("STORY SEMANTIC REVIEW PASS")
    return 0


def finalize_product_review(ep: Path, *, attempt: int, runtime: str) -> int:
    story, storyboard = story_paths(ep)
    candidate = ep / CANDIDATE_REL
    data, provenance = product_review_adapter.finalize_candidate(
        ep,
        kind="story-semantic",
        runtime=runtime,
        attempt=attempt,
        candidate_path=candidate,
    )
    rc = _finalize_review(
        ep,
        data,
        attempt=attempt,
        before_story=sha256_file(story),
        before_board=sha256_file(storyboard),
        provenance=provenance,
    )
    if rc == 0:
        final_export = materialize_review_export(ep, load_review(ep))
        if final_export is None:
            raise RuntimeError("story semantic review export missing after PASS")
        product_review_adapter.mark_complete(
            ep, "story-semantic", attempt=attempt, final_path=final_export
        )
    return rc


def schedule_critic_shadow(
    ep: Path, *, attempt: int, story: Path, storyboard: Path, sources: list[Path],
    review_attempt: int | None = None,
    canonical_source_files: list[dict] | None = None,
) -> dict:
    """Schedule the advisory Critic beside, never inside, canonical Story Review."""
    try:
        import story_semantic_critic_adapter as critic_shadow
    except ModuleNotFoundError:
        from agents import story_semantic_critic_adapter as critic_shadow

    config = critic_shadow.adapter_config()
    if config.get("shadow_enabled") is not True:
        return {"enabled": False, "scheduled": False}
    if config.get("production_enabled") is True:
        raise RuntimeError("Critic shadow/production overlap; refusing Story Review dispatch")
    applicability = critic_shadow.frozen_applicability_context(ep)
    applicability_path = ep / critic_shadow.APPLICABILITY_REL
    prompt = critic_shadow.build_decision_prompt(
        attempt=int(review_attempt if review_attempt is not None else attempt),
        story_text=story.read_text(encoding="utf-8-sig"),
        storyboard_text=storyboard.read_text(encoding="utf-8-sig"),
        rubric_text="\n\n".join(path.read_text(encoding="utf-8-sig") for path in sources[2:]),
        applicability=applicability,
    )
    if canonical_source_files is not None:
        frozen = {str(row.get("path")): str(row.get("sha256")).lower()
                  for row in canonical_source_files if isinstance(row, dict)}
        for source in sources:
            relative = source.resolve().relative_to(ROOT.resolve()).as_posix()
            if frozen.get(relative) != sha256_file(source).lower():
                raise RuntimeError(f"Critic shadow source differs from canonical review request: {relative}")
    shadow_request = critic_shadow.prepare_shadow_request(
        ep, attempt=attempt, review_attempt=(review_attempt if review_attempt is not None else attempt),
        prompt=prompt, story_path=story,
        storyboard_path=storyboard, rubric_paths=[*sources[2:], applicability_path],
        applicability_context=applicability,
    )
    return {
        "enabled": True,
        "scheduled": isinstance(shadow_request, dict),
            "request_id": (shadow_request or {}).get("request_id"),
        "request_path": (shadow_request or {}).get("request_path"),
        "request_snapshot_path": (shadow_request or {}).get("request_snapshot_path"),
        "request_snapshot_sha256": (shadow_request or {}).get("request_snapshot_sha256"),
        "applicability_context": applicability,
        "candidate_authority": "runtime_evidence_only",
    }


def _review_rubric_digest(source: str) -> str:
    """SHA over the actual critic_prompt function AST, not a mutable label."""
    tree = ast.parse(source)
    function = next((node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "critic_prompt"), None)
    if function is None:
        raise RuntimeError("story critic rubric function missing")
    return hashlib.sha256(ast.dump(function, include_attributes=False).encode("utf-8")).hexdigest()


def _authorize_policy_continuation(ep: Path, *, attempt: int, prior_rubric_ref: str | None) -> dict:
    """An explicit, one-time review #3 after two real failures and a changed rubric.

    Not a reset: keep the earlier reviews in their existing immutable Review
    repository. A failed new review cannot be retried by repeating this command.
    """
    if attempt != 3 or not prior_rubric_ref:
        raise RuntimeError("policy continuation requires attempt=3 and --prior-rubric-ref")
    if not _locked_documentary_rubric(ep):
        raise RuntimeError("policy continuation is only available for locked non-anomalous stories")
    prior = load_review(ep)
    if not isinstance(prior, dict) or (prior.get("critic_provenance") or {}).get("attempt") != 2:
        raise RuntimeError("prior independent Critic attempt #2 missing")
    if (prior.get("summary") or {}).get("passed") is not False:
        raise RuntimeError("continuation requires a failed prior Critic #2")
    if (ep / "meta/runtime/story-review-policy-continuation-a3.json").exists():
        raise RuntimeError("policy continuation #3 already authorized; cannot dispatch twice")
    relative = Path("episodes/_system/story_review.py").as_posix()
    old_commit = subprocess.run(["git", "rev-parse", "--verify", prior_rubric_ref + "^{commit}"],
                                cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", old_commit, "HEAD"], cwd=ROOT)
    if ancestor.returncode != 0:
        raise RuntimeError("prior rubric ref is not an ancestor of current HEAD")
    old_code = subprocess.run(["git", "show", f"{old_commit}:{relative}"], cwd=ROOT,
                              capture_output=True, check=True).stdout.decode("utf-8-sig")
    before_rubric = _review_rubric_digest(old_code)
    after_rubric = _review_rubric_digest(Path(__file__).read_text(encoding="utf-8-sig"))
    if before_rubric == after_rubric:
        raise RuntimeError("previous and current Critic rubric match; continuation not authorized")
    story, storyboard = story_paths(ep)
    prior_digest = review_authority_sha256(ep)
    if not prior_digest:
        raise RuntimeError("prior Critic authority SHA missing")
    binding = {
        "schema": "storyos.story_critic_policy_continuation.v1",
        "review_scope": "LOCKED_DOCUMENTARY_POLICY_REVISION",
        "global_review_attempt": 3,
        "review_epoch": 2,
        "epoch_attempt": 1,
        "authorization": "direct_user_continuation",
        "previous_review_sha256": prior_digest,
        "previous_review_attempt": 2,
        "previous_review_passed": False,
        "previous_rubric_git_commit": old_commit,
        "previous_rubric_sha256": before_rubric,
        "current_rubric_sha256": after_rubric,
        "story_sha256": sha256_file(story),
        "storyboard_sha256": sha256_file(storyboard),
        "previous_storyboard_sha256": prior.get("storyboard_sha256"),
        "source_unchanged": prior.get("story_sha256") == sha256_file(story)
            and prior.get("storyboard_sha256") == sha256_file(storyboard),
        "previous_issue_codes": list(prior.get("issue_codes") or []),
        "reason": "Material rubric correction from anomaly plot to locked real-life documentary; no source rewrite or fabricated prior PASS",
    }
    target = ep / "meta/runtime/story-review-policy-continuation-a3.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, binding)
    return binding


def _authorize_source_revision(ep: Path, *, attempt: int) -> dict:
    """One SHA-bound user-directed review of corrected documentary storyboard."""
    if attempt != 4 or not _locked_documentary_rubric(ep):
        raise RuntimeError("source revision requires locked documentary attempt=4")
    target = ep / "meta/runtime/story-review-source-revision-a4.json"
    if target.exists():
        raise RuntimeError("source revision attempt 4 already authorized; no redispatch")
    prior = load_review(ep)
    if (not isinstance(prior, dict)
            or (prior.get("critic_provenance") or {}).get("attempt") != 3
            or (prior.get("summary") or {}).get("passed") is not False
            or not prior.get("issue_codes")):
        raise RuntimeError("must have a real previous failed attempt 3")
    policy_path = ep / "meta/runtime/story-review-policy-continuation-a3.json"
    if not policy_path.is_file():
        raise RuntimeError("previous policy authority missing")
    rubric_sha = _review_rubric_digest(Path(__file__).read_text(encoding="utf-8-sig"))
    if read_json(policy_path).get("current_rubric_sha256") != rubric_sha:
        raise RuntimeError("rubric must not silently change during source continuation")
    story, storyboard = story_paths(ep)
    story_sha, board_sha = sha256_file(story), sha256_file(storyboard)
    previous_board_sha = str(prior.get("storyboard_sha256") or "")
    if story_sha != prior.get("story_sha256") or board_sha == previous_board_sha:
        raise RuntimeError("story must be unchanged; storyboard must actually be revised")
    board_text = storyboard.read_text(encoding="utf-8-sig")
    if not all(token in board_text for token in
               ("左右两个时序画格", "不是同一人", "次子的生母")):
        raise RuntimeError("real issues from attempt 3 are not yet repaired")
    prior_sha = review_authority_sha256(ep)
    if not prior_sha:
        raise RuntimeError("prior review authority SHA missing")
    evidence = {
        "schema": "storyos.story_critic_source_revision.v1",
        "authorization": "direct_user_continuation",
        "review_scope": "LOCKED_DOCUMENTARY_SOURCE_REVISION",
        "global_review_attempt": 4, "review_epoch": 3, "epoch_attempt": 1,
        "previous_review_attempt": 3, "previous_review_passed": False,
        "previous_review_sha256": prior_sha,
        "previous_issue_codes": list(prior.get("issue_codes") or []),
        "previous_storyboard_sha256": previous_board_sha,
        "storyboard_sha256": board_sha, "story_sha256": story_sha,
        "current_rubric_sha256": rubric_sha,
        "reason": "User-directed repair of frame16 time panels and distinct spouse identities after FAIL #3",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, evidence)
    return evidence


def _authorize_symbolic_remediation(ep: Path, *, attempt: int) -> dict:
    """One final, source-and-rubric-bound review after evidence/metaphor conflation."""
    if attempt != 5 or not _locked_documentary_rubric(ep):
        raise RuntimeError("symbolic remediation requires locked documentary attempt=5")
    target = ep / "meta/runtime/story-review-symbolic-remediation-a5.json"
    if target.exists():
        raise RuntimeError("symbolic remediation attempt 5 already authorized")
    prior = load_review(ep)
    if (not isinstance(prior, dict)
            or (prior.get("critic_provenance") or {}).get("attempt") != 4
            or (prior.get("summary") or {}).get("passed") is not False
            or "DOCUMENTARY_EVIDENCE_UNSUPPORTED" not in (prior.get("issue_codes") or [])):
        raise RuntimeError("must have actual failed documentary evidence review #4")
    earlier_path = ep / "meta/runtime/story-review-source-revision-a4.json"
    if not earlier_path.is_file():
        raise RuntimeError("source revision #4 authority missing")
    old_rubric = read_json(earlier_path).get("current_rubric_sha256")
    new_rubric = _review_rubric_digest(Path(__file__).read_text(encoding="utf-8-sig"))
    if not old_rubric or old_rubric == new_rubric:
        raise RuntimeError("symbolic evidence rubric must materially change")
    story, board = story_paths(ep)
    story_sha, board_sha = sha256_file(story), sha256_file(board)
    old_board = str(prior.get("storyboard_sha256") or "")
    if story_sha != prior.get("story_sha256") or board_sha == old_board:
        raise RuntimeError("source SHA must change only for storyboard, not story")
    board_text = board.read_text(encoding="utf-8-sig")
    if not all(s in board_text for s in ("象征性哀伤空镜", "不表述发现鞋", "用户指定的岸边球鞋")):
        raise RuntimeError("source still lacks clear symbol-versus-evidence distinction")
    prior_review_sha = review_authority_sha256(ep)
    if not prior_review_sha:
        raise RuntimeError("prior review identity missing")
    evidence = {
        "schema": "storyos.story_critic_symbolic_remediation.v1",
        "authorization": "direct_user_continuation",
        "review_scope": "LOCKED_DOCUMENTARY_SYMBOLIC_REMEDIATION",
        "global_review_attempt": 5, "review_epoch": 4, "epoch_attempt": 1,
        "previous_review_attempt": 4,
        "previous_review_passed": False,
        "previous_issue_codes": list(prior.get("issue_codes") or []),
        "previous_review_sha256": prior_review_sha,
        "previous_storyboard_sha256": old_board,
        "storyboard_sha256": board_sha, "story_sha256": story_sha,
        "previous_rubric_sha256": old_rubric,
        "current_rubric_sha256": new_rubric,
        "reason": "The user explicitly authored shoes as a symbolic visual; distinguish illustration from forensic evidence",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, evidence)
    return evidence


def _authorize_paired_caption_revision(ep: Path, *, attempt: int) -> dict:
    """One provenance-bound reviewer run after the caption-omission contract fix.

    Review #5 omitted the 25 locked subtitles and failed on image-only
    redundancy. The new review is globally #6 and epoch 5's first (and only)
    attempt; it cannot consume old authorizations or be re-dispatched.
    """
    if attempt != 6 or not _locked_documentary_rubric(ep):
        raise RuntimeError("paired caption revision only allows locked documentary attempt 6")
    target = ep / "meta/runtime/story-review-paired-caption-a6.json"
    if target.exists():
        raise RuntimeError("paired caption review #6 already authorized; no redispatch")
    previous = load_review(ep)
    if (not isinstance(previous, dict)
            or (previous.get("critic_provenance") or {}).get("attempt") != 5
            or (previous.get("summary") or {}).get("passed") is not False
            or not {"STORYBOARD_STALL", "DELETE_FRAME_REDUNDANCY"}.intersection(
                previous.get("issue_codes") or [])):
        raise RuntimeError("missing actual image-only failure from reviewer attempt #5")
    predecessor_path = ep / "meta/runtime/story-review-symbolic-remediation-a5.json"
    if not predecessor_path.is_file():
        raise RuntimeError("predecessor authorization for attempt 5 missing")
    before_rubric = read_json(predecessor_path).get("current_rubric_sha256")
    after_rubric = _review_rubric_digest(Path(__file__).read_text(encoding="utf-8-sig"))
    if not before_rubric or before_rubric == after_rubric:
        raise RuntimeError("paired-caption revision must materially change review rubric")
    story, board = story_paths(ep)
    captions = ep / "docs/subtitles.yaml"
    if not captions.is_file():
        raise RuntimeError("paired-caption review requires the actual 25 subtitles")
    story_sha, board_sha, subtitle_sha = (sha256_file(p) for p in (story, board, captions))
    if story_sha != previous.get("story_sha256") or board_sha != previous.get("storyboard_sha256"):
        raise RuntimeError("paired-caption policy revision cannot silently modify locked source")
    import re
    caption_ids = re.findall(r'(?m)^\s+(\d+):\s+"', captions.read_text(encoding="utf-8-sig"))
    board_ids = re.findall(r'(?m)^\|\s*(\d{2})\s*\|', board.read_text(encoding="utf-8-sig"))
    if [int(x) for x in caption_ids] != list(range(1, 26)) or [int(x) for x in board_ids] != list(range(1, 26)):
        raise RuntimeError("25 frame-to-caption pairings are not bijective")
    previous_sha = review_authority_sha256(ep)
    if not previous_sha:
        raise RuntimeError("missing immutable previous review authority digest")
    evidence = {
        "schema": "storyos.story_critic_paired_caption_revision.v1",
        "authorization": "direct_user_continuation",
        "review_scope": "LOCKED_PHOTO_TEXT_CAPTION_REVIEW",
        "global_review_attempt": 6,
        "review_epoch": 5,
        "epoch_attempt": 1,
        "previous_review_attempt": 5,
        "previous_review_passed": False,
        "previous_review_sha256": previous_sha,
        "previous_issue_codes": list(previous.get("issue_codes") or []),
        "previous_rubric_sha256": before_rubric,
        "current_rubric_sha256": after_rubric,
        "story_sha256": story_sha,
        "storyboard_sha256": board_sha,
        "subtitle_source_sha256": subtitle_sha,
        "reason": "Correct prior image-only redundancy mistake by reviewing each user-locked image together with its exact subtitle",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, evidence)
    return evidence


def _authorize_photo_text_source_repair(ep: Path, *, attempt: int) -> dict:
    """One SHA-bound new review after a real independent #2 content FAIL.

    No attempt reset: the previous failed Review Authority and model log
    remain immutable. This path cannot authorize a third review of the same
    source, a failed CLI run, or a documentary policy override.
    """
    if attempt != 7 or _locked_documentary_rubric(ep):
        raise RuntimeError("photo-text source repair is only attempt=7 for non-documentary episodes")
    target = ep / "meta/runtime/story-review-photo-text-source-repair-a7.json"
    if target.exists():
        raise RuntimeError("photo-text repair #7 already authorized; no redispatch")
    prior = load_review(ep)
    if (not isinstance(prior, dict)
            or (prior.get("critic_provenance") or {}).get("attempt") != 2
            or (prior.get("summary") or {}).get("passed") is not False
            or set(prior.get("issue_codes") or []) !=
            {"DELETE_FRAME_TEST_FAIL", "AUTHORITATIVE_SUBTITLES_MISSING"}):
        raise RuntimeError("requires real failed independent review #2 with exact remediation issues")
    story, board = story_paths(ep)
    source_sha = sha256_file(story)
    board_sha = sha256_file(board)
    if (source_sha != prior.get("story_sha256")
            or board_sha == prior.get("storyboard_sha256")):
        raise RuntimeError("story must remain unchanged, storyboard must materially change")
    captions = ep / "docs/subtitles.yaml"
    if not captions.is_file():
        raise RuntimeError("repaired authoritative subtitles missing")
    from text_audit import parse_simple_subtitles_yaml
    parsed = parse_simple_subtitles_yaml(captions)
    total = int((read_json(ep / "meta/release-manifest.json").get("release") or {}).get("body_frame_count") or 0)
    if total < 1 or sorted(parsed.get("frames") or {}) != list(range(1, total + 1)):
        raise RuntimeError("repaired captions must match every real storyboard frame")
    previous_sha = review_authority_sha256(ep)
    if not previous_sha:
        raise RuntimeError("immutable previous Review Authority SHA missing")
    binding = {
        "schema": "storyos.story_critic_photo_text_repair.v1",
        "authorization": "direct_user_continuation",
        "review_scope": "PHOTO_TEXT_SOURCE_REPAIR_AFTER_FAIL",
        "global_review_attempt": 7,
        "review_epoch": 6,
        "epoch_attempt": 1,
        "previous_review_sha256": previous_sha,
        "previous_storyboard_sha256": prior["storyboard_sha256"],
        "previous_review_attempt": 2,
        "previous_issue_codes": list(prior["issue_codes"]),
        "story_sha256": source_sha,
        "storyboard_sha256": board_sha,
        "subtitle_source_sha256": sha256_file(captions),
        "current_rubric_sha256": _review_rubric_digest(
            Path(__file__).read_text(encoding="utf-8-sig")
        ),
        "reason": "Source-and-subtitle repair for real independent review #2 content FAIL",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, binding)
    return binding



def _authorize_character_source_repair(ep: Path, *, attempt: int) -> dict:
    """Authorize precisely one independent Story Critic #8 for a CAS-relocked story."""
    import character_contract
    from text_audit import parse_simple_subtitles_yaml

    if attempt != 8 or _locked_documentary_rubric(ep):
        raise RuntimeError("Character Story source repair is only attempt 8 for standard episodes")
    target = ep / "meta/runtime/story-review-character-source-repair-a8.json"
    if target.exists():
        raise RuntimeError("Story source review #8 already authorized")
    prior = load_review(ep)
    if (not isinstance(prior, dict)
            or (prior.get("critic_provenance") or {}).get("attempt") != 7
            or (prior.get("summary") or {}).get("passed") is not False
            or set(prior.get("issue_codes") or ()) != {
                "STORY_COMPREHENSION_FAIL", "CAUSAL_CHAIN_BROKEN", "CLIMAX_PAYOFF_WEAK"
            }):
        raise RuntimeError("requires immutable failed independent Story Review #7")
    review_sha = review_authority_sha256(ep)
    contract = character_contract.load(ep) or {}
    revision = contract.get("source_revision") or {}
    story, board = story_paths(ep)
    story_sha = sha256_file(story)
    board_sha = sha256_file(board)
    captions = ep / "docs/subtitles.yaml"
    if (not captions.is_file()
            or revision.get("scope") != "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAILED_A7"
            or revision.get("previous_review_authority_sha256") != review_sha
            or revision.get("previous_story_sha256") != prior.get("story_sha256")
            or revision.get("story_sha256") != story_sha
            or revision.get("storyboard_sha256") != board_sha
            or revision.get("subtitle_sha256") != sha256_file(captions)
            or prior.get("story_sha256") == story_sha
            or prior.get("storyboard_sha256") == board_sha
            or character_contract.validate(ep, require_locked=True)):
        raise RuntimeError("frozen Character/Story source revision SHA or lock invalid")
    declared = (read_json(ep / "meta/release-manifest.json").get("release") or {}).get("body_frame_count")
    if (not isinstance(declared, int) or declared < 1
            or sorted(parse_simple_subtitles_yaml(captions).get("frames") or {})
                != list(range(1, declared + 1))):
        raise RuntimeError("source repair captions do not match every declared frame")
    authority_sha = character_contract.authority_sha256(ep)
    if not authority_sha:
        raise RuntimeError("revised Character Contract authority missing")
    binding = {
        "schema": "storyos.story_critic_character_source_revision.v1",
        "authorization": "direct_user_continuation",
        "review_scope": "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAIL",
        "global_review_attempt": 8,
        "review_epoch": 7,
        "epoch_attempt": 1,
        "previous_review_sha256": review_sha,
        "previous_story_sha256": prior["story_sha256"],
        "previous_storyboard_sha256": prior["storyboard_sha256"],
        "story_sha256": story_sha,
        "storyboard_sha256": board_sha,
        "subtitle_source_sha256": sha256_file(captions),
        "new_character_authority_sha256": authority_sha,
        "character_attestation_sha256": revision["attestation_sha256"],
        "current_rubric_sha256": _review_rubric_digest(
            Path(__file__).read_text(encoding="utf-8-sig")
        ),
        "reason": "Real content repair after immutable failed Story Review #7",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, binding)
    return binding


def _authorize_concept_selection_source_revision(ep: Path, *, attempt: int) -> dict:
    """Authorize one independent Story review after verified concept selection rewrites source."""
    if attempt != 3:
        raise RuntimeError("concept-selection source revision is only attempt 3")
    target = ep / "meta/runtime/story-review-concept-selection-source-revision-a3.json"
    if target.exists():
        raise RuntimeError("concept-selection source revision #3 already authorized; no redispatch")
    import concept_ambition
    errors = concept_ambition.verify(ep)
    if errors:
        raise RuntimeError("Concept Ambition must verify first: " + "; ".join(errors[:5]))
    concept_review_path = ep / concept_ambition.REVIEW_REL
    concept_review = read_json(concept_review_path)
    candidates_path = ep / concept_ambition.CANDIDATES_REL
    if not candidates_path.is_file():
        raise RuntimeError("verified Concept Ambition candidate pool missing")
    selected_id = str(concept_review.get("selected_id") or "")
    selected = next((row for row in concept_review.get("candidates", [])
                     if isinstance(row, dict) and row.get("id") == selected_id), None)
    if not selected:
        raise RuntimeError("verified selected concept is missing")
    previous = load_review(ep)
    if (not isinstance(previous, dict)
            or (previous.get("critic_provenance") or {}).get("attempt") != 2
            or (previous.get("summary") or {}).get("passed") is not True):
        raise RuntimeError("requires preserved Story Critic #2 PASS for the previous source")
    story, board = story_paths(ep)
    captions = ep / "docs/subtitles.yaml"
    if not captions.is_file():
        raise RuntimeError("current authored subtitles are required")
    story_sha, board_sha = sha256_file(story), sha256_file(board)
    if story_sha == previous.get("story_sha256") or board_sha == previous.get("storyboard_sha256"):
        raise RuntimeError("both story and storyboard must change from the previously reviewed source")
    previous_review_sha = review_authority_sha256(ep)
    if not previous_review_sha:
        raise RuntimeError("previous immutable Story Review Authority SHA missing")
    binding = {
        "schema": "storyos.story_critic_concept_selection_source_revision.v1",
        "authorization": "direct_user_continuation",
        "review_scope": "CONCEPT_SELECTION_SOURCE_REVISION",
        "global_review_attempt": 3,
        "review_epoch": 2,
        "epoch_attempt": 1,
        "previous_review_attempt": 2,
        "previous_review_passed": True,
        "previous_review_sha256": previous_review_sha,
        "previous_story_sha256": previous.get("story_sha256"),
        "previous_storyboard_sha256": previous.get("storyboard_sha256"),
        "story_sha256": story_sha,
        "storyboard_sha256": board_sha,
        "subtitle_source_sha256": sha256_file(captions),
        "concept_candidates_sha256": sha256_file(candidates_path),
        "concept_review_sha256": sha256_file(concept_review_path),
        "selected_id": selected_id,
        "selected_title": selected.get("title"),
        "current_rubric_sha256": _review_rubric_digest(
            Path(__file__).read_text(encoding="utf-8-sig")
        ),
        "reason": "Direct user authorization to review the rewritten source selected by verified Concept Ambition",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, binding)
    return binding


def _authorize_concept_selection_source_repair_after_fail(ep: Path, *, attempt: int) -> dict:
    """Authorize exactly one fresh Story review after repairing concept-selected source post-FAIL."""
    if attempt != 4:
        raise RuntimeError("concept-selection source repair after FAIL is only attempt 4")
    target = ep / "meta/runtime/story-review-concept-selection-source-repair-after-fail-a4.json"
    if target.exists():
        raise RuntimeError("concept-selection source repair #4 already authorized; no redispatch")
    import concept_ambition
    errors = concept_ambition.verify(ep)
    if errors:
        raise RuntimeError("Concept Ambition must still verify: " + "; ".join(errors[:5]))
    previous = review_record_persistence.load_attempt(
        Path(ep).resolve(), REVIEW_TYPE, 3, legacy_path=Path(ep) / REVIEW_REL
    )
    prior_manifest_path = ep / "meta/runtime/story-review-concept-selection-source-revision-a3.json"
    if not prior_manifest_path.is_file():
        raise RuntimeError("the consumed attempt 3 SHA authority is missing")
    prior_manifest = read_json(prior_manifest_path)
    if (not isinstance(previous, dict)
            or (previous.get("critic_provenance") or {}).get("attempt") != 3
            or (previous.get("critic_provenance") or {}).get("review_scope") != "CONCEPT_SELECTION_SOURCE_REVISION"
            or (previous.get("summary") or {}).get("passed") is not False):
        raise RuntimeError("requires the immutable failed Concept Selection Story Review #3")
    previous_digest = review_record_persistence._payload_content_sha(previous)
    if (prior_manifest.get("global_review_attempt") != 3
            or prior_manifest.get("previous_review_sha256") != (previous.get("critic_provenance") or {}).get("previous_review_sha256")
            or prior_manifest.get("story_sha256") != previous.get("story_sha256")
            or prior_manifest.get("storyboard_sha256") != previous.get("storyboard_sha256")):
        raise RuntimeError("attempt 3 source authority does not match its preserved Review record")
    story, board = story_paths(ep)
    captions = ep / "docs/subtitles.yaml"
    if not captions.is_file():
        raise RuntimeError("current authored subtitles are required")
    story_sha, board_sha = sha256_file(story), sha256_file(board)
    if (story_sha == previous.get("story_sha256")
            or board_sha == previous.get("storyboard_sha256")
            or sha256_file(captions) == previous.get("subtitle_source_sha256")):
        raise RuntimeError("story, storyboard and subtitles must all be revised after failed attempt 3")
    concept_review_path = ep / concept_ambition.REVIEW_REL
    candidates_path = ep / concept_ambition.CANDIDATES_REL
    concept_review = read_json(concept_review_path)
    selected_id = str(concept_review.get("selected_id") or "")
    selected = next((row for row in concept_review.get("candidates", [])
                     if isinstance(row, dict) and row.get("id") == selected_id), None)
    if not selected:
        raise RuntimeError("verified selected concept is missing")
    binding = {
        "schema": "storyos.story_critic_concept_selection_source_repair_after_fail.v1",
        "authorization": "direct_user_continuation",
        "review_scope": "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL",
        "global_review_attempt": 4,
        "review_epoch": 3,
        "epoch_attempt": 1,
        "previous_review_attempt": 3,
        "previous_review_passed": False,
        "previous_review_sha256": previous_digest,
        "previous_issue_codes": list(previous.get("issue_codes") or []),
        "previous_story_sha256": previous.get("story_sha256"),
        "previous_storyboard_sha256": previous.get("storyboard_sha256"),
        "story_sha256": story_sha,
        "storyboard_sha256": board_sha,
        "subtitle_source_sha256": sha256_file(captions),
        "concept_candidates_sha256": sha256_file(candidates_path),
        "concept_review_sha256": sha256_file(concept_review_path),
        "selected_id": selected_id,
        "selected_title": selected.get("title"),
        "current_rubric_sha256": _review_rubric_digest(
            Path(__file__).read_text(encoding="utf-8-sig")
        ),
        "reason": "Direct user request to progress after revising the source following independent Story Review #3 FAIL",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, binding)
    return binding


def _authorize_concept_selection_source_repair_after_fail_a5(ep: Path, *, attempt: int) -> dict:
    """Authorize one fresh source-SHA-bound Story review after the repaired attempt 4 still failed."""
    if attempt != 5:
        raise RuntimeError("concept-selection source repair after FAIL is only attempt 5")
    target = ep / "meta/runtime/story-review-concept-selection-source-repair-after-fail-a5.json"
    if target.exists():
        raise RuntimeError("concept-selection source repair #5 already authorized; no redispatch")
    import concept_ambition
    errors = concept_ambition.verify(ep)
    if errors:
        raise RuntimeError("Concept Ambition must still verify: " + "; ".join(errors[:5]))
    previous = review_record_persistence.load_attempt(
        Path(ep).resolve(), REVIEW_TYPE, 4, legacy_path=Path(ep) / REVIEW_REL
    )
    prior_manifest_path = ep / "meta/runtime/story-review-concept-selection-source-repair-after-fail-a4.json"
    if not prior_manifest_path.is_file():
        raise RuntimeError("the consumed attempt 4 SHA authority is missing")
    prior_manifest = read_json(prior_manifest_path)
    previous_provenance = (previous or {}).get("critic_provenance") or {}
    if (not isinstance(previous, dict)
            or previous_provenance.get("attempt") != 4
            or previous_provenance.get("review_scope") != "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL"
            or (previous.get("summary") or {}).get("passed") is not False):
        raise RuntimeError("requires the immutable failed Concept Selection Story Review #4")
    previous_digest = review_record_persistence._payload_content_sha(previous)
    attempt3 = review_record_persistence.load_attempt(
        Path(ep).resolve(), REVIEW_TYPE, 3, legacy_path=Path(ep) / REVIEW_REL
    )
    attempt3_provenance = (attempt3 or {}).get("critic_provenance") or {}
    attempt3_digest = (review_record_persistence._payload_content_sha(attempt3)
                       if isinstance(attempt3, dict) else None)
    if (prior_manifest.get("global_review_attempt") != 4
            or prior_manifest.get("review_scope") != previous_provenance.get("review_scope")
            or prior_manifest.get("previous_review_sha256") != previous_provenance.get("previous_review_sha256")
            or prior_manifest.get("current_rubric_sha256") != previous_provenance.get("current_rubric_sha256")
            or prior_manifest.get("story_sha256") != previous.get("story_sha256")
            or prior_manifest.get("storyboard_sha256") != previous.get("storyboard_sha256")
            or prior_manifest.get("subtitle_source_sha256") != previous.get("subtitle_source_sha256")
            or not isinstance(attempt3, dict)
            or attempt3_provenance.get("attempt") != 3
            or (attempt3.get("summary") or {}).get("passed") is not False
            or attempt3_digest != prior_manifest.get("previous_review_sha256")
            or attempt3.get("story_sha256") != prior_manifest.get("previous_story_sha256")
            or attempt3.get("storyboard_sha256") != prior_manifest.get("previous_storyboard_sha256")
            or attempt3.get("issue_codes") != prior_manifest.get("previous_issue_codes")):
        raise RuntimeError("attempt 4 source authority does not match its preserved Review record")
    story, board = story_paths(ep)
    captions = ep / "docs/subtitles.yaml"
    if not captions.is_file():
        raise RuntimeError("current authored subtitles are required")
    story_sha, board_sha, captions_sha = sha256_file(story), sha256_file(board), sha256_file(captions)
    if (story_sha == previous.get("story_sha256")
            or board_sha == previous.get("storyboard_sha256")
            or captions_sha == previous.get("subtitle_source_sha256")):
        raise RuntimeError("story, storyboard and subtitles must all be revised after failed attempt 4")
    concept_review_path = ep / concept_ambition.REVIEW_REL
    candidates_path = ep / concept_ambition.CANDIDATES_REL
    concept_review = read_json(concept_review_path)
    selected_id = str(concept_review.get("selected_id") or "")
    selected = next((row for row in concept_review.get("candidates", [])
                     if isinstance(row, dict) and row.get("id") == selected_id), None)
    if not selected:
        raise RuntimeError("verified selected concept is missing")
    binding = {
        "schema": "storyos.story_critic_concept_selection_source_repair_after_fail_a5.v1",
        "authorization": "direct_user_continuation",
        "review_scope": "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL_A5",
        "global_review_attempt": 5,
        "review_epoch": 4,
        "epoch_attempt": 1,
        "previous_review_attempt": 4,
        "previous_review_passed": False,
        "previous_review_sha256": previous_digest,
        "previous_issue_codes": list(previous.get("issue_codes") or []),
        "previous_story_sha256": previous.get("story_sha256"),
        "previous_storyboard_sha256": previous.get("storyboard_sha256"),
        "story_sha256": story_sha,
        "storyboard_sha256": board_sha,
        "subtitle_source_sha256": captions_sha,
        "concept_candidates_sha256": sha256_file(candidates_path),
        "concept_review_sha256": sha256_file(concept_review_path),
        "selected_id": selected_id,
        "selected_title": selected.get("title"),
        "current_rubric_sha256": _review_rubric_digest(
            Path(__file__).read_text(encoding="utf-8-sig")
        ),
        "reason": "Direct user request to progress after repairing the current story following independent Story Review #4 FAIL",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, binding)
    return binding


# Shared verbatim with the A9 read-only durable receipt reconciler. Never
# mint another paid attempt merely to recover a lost subprocess return value.
DIRECT_CODEX_EXECUTION_OVERRIDE = "\n\nDIRECT CODEX EXECUTION OVERRIDE:\nDo not edit or write any repository file in this execution.\nReturn ONLY the exact candidate JSON object as your final answer, with no prose,\nno Markdown fences and no status summary. The parent process persists it.\n"


def critic_sandbox(*, migrated_rubric: bool) -> str:
    """A9 is a source-reading critic, never a repository-writing agent.

    On Windows, codex_critic_runner.resolve_sandbox("workspace-write")
    expands to danger-full-access. Explicit "read-only" does not.
    """
    return "read-only" if migrated_rubric else "workspace-write"


def run_critic(ep: Path, *, attempt: int, codex_raw: str | None, timeout: int | None = None, direct_user_continuation: bool = False, prior_rubric_ref: str | None = None, direct_user_source_revision: bool = False, direct_user_symbolic_remediation: bool = False, direct_user_paired_caption: bool = False, direct_user_photo_text_repair: bool = False, direct_user_character_source_repair: bool = False, direct_user_concept_selection_source_revision: bool = False, direct_user_concept_selection_source_repair_after_fail: bool = False, direct_user_concept_selection_source_repair_after_fail_a5: bool = False, direct_user_migrated_rubric: bool = False, direct_user_a10_source_revision: bool = False) -> int:
    if timeout is None:
        timeout = runtime_timeout_policy.seconds("review_critic")
    if attempt not in {1, 2} and not (attempt == 3 and direct_user_continuation) and not (attempt == 3 and direct_user_concept_selection_source_revision) and not (attempt == 4 and direct_user_concept_selection_source_repair_after_fail) and not (attempt == 5 and direct_user_concept_selection_source_repair_after_fail_a5) and not (attempt == 4 and direct_user_source_revision) and not (attempt == 5 and direct_user_symbolic_remediation) and not (attempt == 6 and direct_user_paired_caption) and not (attempt == 7 and direct_user_photo_text_repair) and not (attempt == 8 and direct_user_character_source_repair) and not (attempt == 9 and direct_user_migrated_rubric) and not (attempt == 10 and direct_user_a10_source_revision):
        raise RuntimeError("attempts above 2 require explicit direct-user, SHA-bound continuation")
    if direct_user_continuation and (attempt != 3 or direct_user_source_revision):
        raise RuntimeError("policy continuation is only attempt 3")
    if direct_user_source_revision and (attempt != 4 or direct_user_continuation or direct_user_symbolic_remediation):
        raise RuntimeError("source revision is only attempt 4")
    if direct_user_symbolic_remediation and (attempt != 5 or direct_user_continuation or direct_user_source_revision or direct_user_paired_caption):
        raise RuntimeError("symbolic remediation is only attempt 5")
    if direct_user_paired_caption and (attempt != 6 or direct_user_continuation or direct_user_source_revision or direct_user_symbolic_remediation):
        raise RuntimeError("paired caption continuation is only attempt 6")
    if direct_user_photo_text_repair and (
        attempt != 7 or direct_user_continuation or direct_user_source_revision
        or direct_user_symbolic_remediation or direct_user_paired_caption
    ):
        raise RuntimeError("photo-text source repair is only attempt 7")
    if direct_user_character_source_repair and (
        attempt != 8 or direct_user_continuation or direct_user_source_revision
        or direct_user_symbolic_remediation or direct_user_paired_caption
        or direct_user_photo_text_repair
    ):
        raise RuntimeError("Character story source repair is only attempt 8")
    if direct_user_concept_selection_source_revision and (
        attempt != 3 or direct_user_continuation or direct_user_source_revision
        or direct_user_symbolic_remediation or direct_user_paired_caption
        or direct_user_photo_text_repair or direct_user_character_source_repair
    ):
        raise RuntimeError("concept-selection source revision is only attempt 3")
    if direct_user_concept_selection_source_repair_after_fail and (
        attempt != 4 or direct_user_continuation or direct_user_source_revision
        or direct_user_symbolic_remediation or direct_user_paired_caption
        or direct_user_photo_text_repair or direct_user_character_source_repair
        or direct_user_concept_selection_source_revision
    ):
        raise RuntimeError("concept-selection source repair after FAIL is only attempt 4")
    if direct_user_concept_selection_source_repair_after_fail_a5 and (
        attempt != 5 or direct_user_continuation or direct_user_source_revision
        or direct_user_symbolic_remediation or direct_user_paired_caption
        or direct_user_photo_text_repair or direct_user_character_source_repair
        or direct_user_concept_selection_source_revision
        or direct_user_concept_selection_source_repair_after_fail
    ):
        raise RuntimeError("concept-selection source repair after FAIL is only attempt 5")
    if direct_user_migrated_rubric or direct_user_a10_source_revision:
        # This is the REAL text Provider path. The standalone read-only audit
        # is not sufficient; repeat all MySQL/Attempt/Driver/native CLI checks
        # inside the paid entrypoint, before reserving the one-shot epoch.
        script_path=str(ROOT/"scripts")
        if script_path not in sys.path:
            sys.path.insert(0,script_path)
        import storyos_autonomy_r12_critic_preflight as native_recheck
        review_ref=Path(ep).resolve().relative_to(ROOT.resolve()).as_posix()
        readiness=(native_recheck.inspect(
            review_ref,source_revision_after_a9=True)
            if direct_user_a10_source_revision else
            native_recheck.inspect(review_ref))
        if readiness.get("may_start_new_text_review") is not True:
            raise RuntimeError("native migrated rubric Critic denied: "+
                               str(readiness.get("status") or "UNVERIFIED"))
    if direct_user_migrated_rubric and (attempt!=9 or any((
        direct_user_continuation,direct_user_source_revision,
        direct_user_symbolic_remediation,direct_user_paired_caption,
        direct_user_photo_text_repair,direct_user_character_source_repair,
        direct_user_concept_selection_source_revision,
        direct_user_concept_selection_source_repair_after_fail,
        direct_user_concept_selection_source_repair_after_fail_a5))):
        raise RuntimeError("migrated rubric revalidation is exclusive attempt 9")
    if direct_user_a10_source_revision and (
        attempt != 10 or direct_user_migrated_rubric
        or any((direct_user_continuation,direct_user_source_revision,
                direct_user_symbolic_remediation,direct_user_paired_caption,
                direct_user_photo_text_repair,direct_user_character_source_repair,
                direct_user_concept_selection_source_revision,
                direct_user_concept_selection_source_repair_after_fail,
                direct_user_concept_selection_source_repair_after_fail_a5))):
        raise RuntimeError("independent A10 source review is exclusive attempt 10")
    # A nonexistent native executable must never burn the irreversible A9
    # reservation. Only the actual paid dispatch is allowed to consume it.
    prevalidated_codex = (resolve_codex(codex_raw) if
                           (direct_user_migrated_rubric or direct_user_a10_source_revision)
                           else None)
    prevalidated_prompt = None
    if direct_user_migrated_rubric or direct_user_a10_source_revision:
        # Finish every local, free, deterministic input check BEFORE writing
        # the exclusive, non-retryable paid text Critic reservation.
        check_story, check_board = story_paths(ep)
        if not check_story.is_file() or not check_board.is_file():
            raise RuntimeError("migrated rubric Critic source files missing")
        candidate_rel = (story_review_a10_source_revision.CANDIDATE_REL
                         if direct_user_a10_source_revision else CANDIDATE_REL)
        if (ep / candidate_rel).exists():
            if direct_user_a10_source_revision:
                raise RuntimeError("A10 candidate already exists: reconcile first")
            raise RuntimeError("migrated rubric candidate already exists: reconcile first")
        if _locked_documentary_rubric(ep) and not (ep / "docs/subtitles.yaml").is_file():
            raise RuntimeError("migrated rubric critic requires locked subtitles")
        prevalidated_prompt = critic_prompt(
            ep, check_story, check_board, ep / candidate_rel, attempt)
    continuation = (_authorize_policy_continuation(ep, attempt=attempt, prior_rubric_ref=prior_rubric_ref)
                    if direct_user_continuation else _authorize_source_revision(ep, attempt=attempt)
                    if direct_user_source_revision else _authorize_symbolic_remediation(ep, attempt=attempt)
                    if direct_user_symbolic_remediation else _authorize_paired_caption_revision(ep, attempt=attempt)
                    if direct_user_paired_caption else _authorize_photo_text_source_repair(ep, attempt=attempt)
                    if direct_user_photo_text_repair else _authorize_character_source_repair(ep, attempt=attempt)
                    if direct_user_character_source_repair else _authorize_concept_selection_source_revision(ep, attempt=attempt)
                    if direct_user_concept_selection_source_revision else _authorize_concept_selection_source_repair_after_fail(ep, attempt=attempt)
                    if direct_user_concept_selection_source_repair_after_fail else _authorize_concept_selection_source_repair_after_fail_a5(ep, attempt=attempt)
                    if direct_user_concept_selection_source_repair_after_fail_a5 else
                    story_review_rubric_migration.authorize(
                        ep, attempt=attempt,
                        current_rubric_sha256=_review_rubric_digest(
                            Path(__file__).read_text(encoding="utf-8-sig")))
                    if direct_user_migrated_rubric else
                    story_review_a10_source_revision.authorize(
                        ep, attempt=attempt,
                        current_rubric_sha256=_review_rubric_digest(
                            Path(__file__).read_text(encoding="utf-8-sig")))
                    if direct_user_a10_source_revision else None)
    story, storyboard = story_paths(ep)
    before_story = sha256_file(story)
    before_board = sha256_file(storyboard)
    candidate = ep / (story_review_a10_source_revision.CANDIDATE_REL
                      if direct_user_a10_source_revision else CANDIDATE_REL)
    captions = ep / "docs/subtitles.yaml"
    if _locked_documentary_rubric(ep) and not captions.is_file():
        raise RuntimeError("locked photo-text story requires frame-by-frame subtitles")
    before_captions = sha256_file(captions) if captions.is_file() else None
    if not direct_user_a10_source_revision:
        candidate.unlink(missing_ok=True)

    runtime, _ = runtime_router.detect()
    if runtime in {"WORK", "WEB"} and not codex_raw:
        sources = [
            story,
            storyboard,
            ROOT / "standards/制作规范_正式版.md",
            ROOT / "standards/创作执行强制规范_V2.0.3.2.md",
            ROOT / "standards/story_regressions/cases.json",
            ROOT / "standards/传播核与动作回应链规范_V1.0.md",
        ]
        request = product_review_adapter.prepare(
            ep,
            kind="story-semantic",
            runtime=runtime,
            attempt=attempt,
            prompt=critic_prompt(ep, story, storyboard, candidate, attempt),
            source_paths=sources,
            candidate_path=candidate,
        )
        shadow_schedule = {"enabled": False, "scheduled": False}
        try:
            shadow_schedule = schedule_critic_shadow(
                ep, attempt=attempt, story=story, storyboard=storyboard, sources=sources,
                canonical_source_files=request.get("source_files"),
            )
        except Exception as exc:
            # Shadow scheduling is observable but cannot change the canonical
            # Story Review decision or candidate lifecycle.
            shadow_schedule["error"] = f"{type(exc).__name__}: {exc}"
        request["critic_shadow_schedule"] = shadow_schedule
        print(json.dumps(request, ensure_ascii=False, indent=2))
        return product_review_adapter.HOST_ACTION_REQUIRED_RC

    codex = prevalidated_codex or resolve_codex(codex_raw)
    log = ep / "meta" / f"story-critic-attempt-{attempt}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    direct_prompt = (prevalidated_prompt if
                     (direct_user_migrated_rubric or direct_user_a10_source_revision) else
                     critic_prompt(ep, story, storyboard, candidate, attempt)) + DIRECT_CODEX_EXECUTION_OVERRIDE
    completed = codex_critic_runner.launch(
        direct_prompt,
        codex=codex,
        root=ROOT,
        timeout=timeout,
        output_path=candidate,
        reasoning_effort="high",
        sandbox=critic_sandbox(migrated_rubric=(
            direct_user_migrated_rubric or direct_user_a10_source_revision)),
        log_path=log,
        # A long-lived interactive Windows runner can have stale arg0 ACLs
        # beneath ~/.codex; the independent Story critic must start in its
        # own authenticated, runner-owned home like the Concept critic.
        # Keep source SHA, review validation and immutable authority intact.
        codex_home_mode="isolated",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"isolated story critic failed rc={completed.returncode}; log={log}")
    if sha256_file(story) != before_story or sha256_file(storyboard) != before_board:
        raise RuntimeError("critic modified story/storyboard; isolated review is invalid")
    if before_captions is not None and (not captions.is_file() or sha256_file(captions) != before_captions):
        raise RuntimeError("critic input subtitles were modified; isolated review is invalid")
    if not candidate.is_file():
        raise RuntimeError(f"critic did not produce {candidate}")

    data = read_json(candidate)
    provenance = runtime_provenance.build_critic_provenance(
        "CODEX", attempt=attempt, log=log.relative_to(ROOT).as_posix(),
        allow_user_continuation_attempt=bool(continuation),
    )
    if continuation:
        provenance.update({
            "review_scope": continuation["review_scope"],
            "review_epoch": continuation["review_epoch"],
            "epoch_attempt": continuation["epoch_attempt"],
            "previous_review_sha256": continuation["previous_review_sha256"],
            "current_rubric_sha256": continuation["current_rubric_sha256"],
        })
        if continuation.get("review_scope") in {
            "CONCEPT_SELECTION_SOURCE_REVISION",
            "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL",
            "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL_A5",
        }:
            provenance.update({
                "previous_story_sha256": continuation["previous_story_sha256"],
                "previous_storyboard_sha256": continuation["previous_storyboard_sha256"],
                "concept_candidates_sha256": continuation["concept_candidates_sha256"],
                "concept_review_sha256": continuation["concept_review_sha256"],
                "selected_concept_id": continuation["selected_id"],
            })
        for key in ("previous_rubric_sha256", "previous_storyboard_sha256",
                    "previous_story_sha256", "new_character_authority_sha256",
                    "character_attestation_sha256", "previous_review_request_sha256",
                    "previous_review_request_id", "previous_standard_sha256",
                    "current_standard_sha256","previous_a9_ticket_sha256",
                    "previous_a9_candidate_sha256","subtitle_source_sha256"):
            if key in continuation:
                provenance[key] = continuation[key]
    if before_captions:
        provenance["subtitle_source_sha256"] = before_captions
    return _finalize_review(
        ep,
        data,
        attempt=attempt,
        before_story=before_story,
        before_board=before_board,
        provenance=provenance,
    )


def project_verified_story_gate(ep: Path) -> dict:
    """Project only a genuinely verified, SHA-bound independent Story Critic PASS."""
    ep = Path(ep).resolve()
    failures = verify(ep)
    if failures:
        raise ValueError("cannot project invalid Story Critic: " + "; ".join(failures[:8]))
    result = load_review(ep)
    if not isinstance(result, dict) or (result.get("summary") or {}).get("passed") is not True:
        raise ValueError("cannot project Story Critic without real summary PASS")
    authority_sha = review_authority_sha256(ep)
    if not authority_sha:
        raise ValueError("cannot project Story Critic without durable Review Authority SHA")
    story, storyboard = story_paths(ep)
    if (result.get("story_sha256") != sha256_file(story)
            or result.get("storyboard_sha256") != sha256_file(storyboard)):
        raise ValueError("cannot project Story Critic when source SHA differs")
    path = ep / "meta/story-gates.json"
    gates = read_json(path)
    reviews = gates.get("reviews")
    if not isinstance(reviews, dict) or reviews.get("story") not in {"pending", "passed"}:
        raise ValueError("review story gate projection state is not admissible")
    binding = {
        "authority_sha256": authority_sha,
        "story_sha256": sha256_file(story),
        "storyboard_sha256": sha256_file(storyboard),
        "attempt": (result.get("critic_provenance") or {}).get("attempt"),
        "review_scope": (result.get("critic_provenance") or {}).get("review_scope", "STANDARD"),
    }
    old_binding = (gates.get("review_authority_bindings") or {}).get("story")
    if reviews.get("story") == "passed" and old_binding != binding:
        provenance = result.get("critic_provenance") or {}
        scope = provenance.get("review_scope")
        # A historical Story PASS had no bound SHA. Only the newly
        # verified, independent A10 may replace that legacy projection.
        if (scope == story_review_a10_source_revision.REVIEW_SCOPE
                and old_binding is None
                and story_review_a10_source_revision.validate_epoch(ep,provenance)):
            gates.setdefault("review_authority_bindings",{})["story"]=binding
            reviews["story"]="passed"
            write_json(path,gates)
            return binding

        if scope == "CONCEPT_SELECTION_SOURCE_REVISION":
            continuation_path = ep / "meta/runtime/story-review-concept-selection-source-revision-a3.json"
            expected_previous = {
                "attempt": 2,
                "review_scope": "STANDARD",
            }
        elif scope == "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL":
            continuation_path = ep / "meta/runtime/story-review-concept-selection-source-repair-after-fail-a4.json"
            chain_path = ep / "meta/runtime/story-review-concept-selection-source-revision-a3.json"
            if not chain_path.is_file():
                raise ValueError("attempt 4 continuation is missing its authorized attempt 3 predecessor")
            chain = read_json(chain_path)
            expected_previous = {
                "authority_sha256": chain.get("previous_review_sha256"),
                "story_sha256": chain.get("previous_story_sha256"),
                "storyboard_sha256": chain.get("previous_storyboard_sha256"),
                "attempt": 2,
                "review_scope": "STANDARD",
            }
        elif scope == "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL_A5":
            continuation_path = ep / "meta/runtime/story-review-concept-selection-source-repair-after-fail-a5.json"
            chain_path = ep / "meta/runtime/story-review-concept-selection-source-revision-a3.json"
            if not chain_path.is_file():
                raise ValueError("attempt 5 continuation is missing its authorized concept-selection predecessor")
            chain = read_json(chain_path)
            expected_previous = {
                "authority_sha256": chain.get("previous_review_sha256"),
                "story_sha256": chain.get("previous_story_sha256"),
                "storyboard_sha256": chain.get("previous_storyboard_sha256"),
                "attempt": 2,
                "review_scope": "STANDARD",
            }
        else:
            continuation_path = None
            expected_previous = None
        if continuation_path is None or not continuation_path.is_file():
            raise ValueError("existing Story Gate PASS binding drift")
        continuation = read_json(continuation_path)
        if scope == "CONCEPT_SELECTION_SOURCE_REVISION":
            expected_previous = {
                "authority_sha256": continuation.get("previous_review_sha256"),
                "story_sha256": continuation.get("previous_story_sha256"),
                "storyboard_sha256": continuation.get("previous_storyboard_sha256"),
                **expected_previous,
            }
        if old_binding != expected_previous:
            raise ValueError("previous Story Gate PASS does not match the authorized predecessor")
        gates.setdefault("review_authority_bindings", {})["story"] = binding
        reviews["story"] = "passed"
        write_json(path, gates)
        return binding
    if reviews.get("story") == "passed":
        return binding
    gates.setdefault("review_authority_bindings", {})["story"] = binding
    reviews["story"] = "passed"
    write_json(path, gates)
    return binding


def self_test() -> None:
    h = "a" * 64
    data = {
        "schema_version": 1,
        "story_os_version": story_os_version(),
        "story_sha256": h,
        "storyboard_sha256": h,
        "revision_count": 0,
        "critic_provenance": {"runtime": "CODEX_ISOLATED", "isolated_session": True, "attempt": 1},
        "contract": {key: "x" for key in CONTRACT_FIELDS},
        "blind_retell": {key: "x" for key in BLIND_FIELDS},
        "hard_checks": {key: True for key in HARD_CHECKS},
        "issue_codes": [],
        "summary": {"passed": True},
    }
    data["contract"]["ending_recontextualization"] = ["a", "b", "c"]
    assert validate_payload(data, story_sha=h, storyboard_sha=h, version=story_os_version()) == []
    data["hard_checks"]["mechanism_consistency"] = False
    assert any("mechanism_consistency" in x for x in validate_payload(data, story_sha=h, storyboard_sha=h, version=story_os_version()))
    old=propagation_core_gate.anomaly_applicable
    propagation_core_gate.anomaly_applicable=lambda _ep:False
    try:
        prompt=critic_prompt(ROOT,ROOT/"dummy-story.md",ROOT/"dummy-board.md",ROOT/"dummy-candidate.json",1)
        assert "ORDINARY-LIFE OVERRIDE" in prompt
        assert "Do NOT invent horror" in prompt
        assert "propagation_core is NOT required" in prompt
    finally:
        propagation_core_gate.anomaly_applicable=old
    print("STORY SEMANTIC REVIEW SELF-TEST PASS")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run-critic")
    p.add_argument("episode_dir")
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--codex")
    p.add_argument("--timeout", type=int, default=None)
    p.add_argument("--direct-user-continuation", action="store_true")
    p.add_argument("--direct-user-source-revision", action="store_true")
    p.add_argument("--direct-user-symbolic-remediation", action="store_true")
    p.add_argument("--direct-user-paired-caption", action="store_true")
    p.add_argument("--direct-user-photo-text-repair", action="store_true")
    p.add_argument("--direct-user-character-source-repair", action="store_true")
    p.add_argument("--direct-user-concept-selection-source-revision", action="store_true")
    p.add_argument("--direct-user-concept-selection-source-repair-after-fail", action="store_true")
    p.add_argument("--direct-user-concept-selection-source-repair-after-fail-a5", action="store_true")
    p.add_argument("--direct-user-migrated-rubric", action="store_true")
    p.add_argument("--direct-user-a10-source-revision", action="store_true")
    p.add_argument("--prior-rubric-ref")
    p = sub.add_parser("finalize-review")
    p.add_argument("episode_dir")
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--runtime", choices=["WORK", "WEB"], default="WORK")
    p = sub.add_parser("project-verified-gate")
    p.add_argument("episode_dir")
    p = sub.add_parser("verify")
    p.add_argument("episode_dir")
    p = sub.add_parser("show")
    p.add_argument("episode_dir")
    sub.add_parser("self-test")
    args = ap.parse_args()

    if args.cmd == "self-test":
        self_test()
        return 0
    ep = Path(args.episode_dir).resolve()
    if not ep.is_dir():
        raise SystemExit(f"episode directory not found: {ep}")
    if args.cmd == "run-critic":
        try:
            return run_critic(ep, attempt=args.attempt, codex_raw=args.codex, timeout=args.timeout,
                              direct_user_continuation=args.direct_user_continuation,
                              prior_rubric_ref=args.prior_rubric_ref,
                              direct_user_source_revision=args.direct_user_source_revision,
                              direct_user_symbolic_remediation=args.direct_user_symbolic_remediation,
                              direct_user_paired_caption=args.direct_user_paired_caption,
                              direct_user_photo_text_repair=args.direct_user_photo_text_repair,
                              direct_user_character_source_repair=args.direct_user_character_source_repair,
                              direct_user_concept_selection_source_revision=args.direct_user_concept_selection_source_revision,
                              direct_user_concept_selection_source_repair_after_fail=args.direct_user_concept_selection_source_repair_after_fail,
                              direct_user_concept_selection_source_repair_after_fail_a5=args.direct_user_concept_selection_source_repair_after_fail_a5,
                              direct_user_migrated_rubric=args.direct_user_migrated_rubric,
                              direct_user_a10_source_revision=args.direct_user_a10_source_revision)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print("STORY SEMANTIC REVIEW ERROR:", exc)
            return 3
    if args.cmd == "finalize-review":
        try:
            return finalize_product_review(ep, attempt=args.attempt, runtime=args.runtime)
        except (OSError, RuntimeError, ValueError) as exc:
            print("STORY SEMANTIC REVIEW FINALIZE ERROR:", exc)
            return 3
    if args.cmd == "project-verified-gate":
        try:
            print(json.dumps(project_verified_story_gate(ep), ensure_ascii=False, indent=2))
            return 0
        except (OSError, RuntimeError, ValueError) as exc:
            print("STORY GATE PROJECTION REFUSED:", exc)
            return 3
    if args.cmd == "show":
        print(json.dumps(load_review(ep) or {}, ensure_ascii=False, indent=2))
        return 0
    errors = verify(ep)
    if errors:
        for error in errors:
            print("FAIL:", error)
        return 2
    print("STORY SEMANTIC REVIEW VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
