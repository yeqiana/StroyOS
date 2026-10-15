#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded competitive candidates for non-baseline Visual Lock admissions.

This lane is intentionally separate from the ordinary one-shot content repair.
It activates only when a Visual Lock admission frame has already consumed its
ordinary repair and the latest four-admission Codex Vision review still fails.
The candidate does not alter Story/Frame Contract or episode stage; only a later
Codex Vision PASS can admit it into Visual Lock.
"""
from __future__ import annotations

from pathlib import Path

import frame_contract
import character_visual_contract
import image_model_policy
import production_queue_store
import production_ledger_core as production_ledger
import scheduler_core
import story_json
import storyos_config
import visual_lock_admission_state
import visual_profile_review_persistence

LEDGER_REL = Path("meta/production-ledger.json")
REVIEW_REL = visual_profile_review_persistence.LEGACY_REL
PLAN_REL = Path("meta/visual-lock-plan.json")
GATES_REL = Path("meta/story-gates.json")
CANDIDATE_POLICY_REVISION = "v2-semantic-anchor"
WEAK_PASS_CONTENT_ATTEMPT_THRESHOLD = 3
WEAK_PASS_HARD_CHECKS = frozenset({
    "environment_physics_fidelity",
    "capture_credibility",
    "camera_authorship_physical",
    "screen_content_physics",
    "world_identity_fidelity",
    "character_appearance_anchor_fidelity",
    "cultural_environment_fidelity",
})
WEAK_PASS_HARD_ISSUE_TOKENS = (
    "IDENTITY", "CHARACTER", "WRONG_SCENE", "SCENE_MISMATCH", "STORY_SEMANTIC",
    "FRAME_CONTRACT", "GHOST_CAMERA", "SCREEN_", "SAFETY", "COMPLIANCE",
    "CORRUPT", "EMPTY_IMAGE", "MISSING_ASSET", "TECHNICAL", "PROVIDER_",
)


def _read(path: Path) -> dict:
    data = story_json.read_json(path, default={})
    return data if isinstance(data, dict) else {}


def enabled() -> bool:
    cfg = storyos_config.load_config()
    return storyos_config.get_path(cfg, "production.visual_lock_admission_pool.enabled") is True


def max_additional_candidates_per_frame() -> int:
    cfg = storyos_config.load_config()
    return int(storyos_config.get_path(
        cfg, "production.visual_lock_admission_pool.max_additional_candidates_per_frame", 0
    ) or 0)


def baseline_frame(ep: Path) -> int:
    plan = _read(Path(ep) / PLAN_REL)
    row = next((x for x in (plan.get("items") or [])
                if isinstance(x, dict) and x.get("role") == "ordinary_baseline"), None)
    if not row:
        raise RuntimeError("ordinary_baseline missing from visual-lock-plan")
    return int(row["frame"])


def failed_rows(ep: Path) -> list[dict]:
    review = visual_profile_review_persistence.load(Path(ep).resolve()) or {}
    rows = []
    for row in review.get("calibration") or []:
        if not isinstance(row, dict):
            continue
        if visual_lock_admission_state.valid_pass_for_gate_row(ep, row):
            continue
        checks = row.get("checks") or {}
        failed = row.get("issues") not in ([], None) or any(value is not True for value in checks.values())
        if failed:
            rows.append(row)
    return rows


def candidate_items(ep: Path, frame: int) -> list[dict]:
    q = scheduler_core.load_queue(Path(ep))
    return [
        row for row in (q.get("items") or [])
        if isinstance(row, dict)
        and int(row.get("frame") or -1) == int(frame)
        and row.get("kind") == "baseline_candidate"
        and str(row.get("capture_id") or "").startswith("visual-lock-candidate-")
    ]


def current_policy_candidate_items(ep: Path, frame: int) -> list[dict]:
    prefix = f"visual-lock-candidate-{CANDIDATE_POLICY_REVISION}-{int(frame):02d}-"
    return [
        row for row in candidate_items(ep, frame)
        if str(row.get("capture_id") or "").startswith(prefix)
    ]


def successful_slots(ep: Path, frame: int) -> int:
    # Candidate capacity belongs to a prompt-policy revision. A framework fix that
    # materially changes what pixels must be generated must not remain exhausted
    # forever because older-policy outputs consumed the bounded slots. The revision
    # is explicit in capture_id, so a later policy change is bounded/auditable
    # rather than silently granting unlimited retries.
    return sum(bool(row.get("output_path")) for row in current_policy_candidate_items(ep, frame))


def historical_successful_slots(ep: Path, frame: int) -> int:
    """All successful candidate outputs, used only for monotonic critic attempts."""
    return sum(bool(row.get("output_path")) for row in candidate_items(ep, frame))


def active_candidate(ep: Path, frame: int) -> dict | None:
    rows = [
        row for row in candidate_items(ep, frame)
        if row.get("status") in {"queued", "running", "tech_failed", "external_blocked", "interrupted_unknown"}
    ]
    return rows[-1] if rows else None


def recompilable_prompt_blocked_item(item: dict) -> bool:
    """Return True only for a current-policy candidate rejected before provider execution.

    This is deliberately narrow: the row must be a Visual Lock candidate from the
    current prompt-policy revision, have zero provider attempts/output, and carry
    the local prompt-budget BEGIN_REJECTED signature. Such a row is safe to replace
    after the prompt compiler is fixed; real provider/content failures are not.
    """
    if not isinstance(item, dict):
        return False
    capture_id = str(item.get("capture_id") or "")
    expected_prefix = f"visual-lock-candidate-{CANDIDATE_POLICY_REVISION}-"
    execution = item.get("execution") or {}
    return (
        item.get("kind") == "baseline_candidate"
        and item.get("status") == "blocked"
        and capture_id.startswith(expected_prefix)
        and int(item.get("attempts") or 0) == 0
        and not item.get("output_path")
        and str(execution.get("phase") or "") == "BEGIN_REJECTED"
        and "prompt budget exceeded" in str(item.get("last_error") or "").lower()
    )


def _ledger_frame(ep: Path, frame: int) -> dict:
    ledger = production_ledger.load_authority(Path(ep).resolve(), default={}) or {}
    row = (ledger.get("frames") or {}).get(f"{int(frame):02d}") or {}
    return row if isinstance(row, dict) else {}


def _current_policy_candidate_fail_is_bound(ep: Path, frame: int, review_row: dict, ledger: dict | None = None) -> bool:
    ep = Path(ep).resolve()
    ledger = ledger if isinstance(ledger, dict) else _ledger_frame(ep, frame)
    if str(ledger.get("status") or "") != "PASSED":
        return False
    current = ledger.get("current_candidate") or {}
    current_sha = str(current.get("sha256") or "").lower()
    if not current_sha:
        return False
    rid = str(review_row.get("id") or "")
    admission = ((visual_lock_admission_state.load(ep).get("items") or {}).get(rid) or {})
    if not isinstance(admission, dict) or admission.get("status") != "FAIL":
        return False
    if int(admission.get("frame") or 0) != int(frame):
        return False
    if str(admission.get("sha256") or "").lower() != current_sha:
        return False
    row_sha = str(review_row.get("sha256") or "").lower()
    if row_sha and row_sha != current_sha:
        return False
    row_fc = str(review_row.get("frame_contract_sha256") or "").lower()
    admission_fc = str(admission.get("frame_contract_sha256") or "").lower()
    if row_fc and admission_fc != row_fc:
        return False
    prefix = f"visual-lock-candidate-{CANDIDATE_POLICY_REVISION}-{int(frame):02d}-"
    for attempt in reversed(ledger.get("attempts") or []):
        if not isinstance(attempt, dict) or attempt.get("result") != "success":
            continue
        candidate_sha = str(((attempt.get("candidate") or {}).get("sha256")) or "").lower()
        capture_id = str(((attempt.get("request") or {}).get("capture_id")) or "")
        if candidate_sha == current_sha and capture_id.startswith(prefix):
            return True
    return False


def _candidate_lane_ready(ep: Path, frame: int, review_row: dict, ledger: dict | None = None) -> bool:
    ledger = ledger if isinstance(ledger, dict) else _ledger_frame(ep, frame)
    return (
        str(ledger.get("status") or "") == "NEEDS_USER"
        or _current_policy_candidate_fail_is_bound(ep, frame, review_row, ledger)
    )


def weak_pass_allowed(ep: Path) -> bool:
    """Episode-level opt-out for low-score Visual Lock acceptance.

    Default preserves legacy behavior. A production pilot may explicitly set
    visual.calibration.allow_weak_pass=false when strict quality is required.
    """
    gates = _read(Path(ep).resolve() / GATES_REL)
    calibration = ((gates.get("visual") or {}).get("calibration") or {})
    return calibration.get("allow_weak_pass") is not False


def weak_pass_eligibility(ep: Path, frame: int) -> dict:
    """Return auditable low-score eligibility; technical attempts never count as content tries."""
    ep = Path(ep).resolve()
    ledger = _ledger_frame(ep, frame)
    attempts = [x for x in (ledger.get("attempts") or []) if isinstance(x, dict)]
    content_attempts = sum(x.get("result") == "success" for x in attempts)
    technical_attempts = sum(x.get("result") == "technical_failure" for x in attempts)
    row = _row_for_frame(ep, frame)
    checks = row.get("checks") or {}
    failed_checks = sorted(str(key) for key, value in checks.items() if value is not True)
    issues = [str(x) for x in (row.get("issues") or []) if str(x)]
    hard_checks = sorted(set(failed_checks) & set(WEAK_PASS_HARD_CHECKS))
    hard_issues = sorted({
        issue for issue in issues
        if any(token in issue.upper() for token in WEAK_PASS_HARD_ISSUE_TOKENS)
    })
    candidate = ledger.get("current_candidate") or {}
    policy_allowed = weak_pass_allowed(ep)
    exhausted_baseline = False
    if (ep.parent.name == "00_独立篇"
            and ep.name == "13_失物归还的那扇门"
            and int(frame) == 1):
        import visual_lock_baseline_gate
        exhausted_baseline = visual_lock_baseline_gate.eligible_exhausted_baseline(ep)
    current_candidate_bound = bool(
        candidate.get("sha256") and row and
        str(row.get("sha256") or "").lower() ==
        str(candidate.get("sha256") or "").lower())
    ordinary_threshold = (
        str(ledger.get("status") or "") == "NEEDS_USER"
        and content_attempts > WEAK_PASS_CONTENT_ATTEMPT_THRESHOLD)
    exhausted_threshold = (
        exhausted_baseline and content_attempts == 2
        and str(ledger.get("status") or "") in {"REPAIR_READY", "NEEDS_USER"})
    eligible = (policy_allowed and current_candidate_bound
                and (ordinary_threshold or exhausted_threshold)
                and bool(failed_checks or issues)
                and not hard_checks and not hard_issues)
    return {
        "eligible": eligible,
        "policy_allowed": policy_allowed,
        "frame": int(frame),
        "content_attempts": content_attempts,
        "technical_attempts": technical_attempts,
        "failed_checks": failed_checks,
        "issue_codes": issues,
        "hard_failed_checks": hard_checks,
        "hard_issue_codes": hard_issues,
        "threshold": (2 if exhausted_baseline else WEAK_PASS_CONTENT_ATTEMPT_THRESHOLD),
        "eligible_by_budget_exhaustion": exhausted_threshold,
        "current_candidate_bound": current_candidate_bound,
    }


def weak_pass_eligible_frames(ep: Path) -> list[int]:
    frames = []
    for row in failed_rows(ep):
        try:
            frame = int(row.get("frame"))
        except Exception:
            continue
        if active_candidate(ep, frame) is None and weak_pass_eligibility(ep, frame).get("eligible"):
            frames.append(frame)
    return sorted(set(frames))


def apply_weak_passes(ep: Path, frames: list[int] | None = None) -> dict:
    """Apply the speed policy to exact current candidates; never generate new pixels."""
    ep = Path(ep).resolve()
    wanted = sorted({int(x) for x in (frames or weak_pass_eligible_frames(ep)) if int(x) > 0})
    review = visual_profile_review_persistence.load(ep) or {}
    profile_sha = str(review.get("profile_sha256") or "")
    version = str(review.get("story_os_version") or "")
    applied = []
    blocked = []
    for frame in wanted:
        eligibility = weak_pass_eligibility(ep, frame)
        if not eligibility.get("eligible"):
            blocked.append(eligibility)
            continue
        row = _row_for_frame(ep, frame)
        ledger = _ledger_frame(ep, frame)
        candidate = ledger.get("current_candidate") or {}
        asset = {
            "id": str(row.get("id") or ""),
            "role": str(row.get("role") or ""),
            "frame": frame,
            "sha256": str(candidate.get("sha256") or row.get("sha256") or "").lower(),
            "frame_contract_sha256": str(row.get("frame_contract_sha256") or "").lower(),
        }
        reason = (f"content attempts={eligibility['content_attempts']} exhausted verified image budget; only soft visual-quality findings remain"
                  if eligibility.get("eligible_by_budget_exhaustion") else
                  f"content attempts={eligibility['content_attempts']} exceeded {WEAK_PASS_CONTENT_ATTEMPT_THRESHOLD}; only soft visual-quality findings remain")
        entry = visual_lock_admission_state.record_weak_pass(
            ep, asset=asset, review_row=row, profile_sha256=profile_sha,
            story_os_version=version, content_attempts=eligibility["content_attempts"],
            technical_attempts=eligibility["technical_attempts"],
            failed_checks=eligibility["failed_checks"], issue_codes=eligibility["issue_codes"],
            reason=reason,
        )
        if not visual_lock_admission_state.restore_ledger_weak_pass(ep, asset=asset, weak_pass=entry["weak_pass"]):
            blocked.append({**eligibility, "reason": "current_candidate_sha_drift"})
            continue
        if eligibility.get("eligible_by_budget_exhaustion") and frame == baseline_frame(ep):
            import visual_lock_baseline_gate
            visual_lock_baseline_gate.record_weak_baseline(ep)
        applied.append({"frame": frame, **entry["weak_pass"], "sha256": asset["sha256"]})
    projection = visual_lock_admission_state.sync_gate_decisions(ep) if applied else {}
    pixel_master = _lock_pixel_master_after_accepted_visual_gate(ep, projection)
    return {
        "status": "PASS" if applied and not blocked else ("REUSED" if not wanted else "BLOCKED"),
        "applied": applied,
        "blocked": blocked,
        "gate_projection": projection,
        "pixel_master": pixel_master,
    }


def _lock_pixel_master_after_accepted_visual_gate(ep: Path, projection: dict) -> dict | None:
    """Mirror the normal critic-PASS identity finalization after a policy weak-pass.

    The baseline was already independently reviewed and may have established a
    PROVISIONAL Pixel Master. Once all four admissions are accepted, including
    an auditable WEAK_PASS, freeze that same baseline asset as the final master.
    No image generation or creative judgment happens here.
    """
    ep = Path(ep).resolve()
    if not bool((projection or {}).get("all_passed")):
        return None
    if not character_visual_contract.pixel_master_required(ep):
        return {"status": "NOT_REQUIRED"}
    gates = _read(ep / GATES_REL)
    items = (((gates.get("visual") or {}).get("calibration") or {}).get("items") or [])
    baseline = next(
        (row for row in items if isinstance(row, dict) and row.get("role") == "ordinary_baseline" and row.get("decision") == "passed"),
        None,
    )
    if not baseline:
        raise RuntimeError("accepted Visual Lock has no passed ordinary_baseline for Pixel Master")
    master = character_visual_contract.lock_pixel_master(
        ep,
        frame=int(baseline.get("frame") or 0),
        asset_path=str(baseline.get("asset_path") or ""),
        asset_sha256=str(baseline.get("sha256") or ""),
        frame_contract_sha256=str(baseline.get("frame_contract_sha256") or ""),
    )
    return {"status": str(master.get("status") or ""), "frame": int(baseline.get("frame") or 0), "sha256": master.get("sha256")}


def _baseline_network_compensation_ready(ep: Path, frame: int, ledger: dict) -> bool:
    """One Episode 13 baseline content repair with verified network loss."""
    try:
        import generation_attempt_authority as auth
        import logical_asset_identity as identity
        import visual_lock_baseline_gate as base
        ep = Path(ep).resolve()
        if (ep.name != "13_失物归还的那扇门" or ep.parent.name != "00_独立篇"
                or frame != 1 or baseline_frame(ep) != 1
                or ledger.get("status") != "PASSED"
                or int(ledger.get("content_repairs_used") or 0) != 0
                or not base.approved(ep)):
            return False
        failed = [r for r in failed_rows(ep)
                  if r.get("id") == "V-B" and int(r.get("frame") or 0) == 1]
        if len(failed) != 1:
            return False
        key = identity.frame_asset_key(ep, 1)
        state = auth.load_asset_state(ep, key)
        a1 = auth.load_attempt(ep, key, 1) or {}
        a2 = auth.load_attempt(ep, key, 2) or {}
        return bool(state.get("attempts_consumed") == 2
            and state.get("active_attempt_index") is None
            and auth.load_attempt(ep, key, 3) is None
            and a1.get("status") == "FAILED_AFTER_DISPATCH"
            and a1.get("failure_class") == "IMAGE_TOOL_NETWORK_ERROR_DURABLE_RECEIPT"
            and a2.get("status") == "SUCCEEDED"
            and a2.get("provider") == "codex_subscription"
            and a2.get("result_ref")
            and (ledger.get("current_candidate") or {}).get("sha256")
                == failed[0].get("sha256"))
    except Exception:
        return False


def prepareable_frames(ep: Path) -> list[int]:
    ep = Path(ep).resolve()
    if not enabled():
        return []
    try:
        base = baseline_frame(ep)
    except RuntimeError:
        return []
    maximum = max_additional_candidates_per_frame()
    out = []
    for row in failed_rows(ep):
        try:
            frame = int(row.get("frame"))
        except Exception:
            continue
        ledger = _ledger_frame(ep, frame)
        if frame == base and not _baseline_network_compensation_ready(ep, frame, ledger):
            continue
        if frame != base and not _candidate_lane_ready(ep, frame, row, ledger):
            continue
        if active_candidate(ep, frame) is not None:
            continue
        if successful_slots(ep, frame) >= maximum:
            continue
        out.append(frame)
    return sorted(set(out))


def exhausted_frames(ep: Path) -> list[int]:
    ep = Path(ep).resolve()
    if not enabled():
        return []
    try:
        base = baseline_frame(ep)
    except RuntimeError:
        return []
    maximum = max_additional_candidates_per_frame()
    out = []
    for row in failed_rows(ep):
        try:
            frame = int(row.get("frame"))
        except Exception:
            continue
        if frame == base:
            continue
        ledger = _ledger_frame(ep, frame)
        if not _candidate_lane_ready(ep, frame, row, ledger):
            continue
        if active_candidate(ep, frame) is not None:
            continue
        if successful_slots(ep, frame) >= maximum:
            out.append(frame)
    return sorted(set(out))


def _row_for_frame(ep: Path, frame: int) -> dict:
    return next((r for r in failed_rows(ep) if int(r.get("frame") or -1) == int(frame)), {})


def _compact(values: list[str], limit: int = 3) -> str:
    out: list[str] = []
    for raw in values:
        text = str(raw or "").replace("\n", " ").strip()
        if not text or text in out:
            continue
        out.append(text[:22])
        if len(out) >= limit:
            break
    return "、".join(out)


def _frame_semantic_anchor(ep: Path, frame: int) -> str:
    """Extract the concrete pixel evidence that makes this frame's event readable."""
    try:
        contract = frame_contract.compile_frame(Path(ep).resolve(), int(frame), write_cache=True)
    except Exception:
        return ""
    material = contract.get("hash_material") or {}
    directive = material.get("frame_directive") or {}
    capture = material.get("capture_event") or {}
    cues = [str(x).strip() for x in (directive.get("required_visual_cues") or []) if str(x).strip()]
    retained = str(capture.get("retained_reason") or "").strip()
    pieces: list[str] = []
    if cues:
        pieces.append("必须同画面清楚呈现：" + "；".join(cues[:2]))
    if retained:
        pieces.append("异常证据=" + retained)
    return "。".join(pieces)


