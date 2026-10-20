#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from episode_state import MANIFEST_FILE, STATE_FILE, GATES_FILE, STATES, SYSTEM_VERSION
import episode_state_persistence
from canvas_spec import resolve_canvas_spec
from concept_ambition import required as concept_ambition_required, verify as verify_concept_ambition
from propagation_core_gate import required as propagation_core_required, verify as verify_propagation_core  # STORY_OS_V2_5_PROPAGATION_CORE
from environment_contract import required as environment_contract_required, verify as verify_environment_contract
from frame_contract import required as frame_contract_required, verify_all as verify_frame_contracts
from visual_lock_v21 import required as visual_lock_v21_required, verify as verify_visual_lock_v21
from fast_frame_scout import required as fast_scout_required, audit as audit_fast_scout
from final_candidate_snapshot import required as final_snapshot_required, verify as verify_final_snapshot
from post_publish_review import REQUIRED_FOR_DATA_REVIEWED, required as post_publish_required, verify as verify_post_publish
from final_acceptance import allows as acceptance_allows, visual_asset_for_frame
import runtime_request
import story_narrative_form

STATE_MIN = {name: idx for idx, name in enumerate(STATES)}
PRODUCTION_DECISIONS = {"pending", "pass", "fail"}
PROPAGATION_DECISIONS = {"pending", "strong", "publishable", "conditional", "not_recommended"}
PUBLISH_DECISIONS = {"hold", "go"}
# Pre-V2.6 quality envelopes wrote placeholder values outside the canonical
# decision sets (example: IDEA_LOCKED drafts used production_gate=not_ready and
# omitted propagation_decision). They are only tolerated as WARN in the
# Git-metadata CI scan; full validation still requires migration before advance.
LEGACY_PRODUCTION_GATE_VALUES = {"not_ready", "NOT_READY"}
REVIEW_STATUSES = {"pending", "passed", "failed", "waived"}
LOCK_MODES = {"none", "subtitle_only", "crop_only", "regenerate_frame", "regenerate_sequence"}
WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass
class Finding:
    level: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.code}: {self.message}"