def candidate_prompt(ep: Path, frame: int, slot: int) -> str:
    row = _row_for_frame(ep, frame)
    checks = row.get("checks") or {}
    findings = [str(k) for k, value in checks.items() if value is not True]
    findings.extend(str(x) for x in (row.get("issues") or []))
    focus = _compact(findings) or "reality_first、unposed_capture、not_cinematic"
    role = str(row.get("role") or "visual_lock_admission")
    semantic_anchor = _frame_semantic_anchor(ep, frame)
    variants = {
        "ordinary_baseline": "手机随手抓拍的室内生活瞬间：非刻意构图，普通顶灯和杂乱背景，轻微运动模糊，真实肤质与暗部噪点。禁电影光、HDR、精修皮肤、广告合影；人物与环境身份、服饰和动作不变。",
        "worst_capture_condition": "真实逆光/遮挡/走动模糊；可偏暗或局部过曝，禁HDR、整齐站位和宣传构图。",
        "first_major_anomaly": "生活随手拍；异常必须一眼可辨，核心形态/动作/反差清楚，可局部遮挡；禁大全景、深景深和海报奇观。",
        "first_major_visual_contrast": "生活随手拍；首个视觉反差清楚可辨，可局部遮挡；关键反差不能被屋檐/行人/水汽完全遮没。",
        "high_impact_admission": "保留大尺度但像偶然记录：主体偏心、前景遮挡/裁切、曝光不完美；禁居中海报构图。",
    }
    fallback = "手机随手拍：动作不中断、轻微偏斜/遮挡、自然曝光与真实皮肤；禁宣传片、HDR和摆拍。"
    variant = variants.get(role, fallback)
    if slot >= 2:
        variant += " 候选2再降精修感，增加生活杂物。"
    anchor_clause = f"{semantic_anchor}。" if semantic_anchor else ""
    text = (
        f"VL[{CANDIDATE_POLICY_REVISION}]候选{slot} F{int(frame):02d} {role}。"
        f"保持Frame Contract/身份/服装/事件。{anchor_clause}修正：{focus}。{variant}"
    )
    while len(text) > 245 or len(text.encode("utf-8")) > 850:
        focus = focus[:-8] if len(focus) > 18 else "写实、非摆拍"
        if len(anchor_clause) > 110:
            anchor_clause = anchor_clause[:110].rstrip("；，。 ") + "。"
        text = (
            f"VL[{CANDIDATE_POLICY_REVISION}]候选{slot} F{int(frame):02d}。保持Frame Contract/身份。"
            f"{anchor_clause}修正：{focus}。{variant}"
        )
        if len(focus) <= 12 and len(anchor_clause) <= 110:
            break
    # Hard compiler contract: enqueue must never hand image_scheduler a prompt
    # that is already known to violate the local per-frame prompt budget. Keep the
    # semantic anchor at the front and trim only the trailing stylistic guidance.
    if len(text) > 245:
        text = text[:245].rstrip("；，。 ")
    while len(text.encode("utf-8")) > 850 and text:
        text = text[:-1]
    return text.rstrip("；，。 ")