def load_json(path: Path, findings: list[Finding], *, required: bool = True) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            findings.append(Finding("FAIL", "invalid_json_root", f"{path}: top-level must be object"))
            return None
        return data
    except FileNotFoundError:
        if required:
            findings.append(Finding("FAIL", "missing_json", str(path)))
    except json.JSONDecodeError as e:
        findings.append(Finding("FAIL", "invalid_json", f"{path}: {e}"))
    return None


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def is_number_0_10(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and 0 <= float(value) <= 10


def resolve_repo_relative_path(repo_root: Path, value: object, findings: list[Finding], where: str) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    p = Path(raw)
    if p.is_absolute() or WINDOWS_DRIVE_RE.match(raw):
        findings.append(Finding("FAIL", "absolute_path", f"{where} must be repository-root relative: {raw}"))
        return None
    if "\\" in raw:
        findings.append(Finding("FAIL", "non_portable_path", f"{where} must use '/' separators: {raw}"))
        return None
    root = repo_root.resolve()
    resolved = (root / p).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        findings.append(Finding("FAIL", "path_outside_repo", f"{where} escapes repository root: {raw}"))
        return None
    return resolved


def require_string(obj: dict, key: str, findings: list[Finding], where: str) -> str | None:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        findings.append(Finding("FAIL", "required_field", f"{where}.{key} must be a non-empty string"))
        return None
    return value


def require_repo_path(repo_root: Path, obj: dict, key: str, findings: list[Finding], where: str, *, metadata_only: bool, asset_path: bool = False) -> Path | None:
    value = require_string(obj, key, findings, where)
    if value is None:
        return None
    p = resolve_repo_relative_path(repo_root, value, findings, f"{where}.{key}")
    if p is None:
        return None
    if metadata_only and asset_path:
        return p
    if not p.exists():
        findings.append(Finding("FAIL", "missing_path", f"{where}.{key}: {value}"))
    return p


def derive_propagation_decision(score: object, s_min: object) -> str | None:
    if not is_number_0_10(score) or not is_number_0_10(s_min):
        return None
    score = float(score)
    s_min = float(s_min)
    if score < 8.3 or s_min < 7.0:
        return "not_recommended"
    if score < 8.7 or s_min < 7.5:
        return "conditional"
    if score >= 9.2 and s_min >= 8.5:
        return "strong"
    return "publishable"


def check_history(state: dict, current: str | None, findings: list[Finding]) -> None:
    history = state.get("history")
    if not isinstance(history, list) or not history:
        findings.append(Finding("FAIL", "state_history", "state.history must be a non-empty array"))
        return
    first = history[0]
    if not isinstance(first, dict) or first.get("state") not in STATES:
        findings.append(Finding("FAIL", "state_history_entry", "history[0] has invalid state"))
    elif first.get("mode") != "migration" and first.get("state") != "IDEA_LOCKED":
        findings.append(Finding("FAIL", "state_history_origin", "history must start at IDEA_LOCKED unless first entry mode=migration"))

    previous_valid_state: str | None = None
    for i, entry in enumerate(history):
        if not isinstance(entry, dict):
            findings.append(Finding("FAIL", "state_history_entry", f"history[{i}] must be an object"))
            previous_valid_state = None
            continue
        cur = entry.get("state")
        if cur not in STATES:
            findings.append(Finding("FAIL", "state_history_entry", f"history[{i}] has invalid state"))
            previous_valid_state = None
            continue
        if not isinstance(entry.get("at"), str) or not entry.get("at", "").strip():
            findings.append(Finding("FAIL", "state_history_at", f"history[{i}].at must be non-empty"))
        if i == 0:
            previous_valid_state = cur
            continue
        mode = entry.get("mode")
        if mode not in {"advance", "rewind"}:
            findings.append(Finding("FAIL", "state_history_mode", f"history[{i}].mode must be advance or rewind"))
        elif previous_valid_state is not None:
            if mode == "advance" and STATE_MIN[cur] != STATE_MIN[previous_valid_state] + 1:
                findings.append(Finding("FAIL", "illegal_state_history", f"history transition {previous_valid_state} -> {cur} is not adjacent advance"))
            elif mode == "rewind" and STATE_MIN[cur] >= STATE_MIN[previous_valid_state]:
                findings.append(Finding("FAIL", "illegal_state_history", f"history transition {previous_valid_state} -> {cur} is not a rewind"))
        previous_valid_state = cur
    tail = history[-1]
    tail_state = tail.get("state") if isinstance(tail, dict) else None
    if current and tail_state != current:
        findings.append(Finding("FAIL", "state_history_tail", "last history state must equal current_state"))


def check_populated_manifest_paths(repo_root: Path, manifest: dict, findings: list[Finding]) -> None:
    groups = {
        "manifest.release": (manifest.get("release"), ("publish_dir", "cover_path", "contact_sheet_path")),
        "manifest.artifacts": (manifest.get("artifacts"), ("story", "storyboard", "visual_spec", "captions", "publish_copy", "production_review", "propagation_card")),
        "manifest.data_review": (manifest.get("data_review"), ("report_path",)),
    }
    for where, (obj, keys) in groups.items():
        if not isinstance(obj, dict):
            continue
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                resolve_repo_relative_path(repo_root, value, findings, f"{where}.{key}")


def check_common(repo_root: Path, state: dict, manifest: dict, findings: list[Finding], *, metadata_only: bool = False) -> str | None:
    if state.get("schema_version") != 1:
        findings.append(Finding("FAIL", "state_schema", "episode-state.json schema_version must be 1"))
    if manifest.get("schema_version") != 1:
        findings.append(Finding("FAIL", "manifest_schema", "release-manifest.json schema_version must be 1"))
    for obj, where in ((state, "state"), (manifest, "manifest")):
        tv = obj.get("tool_version")
        if tv is not None and tv != SYSTEM_VERSION:
            findings.append(Finding("WARN", "tool_version", f"{where}.tool_version={tv!r}; current tool is {SYSTEM_VERSION}"))
    current = state.get("current_state")
    if current not in STATES:
        findings.append(Finding("FAIL", "invalid_state", f"current_state={current!r}"))
        current = None
    for key in ("episode_id", "series", "title", "updated_at"):
        require_string(state, key, findings, "state")
    check_history(state, current, findings)

    episode = manifest.get("episode")
    if not isinstance(episode, dict):
        findings.append(Finding("FAIL", "manifest_episode", "manifest.episode must be an object"))
    else:
        for key in ("id", "series", "title", "format", "aspect_ratio"):
            require_string(episode, key, findings, "manifest.episode")
        try:
            resolve_canvas_spec(episode.get("aspect_ratio"))
        except ValueError as e:
            findings.append(Finding("FAIL", "aspect_ratio", str(e)))
        if episode.get("id") != state.get("episode_id"):
            findings.append(Finding("FAIL", "id_drift", "state episode_id != manifest episode.id"))
        if episode.get("series") != state.get("series"):
            findings.append(Finding("FAIL", "series_drift", "state series != manifest episode.series"))
        if episode.get("title") != state.get("title"):
            findings.append(Finding("FAIL", "title_drift", "state title != manifest episode.title"))

    release = manifest.get("release")
    if not isinstance(release, dict):
        findings.append(Finding("FAIL", "manifest_release", "manifest.release must be an object"))
    elif not isinstance(release.get("body_frame_count"), int) or isinstance(release.get("body_frame_count"), bool) or release.get("body_frame_count") <= 0:
        findings.append(Finding("FAIL", "frame_count", "release.body_frame_count must be > 0"))
    check_populated_manifest_paths(repo_root, manifest, findings)

    quality = manifest.get("quality")
    if not isinstance(quality, dict):
        findings.append(Finding("FAIL", "manifest_quality", "manifest.quality must be an object"))
    else:
        pg = quality.get("production_gate")
        legacy_quality = metadata_only and pg in LEGACY_PRODUCTION_GATE_VALUES
        if pg not in PRODUCTION_DECISIONS:
            if legacy_quality:
                findings.append(Finding("WARN", "legacy_quality_placeholder", f"旧世代 quality.production_gate={pg!r} 占位值；推进前先迁移质量字段"))
            else:
                findings.append(Finding("FAIL", "production_gate", "invalid quality.production_gate"))
        if quality.get("propagation_decision") not in PROPAGATION_DECISIONS:
            if legacy_quality:
                findings.append(Finding("WARN", "legacy_quality_placeholder", "旧世代 manifest 未登记 propagation_decision；推进前迁移"))
            else:
                findings.append(Finding("FAIL", "propagation_decision", "invalid quality.propagation_decision"))
        if quality.get("publish_decision") not in PUBLISH_DECISIONS:
            findings.append(Finding("FAIL", "publish_decision", "invalid quality.publish_decision"))
    return current


def frame_list(value: object, total: int, findings: list[Finding], where: str) -> list[int]:
    if not isinstance(value, list):
        findings.append(Finding("FAIL", "frame_list", f"{where} must be an array"))
        return []
    out = []
    for x in value:
        if isinstance(x, bool) or not isinstance(x, int) or not 1 <= x <= total:
            findings.append(Finding("FAIL", "frame_number", f"{where} contains invalid frame: {x!r}; total={total}"))
        else:
            out.append(x)
    return out


def review_passed(reviews: dict, key: str, findings: list[Finding]) -> None:
    value = reviews.get(key)
    if value not in REVIEW_STATUSES:
        findings.append(Finding("FAIL", "review_status", f"story-gates.reviews.{key} invalid: {value!r}"))
    elif value != "passed":
        findings.append(Finding("FAIL", "review_not_passed", f"story-gates.reviews.{key} must be 'passed', got {value!r}"))


def check_gates_common(state: dict, manifest: dict, gates: dict, findings: list[Finding]) -> None:
    if gates.get("schema_version") != 1:
        findings.append(Finding("FAIL", "gates_schema", "story-gates.json schema_version must be 1"))
    episode_id = gates.get("episode_id")
    if episode_id != state.get("episode_id") or episode_id != (manifest.get("episode") or {}).get("id"):
        findings.append(Finding("FAIL", "gates_id_drift", "story-gates episode_id must match state + release manifest"))
    reviews = gates.get("reviews")
    if not isinstance(reviews, dict):
        findings.append(Finding("FAIL", "gates_reviews", "story-gates.reviews must be object"))
    else:
        for key, value in reviews.items():
            if value not in REVIEW_STATUSES:
                findings.append(Finding("FAIL", "review_status", f"story-gates.reviews.{key} invalid: {value!r}"))


def locked_story_contract(episode_dir: Path) -> bool:
    """Whether creative-authoring gates are inapplicable to a user-locked story.

    Locked-story mode preserves the user's supplied story structure. It must not
    require invention-only evidence such as competing explanations or four-lock
    novelty, while ordinary closure, frame bounds and independent Story Review
    remain mandatory.
    """
    try:
        request = runtime_request.authority_for_episode(Path(episode_dir).resolve())
    except Exception:
        return False
    if not isinstance(request, dict):
        return False
    story_input = request.get("story_input")
    if not isinstance(story_input, dict):
        return False
    return (
        story_input.get("mode") == "locked_story"
        and story_input.get("allow_structure_rewrite") is False
    )


def check_story_gate(gates: dict, total: int, findings: list[Finding], *, creative_gates_required: bool = True, narrative_form: str = story_narrative_form.STANDALONE) -> None:
    story = gates.get("story")
    reviews = gates.get("reviews") if isinstance(gates.get("reviews"), dict) else {}
    if not isinstance(story, dict):
        findings.append(Finding("FAIL", "story_gate", "story-gates.story must be object"))
        return
    if creative_gates_required:
        if story.get("recent5_checked") is not True:
            findings.append(Finding("FAIL", "recent5_not_checked", "最近5篇账号级同质化检查尚未通过"))
        diff = story.get("four_locks_diff_count")
        if isinstance(diff, bool) or not isinstance(diff, int) or diff < 2:
            findings.append(Finding("FAIL", "four_locks_diff", "四把锁至少需要 2 把不同"))
        if story.get("mechanism_skin_swap_veto") is True:
            findings.append(Finding("FAIL", "mechanism_skin_swap_veto", "已触发机制换皮一票否决"))
    if story.get("task_closed") is not True:
        detail=("本集没有可核实的状态改变与悬念兑现" if narrative_form==story_narrative_form.SERIAL_EPISODE else "任务/事件闭环尚未完成")
        findings.append(Finding("FAIL", "task_not_closed", detail))
    if creative_gates_required:
        ce = story.get("competing_explanations")
        if isinstance(ce, bool) or not isinstance(ce, int) or ce < 2:
            findings.append(Finding("FAIL", "competing_explanations", "至少需要 2 种竞争解释"))
    hooks = frame_list(story.get("hook_frames"), total, findings, "story.hook_frames")
    if not hooks:
        findings.append(Finding("FAIL", "hook_frames", "hook_frames 不能为空"))
    for key in ("climax_frame", "payoff_frame"):
        value = story.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= total:
            findings.append(Finding("FAIL", key, f"story.{key} must be within 1..{total}"))
    review_passed(reviews, "story", findings)


def check_visual_gate(gates: dict, total: int, findings: list[Finding]) -> None:
    visual = gates.get("visual")
    reviews = gates.get("reviews") if isinstance(gates.get("reviews"), dict) else {}
    if not isinstance(visual, dict):
        findings.append(Finding("FAIL", "visual_gate", "story-gates.visual must be object"))
        return
    frames = frame_list(visual.get("admission_frames"), total, findings, "visual.admission_frames")
    if len(frames) != 4 or len(set(frames)) != 4:
        findings.append(Finding("FAIL", "visual_admission_frames", "视觉准入必须恰好 4 帧且互不重复"))
    continuity = visual.get("continuity")
    if not isinstance(continuity, dict):
        findings.append(Finding("FAIL", "continuity", "visual.continuity must be object"))
    else:
        required = continuity.get("required")
        anchors = continuity.get("anchors")
        if not isinstance(required, list) or not required:
            findings.append(Finding("FAIL", "continuity_required", "visual.continuity.required must be non-empty array"))
            required = []
        if not isinstance(anchors, dict):
            findings.append(Finding("FAIL", "continuity_anchors", "visual.continuity.anchors must be object"))
            anchors = {}
        for key in required:
            if not isinstance(key, str) or not key.strip():
                findings.append(Finding("FAIL", "continuity_required", f"invalid continuity key: {key!r}"))
                continue
            if not str(anchors.get(key) or "").strip():
                findings.append(Finding("FAIL", "continuity_anchor_missing", f"required continuity anchor missing: {key}"))
    review_passed(reviews, "visual_admission", findings)
    review_passed(reviews, "authenticity", findings)


def check_production_story_os_gate(gates: dict, findings: list[Finding], *, waive: bool = False) -> None:
    reviews = gates.get("reviews") if isinstance(gates.get("reviews"), dict) else {}
    for key in ("production", "continuity", "authenticity"):
        if key == "production" and waive and reviews.get(key) in {"passed", "waived"}:
            findings.append(Finding("WARN", "production_review_accepted", "direct user final-decision acceptance recorded; reviews.production waived (meta/final-acceptance.json)"))
            continue
        review_passed(reviews, key, findings)
    subtitles = gates.get("subtitles")
    if not isinstance(subtitles, dict):
        findings.append(Finding("FAIL", "subtitles_gate", "story-gates.subtitles must be object"))
        return
    if subtitles.get("required") is True:
        if subtitles.get("sound_card_completed") is not True:
            if waive:
                findings.append(Finding("WARN", "sound_card_accepted", "direct user final-decision acceptance recorded; sound card waived (meta/final-acceptance.json)"))
            else:
                findings.append(Finding("FAIL", "sound_card", "正式字幕前必须完成声音卡"))
        if waive and reviews.get("subtitle") in {"passed", "waived"}:
            findings.append(Finding("WARN", "subtitle_review_accepted", "direct user final-decision acceptance recorded; reviews.subtitle waived (meta/final-acceptance.json)"))
        else:
            review_passed(reviews, "subtitle", findings)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check_locks(repo_root: Path, gates: dict, findings: list[Finding], *, metadata_only: bool, legacy_gates_pending: bool = False) -> None:
    locks = gates.get("locks")
    if not isinstance(locks, dict):
        if metadata_only and legacy_gates_pending:
            findings.append(Finding("WARN", "legacy_locks_pending", "旧世代 story-gates 尚未迁移 locks（legacy gates envelope）；推进前运行 episode_state.py migrate-gates"))
        else:
            findings.append(Finding("FAIL", "locks", "story-gates.locks must be object"))
        return
    mode = locks.get("edit_mode", "none")
    if mode not in LOCK_MODES:
        findings.append(Finding("FAIL", "lock_mode", f"invalid locks.edit_mode={mode!r}"))
    assets = locks.get("assets")
    if not isinstance(assets, list):
        findings.append(Finding("FAIL", "locked_assets", "locks.assets must be array"))
        return
    if mode == "subtitle_only" and not assets:
        findings.append(Finding("FAIL", "subtitle_only_without_hash", "subtitle_only 必须登记至少 1 个锁定底图 SHA-256"))
    for i, item in enumerate(assets):
        if not isinstance(item, dict):
            findings.append(Finding("FAIL", "locked_asset", f"locks.assets[{i}] must be object"))
            continue
        raw = item.get("path")
        expected = str(item.get("sha256") or "")
        if not HEX64_RE.match(expected):
            findings.append(Finding("FAIL", "locked_asset_hash", f"locks.assets[{i}].sha256 must be 64 hex chars"))
            continue
        p = resolve_repo_relative_path(repo_root, raw, findings, f"story-gates.locks.assets[{i}].path")
        if p is None:
            continue
        if metadata_only:
            continue
        if not p.exists():
            findings.append(Finding("FAIL", "locked_asset_missing", f"locked asset missing: {raw}"))
            continue
        actual = sha256_file(p)
        if actual.lower() != expected.lower():
            findings.append(Finding("FAIL", "locked_asset_changed", f"锁定资产已变化: {raw}\nexpected={expected}\nactual  ={actual}"))


def image_dimensions(path: Path) -> tuple[int, int] | None:
    ext = path.suffix.lower()
    try:
        if ext == ".png":
            head = path.read_bytes()[:24]
            if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
                return struct.unpack(">II", head[16:24])
            return None
        if ext in {".jpg", ".jpeg"}:
            with path.open("rb") as f:
                if f.read(2) != b"\xff\xd8":
                    return None
                while True:
                    b = f.read(1)
                    if not b:
                        return None
                    if b != b"\xff":
                        continue
                    marker = f.read(1)
                    while marker == b"\xff":
                        marker = f.read(1)
                    if not marker:
                        return None
                    code = marker[0]
                    if code in {0xD8, 0xD9}:
                        continue
                    raw_len = f.read(2)
                    if len(raw_len) != 2:
                        return None
                    length = struct.unpack(">H", raw_len)[0]
                    if length < 2:
                        return None
                    if code in {0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF}:
                        payload = f.read(length - 2)
                        if len(payload) < 5:
                            return None
                        height, width = struct.unpack(">HH", payload[1:5])
                        return width, height
                    f.seek(length - 2, 1)
    except OSError:
        return None
    return None


def check_publish_images(publish_dir: Path | None, body_glob: str | None, expected_count: object, aspect_ratio: object, findings: list[Finding], *, metadata_only: bool) -> None:
    if metadata_only or publish_dir is None or not publish_dir.exists() or not body_glob:
        return
    try:
        spec = resolve_canvas_spec(aspect_ratio if isinstance(aspect_ratio, str) else None)
    except ValueError as e:
        findings.append(Finding("FAIL", "aspect_ratio", str(e)))
        return
    expected_size = (spec.width, spec.height)
    files = [p for p in publish_dir.glob(body_glob) if p.is_file()]
    if isinstance(expected_count, int) and len(files) != expected_count:
        findings.append(Finding("FAIL", "body_count_mismatch", f"{publish_dir}: expected {expected_count}, found {len(files)} by {body_glob!r}"))
    for p in files:
        if p.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        size = image_dimensions(p)
        if size is None:
            findings.append(Finding("FAIL", "image_dimensions", f"cannot parse image dimensions: {p.name}"))
        elif size != expected_size:
            findings.append(Finding("FAIL", "image_size", f"{p.name}: {size[0]}x{size[1]}, expected {expected_size[0]}x{expected_size[1]} for {spec.aspect_ratio}"))


def check_stage(repo_root: Path, episode_dir: Path, manifest: dict, current: str, findings: list[Finding], *, metadata_only: bool) -> None:
    idx = STATE_MIN[current]
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    release = manifest.get("release") if isinstance(manifest.get("release"), dict) else {}
    quality = manifest.get("quality") if isinstance(manifest.get("quality"), dict) else {}
    publication = manifest.get("publication") if isinstance(manifest.get("publication"), dict) else {}
    data_review = manifest.get("data_review") if isinstance(manifest.get("data_review"), dict) else {}

    if idx >= STATE_MIN["STORYBOARD_LOCKED"]:
        require_repo_path(repo_root, artifacts, "storyboard", findings, "manifest.artifacts", metadata_only=metadata_only)
    if idx >= STATE_MIN["VISUAL_CALIBRATED"]:
        require_repo_path(repo_root, artifacts, "visual_spec", findings, "manifest.artifacts", metadata_only=metadata_only)
    if idx >= STATE_MIN["PRODUCTION_PASSED"]:
        require_repo_path(repo_root, artifacts, "production_review", findings, "manifest.artifacts", metadata_only=metadata_only)
        require_repo_path(repo_root, artifacts, "captions", findings, "manifest.artifacts", metadata_only=metadata_only)
        if quality.get("production_gate") != "pass":
            if not acceptance_allows(episode_dir, "production_gate"):
                findings.append(Finding("FAIL", "production_not_passed", "quality.production_gate must be 'pass'"))
            else:
                findings.append(Finding("WARN", "production_gate_accepted", "direct user final-decision acceptance recorded; production gate accepted as-is (meta/final-acceptance.json)"))
    if idx >= STATE_MIN["PUBLISH_READY"]:
        require_string(release, "version", findings, "manifest.release")
        publish_dir = require_repo_path(repo_root, release, "publish_dir", findings, "manifest.release", metadata_only=metadata_only, asset_path=True)
        require_repo_path(repo_root, release, "cover_path", findings, "manifest.release", metadata_only=metadata_only, asset_path=True)
        body_glob = require_string(release, "body_glob", findings, "manifest.release")
        require_repo_path(repo_root, artifacts, "captions", findings, "manifest.artifacts", metadata_only=metadata_only)
        require_repo_path(repo_root, artifacts, "publish_copy", findings, "manifest.artifacts", metadata_only=metadata_only)
        require_repo_path(repo_root, artifacts, "propagation_card", findings, "manifest.artifacts", metadata_only=metadata_only)
        score = quality.get("propagation_score")
        s_min = quality.get("s_min_score")
        if not is_number_0_10(score):
            findings.append(Finding("FAIL", "propagation_score", "quality.propagation_score must be 0..10"))
        if not is_number_0_10(s_min):
            findings.append(Finding("FAIL", "s_min_score", "quality.s_min_score must be 0..10"))
        expected = derive_propagation_decision(score, s_min)
        actual = quality.get("propagation_decision")
        if actual == "pending":
            findings.append(Finding("FAIL", "propagation_pending", "propagation decision cannot be pending"))
        elif expected is not None and actual != expected:
            findings.append(Finding("FAIL", "propagation_decision_mismatch", f"score={score}, s_min_score={s_min} => expected {expected}, got {actual}"))
        if quality.get("publish_decision") != "go":
            findings.append(Finding("FAIL", "publish_hold", "quality.publish_decision must be 'go'"))
        if actual in {"conditional", "not_recommended"} and (not isinstance(quality.get("decision_note"), str) or not quality.get("decision_note", "").strip()):
            findings.append(Finding("FAIL", "decision_note", "conditional/not_recommended release requires decision_note"))
        for key in ("actual_title", "description"):
            require_string(publication, key, findings, "manifest.publication")
        topics = publication.get("topics")
        if not isinstance(topics, list) or not topics or not all(isinstance(x, str) and x.strip() for x in topics):
            findings.append(Finding("FAIL", "topics", "publication.topics must be a non-empty string array"))
        check_publish_images(publish_dir, body_glob, release.get("body_frame_count"), (manifest.get("episode") or {}).get("aspect_ratio"), findings, metadata_only=metadata_only)
    if idx >= STATE_MIN["PUBLISHED"]:
        publish_event = load_json(episode_dir / "meta/publish-event.json", findings, required=False)
        if isinstance(publish_event, dict) and isinstance(publish_event.get("published_at"), str) and publish_event.get("published_at", "").strip():
            pass
        else:
            require_string(publication, "published_at", findings, "manifest.publication")
    if idx >= STATE_MIN["DATA_REVIEWED"]:
        data_state = load_json(episode_dir / "meta/data-review-state.json", findings, required=False)
        if isinstance(data_state, dict):
            require_repo_path(repo_root, data_state, "report_path", findings, "meta.data-review-state", metadata_only=metadata_only)
            completed = data_state.get("completed_checkpoints")
        else:
            require_repo_path(repo_root, data_review, "report_path", findings, "manifest.data_review", metadata_only=metadata_only)
            completed = data_review.get("completed_checkpoints")
        if not isinstance(completed, list) or not all(cp in completed for cp in REQUIRED_FOR_DATA_REVIEWED):
            required_text = ", ".join(REQUIRED_FOR_DATA_REVIEWED)
            findings.append(Finding("FAIL", "missing_48h_review", f"DATA_REVIEWED requires completed_checkpoints to include {required_text}"))

    readme = episode_dir / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8", errors="replace")
        if current == "PUBLISHED" and "可发布" in text and "已发布" not in text:
            findings.append(Finding("WARN", "readme_state_drift", "machine state is PUBLISHED but episode README still says 可发布"))
        if idx < STATE_MIN["PUBLISHED"] and "已发布" in text:
            findings.append(Finding("WARN", "readme_state_drift", f"machine state is {current} but episode README says 已发布"))


def check_story_os_for_effective(repo_root: Path, state: dict, manifest: dict, gates: dict, effective: str, findings: list[Finding], *, metadata_only: bool, waive: bool = False, legacy_gates_pending: bool = False, creative_story_gates_required: bool = True, narrative_form: str = story_narrative_form.STANDALONE) -> None:
    check_gates_common(state, manifest, gates, findings)
    total = (manifest.get("release") or {}).get("body_frame_count")
    if not isinstance(total, int) or total <= 0:
        return
    idx = STATE_MIN[effective]
    if idx >= STATE_MIN["STORYBOARD_LOCKED"]:
        check_story_gate(
            gates, total, findings,
            creative_gates_required=creative_story_gates_required,
            narrative_form=narrative_form,
        )
    if idx >= STATE_MIN["VISUAL_CALIBRATED"]:
        check_visual_gate(gates, total, findings)
    if idx >= STATE_MIN["PRODUCTION_PASSED"]:
        check_production_story_os_gate(gates, findings, waive=waive)
    if idx >= STATE_MIN["PUBLISH_READY"]:
        reviews = gates.get("reviews") if isinstance(gates.get("reviews"), dict) else {}
        review_passed(reviews, "recommendation_fit", findings)
        review_passed(reviews, "publish", findings)
    check_locks(repo_root, gates, findings, metadata_only=metadata_only, legacy_gates_pending=legacy_gates_pending)


def validate_episode(episode_dir: Path, repo_root: Path, metadata_only: bool, target_state: str | None = None) -> list[Finding]:
    findings: list[Finding] = []
    try:
        state = episode_state_persistence.load(episode_dir)
    except Exception as exc:
        findings.append(Finding("FAIL", "state_authority", f"Episode state authority read failed: {exc}"))
        state = None
    if state is None:
        findings.append(Finding("FAIL", "state_authority", "Episode state authority missing"))
    manifest = load_json(episode_dir / MANIFEST_FILE, findings)
    if state is None or manifest is None:
        return findings
    current = check_common(repo_root, state, manifest, findings, metadata_only=metadata_only)
    effective = target_state or current
    if target_state is not None and target_state not in STATES:
        findings.append(Finding("FAIL", "invalid_target_state", f"target_state={target_state!r}"))
        effective = None
    if effective:
        check_stage(repo_root, episode_dir, manifest, effective, findings, metadata_only=metadata_only)

    gates_path = episode_dir / GATES_FILE
    gates = load_json(gates_path, findings, required=False)
    state_v = str(state.get("tool_version") or "")
    manifest_v = str(manifest.get("tool_version") or "")

    def version_at_least(raw: str, minimum: tuple[int, int]) -> bool:
        try:
            parts = raw.strip().split(".")
            value = (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
        except (TypeError, ValueError, IndexError):
            return False
        return value >= minimum

    # Story Gates became mandatory in Story OS V1.4. Keep that boundary
    # monotonic when SYSTEM_VERSION advances.
    new_system_episode = version_at_least(state_v, (1, 4)) or version_at_least(manifest_v, (1, 4))
    # Pre-migration drafts still carry the legacy top-level "gates" envelope
    # and no locks; only the Git-metadata scan tolerates that shape.
    legacy_gates_pending = (
        isinstance(gates, dict)
        and isinstance(gates.get("gates"), dict)
        and not isinstance(gates.get("locks"), dict)
    )

    if gates is None:
        if new_system_episode:
            findings.append(Finding("FAIL", "missing_story_gates", f"V{SYSTEM_VERSION} episode requires {GATES_FILE}"))
        elif target_state is not None and effective and STATE_MIN[effective] >= STATE_MIN["STORYBOARD_LOCKED"]:
            findings.append(Finding("FAIL", "legacy_story_gates_required", "旧剧集继续推进前先运行 episode_state.py migrate-gates <episode_dir>"))
        else:
            findings.append(Finding("WARN", "legacy_without_story_gates", "旧剧集尚未迁移 Story OS V1.2 门禁；保持兼容"))
    elif effective:
        check_story_os_for_effective(
            repo_root, state, manifest, gates, effective, findings,
            metadata_only=metadata_only,
            waive=acceptance_allows(episode_dir, "production_gate"),
            legacy_gates_pending=legacy_gates_pending,
            creative_story_gates_required=not locked_story_contract(episode_dir),
            narrative_form=(story_narrative_form.for_episode(episode_dir) if Path(repo_root).resolve()==repo_root_from_script().resolve() else story_narrative_form.STANDALONE),
        )

    # V2.1 Concept Ambition is pre-Story-Lock evidence, not a second episode stage.
    if effective and STATE_MIN[effective] >= STATE_MIN["STORYBOARD_LOCKED"] and concept_ambition_required(episode_dir):
        for error in verify_concept_ambition(episode_dir):
            findings.append(Finding("FAIL", "concept_ambition_gate", error))
    if effective and STATE_MIN[effective] >= STATE_MIN["VISUAL_CALIBRATED"] and environment_contract_required(episode_dir):
        for error in verify_environment_contract(episode_dir):
            findings.append(Finding("FAIL", "environment_impact_gate", error))

    if effective and STATE_MIN[effective] >= STATE_MIN["VISUAL_CALIBRATED"] and visual_lock_v21_required(episode_dir):
        for error in verify_visual_lock_v21(episode_dir, metadata_only=metadata_only):
            findings.append(Finding("FAIL", "visual_lock_v21_gate", error))

    if effective and STATE_MIN[effective] >= STATE_MIN["PRODUCTION_PASSED"] and frame_contract_required(episode_dir):
        frame_contract_errors = verify_frame_contracts(episode_dir)
        if frame_contract_errors and acceptance_allows(episode_dir, "frame_semantic"):
            # Later direct-user SHA-bound image acceptance supersedes a stale
            # generation contract for release. Keep the stale cache visible as
            # a warning and require every accepted publish asset to verify.
            try:
                total = int(((manifest.get("release") or {}).get("body_frame_count")) or 0)
                accepted_complete = total > 0 and all(
                    visual_asset_for_frame(episode_dir, str(frame).zfill(2)) is not None
                    for frame in range(1, total + 1)
                )
            except (RuntimeError, ValueError, TypeError):
                accepted_complete = False
            if accepted_complete:
                for error in frame_contract_errors:
                    findings.append(Finding("WARN", "resolved_frame_contract_user_accepted", f"stale generation contract retained as history; all {total} direct-user accepted publish assets verified: {error}"))
            else:
                for error in frame_contract_errors:
                    findings.append(Finding("FAIL", "resolved_frame_contract_gate", error))
        else:
            for error in frame_contract_errors:
                findings.append(Finding("FAIL", "resolved_frame_contract_gate", error))

    if effective and STATE_MIN[effective] >= STATE_MIN["PRODUCTION_PASSED"] and fast_scout_required(episode_dir):
        # Fast Scout is a pixel-triage gate over actual media and its audit
        # rewrites derived frame-contract caches; the Git-metadata CI scan
        # defers it to local/full verification where media exists.
        if not metadata_only:
            scout_errors = audit_fast_scout(episode_dir, write_summary=True)
            if scout_errors:
                if acceptance_allows(episode_dir, "fast_frame_scout"):
                    findings.append(Finding("WARN", "fast_frame_scout_accepted", "direct user final-decision acceptance recorded; scout REPAIR_NOW/stale accepted as known defects (meta/final-acceptance.json)"))
                else:
                    for error in scout_errors:
                        findings.append(Finding("FAIL", "fast_frame_scout_gate", error))

    if effective and STATE_MIN[effective] >= STATE_MIN["PUBLISH_READY"] and final_snapshot_required(episode_dir):
        for error in verify_final_snapshot(episode_dir, metadata_only=metadata_only):
            findings.append(Finding("FAIL", "final_candidate_snapshot_gate", error))

    if effective and STATE_MIN[effective] >= STATE_MIN["PUBLISHED"] and post_publish_required(episode_dir):
        for error in verify_post_publish(episode_dir, require_48h=STATE_MIN[effective] >= STATE_MIN["DATA_REVIEWED"]):
            findings.append(Finding("FAIL", "post_publish_data_gate", error))
    return findings


def discover_episode_dirs(episodes_root: Path) -> Iterable[Path]:
    import episode_discovery
    yield from episode_discovery.iter_episode_roots(episodes_root)


def print_result(episode_dir: Path, findings: list[Finding]) -> bool:
    failed = any(f.level == "FAIL" for f in findings)
    print(f"\n=== {'FAIL' if failed else 'PASS'} {episode_dir} ===")
    if not findings:
        print("[PASS] clean")
    else:
        for finding in findings:
            print(finding)
    return not failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Story OS episode state + gates")
    parser.add_argument("episode_dir", nargs="?")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--repo-root")
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--target", choices=STATES)
    args = parser.parse_args()
    if bool(args.episode_dir) == bool(args.all):
        parser.error("provide exactly one episode_dir or --all")
    if args.all and args.target:
        parser.error("--target is only valid for a single episode")
    repo_root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_script()
    episodes_root = repo_root / "episodes"
    dirs = sorted(set(discover_episode_dirs(episodes_root))) if args.all else [Path(args.episode_dir).resolve()]
    if not dirs:
        print("no episode state files found; legacy repository is still compatible")
        return 0
    ok = True
    for episode_dir in dirs:
        ok = print_result(episode_dir, validate_episode(episode_dir, repo_root, args.metadata_only, args.target)) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