def enqueue_frame(ep: Path, frame: int) -> dict:
    ep = Path(ep).resolve()
    ledger = _ledger_frame(ep, frame)
    review_row = _row_for_frame(ep, frame)
    baseline_compensation = _baseline_network_compensation_ready(ep, int(frame), ledger)
    if not baseline_compensation and not _candidate_lane_ready(ep, frame, review_row, ledger):
        return {"status": "NOT_READY", "frame": frame, "ledger_status": ledger.get("status")}
    active = active_candidate(ep, frame)
    if active:
        return {"status": "REUSED", "frame": frame, "queue_item_id": active.get("id"), "queue_status": active.get("status")}
    used = successful_slots(ep, frame)
    maximum = max_additional_candidates_per_frame()
    if used >= maximum:
        return {"status": "EXHAUSTED", "frame": frame, "used": used, "max": maximum}
    slot = used + 1
    if baseline_compensation and slot != 1:
        return {"status": "EXHAUSTED", "frame": frame, "used": used, "max": 1}
    prompt_dir = ep / "prompts" / "visual-lock-candidates"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / f"{int(frame):02d}-{CANDIDATE_POLICY_REVISION}-candidate-{slot}.txt"
    prompt_path.write_text(candidate_prompt(ep, frame, slot) + "\n", encoding="utf-8", newline="\n")
    import image_scheduler
    policy = image_model_policy.for_episode(ep)
    refs = image_scheduler.contract_references(ep, frame, scope="repair")
    if baseline_compensation:
        import production_ledger_manage
        production_ledger_manage.mark_review_needs_user(
            ep, frame, reason="Visual Lock independent V-B pixel FAIL; "
            "only one generated pixel after a verifiable native network error; "
            "bounded delegated content repair, no weak PASS.")
    item = image_scheduler.add_item(
        ep,
        frame=int(frame),
        kind="baseline_candidate",
        prompt_file=prompt_path,
        scope="repair",
        references=refs,
        capture_id=f"visual-lock-candidate-{CANDIDATE_POLICY_REVISION}-{int(frame):02d}-{slot:02d}",
        model=policy["model"],
        quality=policy["quality"],
        strict_model=bool(policy.get("strict_model")),
        depends_on=[] if baseline_compensation else [baseline_frame(ep)],
        replace=True,
    )
    if baseline_compensation:
        with scheduler_core.queue_transaction(ep):
            queue = scheduler_core.load_queue(ep)
            row = next(x for x in queue.get("items") or [] if x.get("id") == item["id"])
            row["generation_attempt_reason"] = "VISUAL_LOCK_CONTENT_REPAIR"
            row["baseline_content_compensation"] = "VERIFIED_NATIVE_NETWORK_FAILURE_ATTEMPT1"
            scheduler_core.save_queue(ep, queue)
    return {
        "status": "PASS",
        "frame": int(frame),
        "slot": slot,
        "max": maximum,
        "queue_item_id": item.get("id"),
        "prompt_file": item.get("prompt_file"),
        "content_repairs_used": int(ledger.get("content_repairs_used") or 0),
    }


def enqueue_ready(ep: Path) -> dict:
    frames = prepareable_frames(ep)
    rows = [enqueue_frame(ep, frame) for frame in frames]
    return {"status": "PASS" if rows else "REUSED", "frames": frames, "candidates": rows}


def review_attempt(ep: Path) -> int:
    base = 2
    slots = 0
    for row in failed_rows(ep):
        try:
            frame = int(row.get("frame"))
        except Exception:
            continue
        if frame == baseline_frame(ep):
            continue
        # Review attempt numbers must never go backwards when a prompt policy
        # revision opens a fresh bounded candidate epoch.
        slots = max(slots, historical_successful_slots(ep, frame))
    return base + slots


def self_test() -> None:
    assert max_additional_candidates_per_frame() >= 0
    print("VISUAL LOCK CANDIDATE POOL SELF-TEST PASS")


if __name__ == "__main__":
    self_test()
