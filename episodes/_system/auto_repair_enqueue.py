#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded automatic content-repair enqueue for Story OS image lanes.

This module does not judge pixels and never advances gates/stages. It only turns
an already-verified content failure into the repository's existing one-shot
repair transaction:

ready candidate -> CONTENT_FAILED -> REPAIR_AUTHORIZED -> queued repair item

The Production Ledger remains the repair-budget authority; Image Scheduler
remains the execution authority.
"""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import image_model_policy
import ledger_call
import production_queue_store
import scheduler_core
import story_json
import production_ledger
import runtime_observability

ROOT = Path(__file__).resolve().parents[2]
LEDGER_REL = Path("meta/production-ledger.json")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _read(path: Path) -> dict:
    data = story_json.read_json(path, default={})
    return data if isinstance(data, dict) else {}


def _ledger_frame(ep: Path, frame: int) -> dict:
    data = production_ledger.load_authority(ep, default={}) or {}
    rows = data.get("frames") or {}
    row = rows.get(f"{int(frame):02d}") or rows.get(str(int(frame))) or {}
    return row if isinstance(row, dict) else {}


def _queue_items(ep: Path, frame: int) -> list[dict]:
    q = scheduler_core.load_queue(ep)
    return [
        row for row in (q.get("items") or [])
        if isinstance(row, dict) and int(row.get("frame") or -1) == int(frame)
    ]


def repair_pending(ep: Path, frame: int) -> bool:
    return any(
        row.get("kind") == "repair" and row.get("status") in {"queued", "running", "tech_failed"}
        for row in _queue_items(Path(ep).resolve(), frame)
    )


def generated_repair(ep: Path, frame: int) -> bool:
    return any(
        row.get("kind") == "repair" and row.get("status") == "generated"
        for row in _queue_items(Path(ep).resolve(), frame)
    )


def enqueue_marked_repairs(ep: Path) -> dict:
    """Convert queue ``scout_repair`` markers into executable repair items.

    Production Batch Review/Fast Scout already own the pixel decision. This
    helper only bridges their marker into the existing Ledger + Scheduler
    repair transaction so ``REPAIR_FAILED_IMAGES`` cannot become an empty loop.
    """
    ep = Path(ep).resolve()
    q = scheduler_core.load_queue(ep)
    marked = [row for row in (q.get("items") or []) if isinstance(row, dict) and row.get("status") == "scout_repair"]
    results = []
    supersede_ids: set[str] = set()
    for row in marked:
        frame = int(row.get("frame") or 0)
        if frame <= 0:
            continue
        production_review_marker = (
            str(row.get("scope") or "") in {"batch", "production"}
            or bool(row.get("batch_id"))
            or isinstance(row.get("vision_batch_review"),dict)
            or isinstance(row.get("work_batch_review"),dict)
        )
        if production_review_marker:
            results.append({"status":"DEFERRED_FIRST_PASS_BARRIER","frame":frame,
                            "queue_item_id":row.get("id")})
            continue
        findings: list[str] = []
        for source in (row.get("vision_batch_review"), row.get("work_batch_review"), row.get("scout"), row.get("repair_assessment")):
            if not isinstance(source, dict):
                continue
            findings.extend(str(x) for x in (source.get("issue_codes") or []) if str(x))
            if source.get("reason"):
                findings.append(str(source.get("reason")))
            if source.get("notes"):
                findings.append(str(source.get("notes")))
        result = enqueue(
            ep,
            frame=frame,
            findings=findings,
            source="PRODUCTION_REVIEW",
            review_note="Production actual-pixel review authorized content repair",
        )
        results.append(result)
        if result.get("status") in {"REPAIR_ENQUEUED", "REPAIR_ALREADY_PENDING"}:
            supersede_ids.add(str(row.get("id") or ""))
    if supersede_ids:
        with scheduler_core.queue_transaction(ep):
            latest = scheduler_core.load_queue(ep)
            for row in latest.get("items") or []:
                if str(row.get("id") or "") in supersede_ids and row.get("status") == "scout_repair":
                    row["status"] = "superseded"
                    row["superseded_reason"] = "bounded content repair enqueued"
            scheduler_core.save_queue(ep, latest)
    return {"marked": len(marked), "results": results, "repair_items_ready": sum(r.get("status") in {"REPAIR_ENQUEUED", "REPAIR_ALREADY_PENDING"} for r in results)}


def authority_refresh_prompt(frame: int, frame_contract_sha256: str) -> str:
    contract_sha = str(frame_contract_sha256 or "").strip().lower()
    if not contract_sha:
        raise ValueError("authority refresh requires current frame_contract_sha256")
    text = (
        f"权威刷新Frame{int(frame):02d}，合同指纹={contract_sha[:16]}。上游 Visual Profile / World Identity / Frame Contract 已合法更新。"
        "丢弃旧候选的视觉合同语义，严格按当前 Frame Contract 重新生成同一故事帧；不新增剧情、不把权威刷新当内容返修。"
        "保持人物身份与故事连续性，以当前合同中的拍摄者、设备位置、生活动作、环境物理和视觉档案为唯一生成依据。"
    )
    while len(text) > 250 or len(text.encode("utf-8")) > 860:
        text = text.replace("上游 Visual Profile / World Identity / Frame Contract 已合法更新。", "上游权威合同已合法更新。")
        if len(text) <= 250 and len(text.encode("utf-8")) <= 860:
            break
        text = text[:240]
    return text


def enqueue_authority_refresh(ep: Path, frame: int) -> dict:
    ep = Path(ep).resolve()
    frame = int(frame)
    if repair_pending(ep, frame):
        return {"status": "AUTHORITY_REFRESH_ALREADY_PENDING", "frame": frame}
    ledger = _ledger_frame(ep, frame)
    if str(ledger.get("status") or "") != "AUTHORITY_REFRESH_AUTHORIZED":
        return {"status": "NOT_AUTHORITY_REFRESHABLE", "frame": frame, "ledger_status": ledger.get("status")}
    authority = ledger.get("authority_refresh_authorization") or {}
    contract_sha = str(authority.get("frame_contract_sha256") or "").strip()
    if not contract_sha:
        raise ValueError("authority refresh authorization missing frame_contract_sha256")
    prompt_dir = ep / "prompts" / "authority-refresh"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / f"{frame:02d}-authority-refresh.txt"
    prompt_path.write_text(authority_refresh_prompt(frame, contract_sha) + "\n", encoding="utf-8", newline="\n")

    import image_scheduler
    import visual_lock_baseline_gate
    source_item = _source_item(ep, frame)
    policy = image_model_policy.for_episode(ep)
    # Authority refresh of the ordinary baseline bootstraps a new identity master.
    # It must not depend on the stale master that this refresh is replacing.
    try:
        is_baseline = frame == int(visual_lock_baseline_gate.baseline_frame(ep))
    except Exception:
        is_baseline = False
    refs = [] if is_baseline else image_scheduler.contract_references(ep, frame, scope="repair")
    item = image_scheduler.add_item(
        ep,
        frame=frame,
        kind="repair",
        prompt_file=prompt_path,
        scope="repair",
        references=refs,
        capture_id=f"authority-refresh-{frame:02d}",
        model=policy["model"],
        quality=policy["quality"],
        strict_model=bool(policy.get("strict_model")),
        depends_on=[int(x) for x in (source_item.get("depends_on") or [])],
        # Authority refresh is a new SHA-bound transaction under refreshed
        # upstream authority. Historical generated repairs remain audit evidence
        # but must not dedupe the new request; supersede them in the queue.
        replace=True,
    )
    return {
        "status": "AUTHORITY_REFRESH_ENQUEUED",
        "frame": frame,
        "queue_item_id": item.get("id"),
        "prompt_file": item.get("prompt_file"),
        "content_repairs_used": int(ledger.get("content_repairs_used") or 0),
        "at": now(),
    }


def enqueue_authority_refreshes(ep: Path) -> dict:
    ep = Path(ep).resolve()
    ledger = production_ledger.load_authority(ep, default={}) or {}
    frames = sorted(
        int(key) for key, row in (ledger.get("frames") or {}).items()
        if isinstance(row, dict) and row.get("status") == "AUTHORITY_REFRESH_AUTHORIZED"
    )
    targets = list(frames)
    # When Visual Lock identity bootstrap itself changed authority, regenerate only
    # the ordinary baseline first. The remaining admissions must wait for the new
    # baseline actual-pixel PASS and provisional Pixel Master, exactly like initial
    # production. This prevents stale-master reuse and identity-free dependents.
    try:
        import character_visual_contract
        import visual_lock_baseline_gate
        baseline = int(visual_lock_baseline_gate.baseline_frame(ep))
        if baseline in frames and character_visual_contract.pixel_master_required(ep):
            targets = [baseline]
    except Exception:
        pass
    rows = [enqueue_authority_refresh(ep, frame) for frame in targets]
    return {
        "frames": targets,
        "pending_authority_refresh_frames": frames,
        "results": rows,
        "enqueued": sum(r.get("status") == "AUTHORITY_REFRESH_ENQUEUED" for r in rows),
    }


def review_attempt(ep: Path, frame: int) -> int:
    """Attempt 1 for originals, attempt 2 after the one ordinary repair."""
    row = _ledger_frame(Path(ep).resolve(), frame)
    return 2 if int(row.get("content_repairs_used") or 0) > 0 else 1


def _source_item(ep: Path, frame: int) -> dict:
    rows = [row for row in _queue_items(ep, frame) if row.get("status") == "generated"]
    if not rows:
        rows = _queue_items(ep, frame)
    if not rows:
        raise RuntimeError(f"no queue source item for frame {frame:02d}")
    # Queue order is chronological; a generated repair appended later must win.
    return rows[-1]


def _compact_findings(findings: list[str]) -> str:
    cleaned: list[str] = []
    for raw in findings:
        text = str(raw or "").strip().replace("\n", " ")
        if not text or text in cleaned:
            continue
        cleaned.append(text[:42])
        if len(cleaned) >= 6:
            break
    return "、".join(cleaned) if cleaned else "实际像素审核未通过"


def repair_prompt(
    frame: int,
    findings: list[str],
    *,
    required_visual_cues: list[str] | None = None,
    camera_owner: str = "",
    camera_position: str = "",
) -> str:
    """Short derived prompt with current Frame Contract must-show cues.

    The locked Frame Contract remains the authority. This prompt only lifts the
    concrete visual delta and camera-authorship constraints into the expensive
    retry request so a repair does not lose the exact reason the prior pixels
    failed.
    """
    codes = {str(x or "").strip().upper() for x in findings}
    if codes & {
        "CINEMATIC_CLIMAX_POSTER", "PROMO_FANTASY_COMPOSITION",
        "DOCUMENTARY_REALISM_EXCEEDED", "REALITY_FIRST_FAILURE",
        "SUBJECTS_ARRANGED_FOR_CAMERA", "CINEMATIC_LIGHTING_AND_POLISH",
        "ORDINARY_LIFE_DENSITY_INSUFFICIENT",
    }:
        return (
            f"返修Frame{frame:02d}。保持当前Frame Contract、身份、服装、地点和事件。"
            "人物继续合同里的看云海/聊天/趴栏动作，不看镜头、不排队、不为拍照转身；摄影者边缘袖口/手/设备证据保留。"
            "人物偏在一侧并允许栏杆或衣角遮挡，远景大气雾化减细节；夕阳不要落视觉中心。"
            "强逆光允许天空过曝、人物欠曝或剪影和轻微眩光，禁止HDR、金色轮廓光、对称海报和旅游宣传片质感。"
        )
    focus = _compact_findings(findings)
    cues = [str(x or "").strip() for x in (required_visual_cues or []) if str(x or "").strip()][:3]
    cue_text = "；".join(cues)
    camera_bits = []
    if str(camera_owner or "").strip():
        camera_bits.append(f"持机人={str(camera_owner).strip()}")
    if str(camera_position or "").strip():
        camera_bits.append(f"机位={str(camera_position).strip()}")
    camera_text = "；".join(camera_bits)

    parts = [
        f"返修Frame{frame:02d}。严格保持当前Frame Contract、人物身份/服装/地点/事件与世界设定，不改故事。",
        f"重点修复：{focus}。",
    ]
    if cue_text:
        parts.append(f"像素必须清楚兑现：{cue_text}。")
    if camera_text:
        parts.append(f"摄像机物理必须成立：{camera_text}；不得出现无法解释的全员入镜或幽灵机位。")
    parts.append("普通手机随手拍，自然不对称构图、真实曝光、非电影布光、非海报化；保留生活杂物和有物理原因的轻微摄影瑕疵。")
    text = "".join(parts)

    # Repository generation budget is <=260 chars / <=900 UTF-8 bytes. Trim
    # only secondary prose/findings; never silently drop mandatory visual cues.
    while len(text) > 250 or len(text.encode("utf-8")) > 860:
        if len(focus) > 20:
            focus = focus[:-4]
        elif len(camera_position) > 18:
            camera_position = camera_position[:18]
        elif len(cues) > 2:
            cues = cues[:2]
        else:
            break
        cue_text = "；".join(cues)
        camera_bits = []
        if str(camera_owner or "").strip():
            camera_bits.append(f"持机人={str(camera_owner).strip()}")
        if str(camera_position or "").strip():
            camera_bits.append(f"机位={str(camera_position).strip()}")
        camera_text = "；".join(camera_bits)
        parts = [f"返修Frame{frame:02d}。保持当前Frame Contract，不改故事。", f"重点修复：{focus}。"]
        if cue_text:
            parts.append(f"必须清楚兑现：{cue_text}。")
        if camera_text:
            parts.append(f"摄像机物理：{camera_text}；禁止幽灵机位。")
        parts.append("普通手机随手拍，真实曝光，非电影/海报化。")
        text = "".join(parts)
    return text


def _native_real_attempt_budget_preflight(ep: Path, frame: int) -> dict | None:
    """Read the Generation Attempt authority BEFORE creating a doomed repair.

    The Production Ledger's one content-repair allowance is not another real
    paid image generation allowance. Only GenerationAttempt.remaining may
    grant that. Never reserve, refund or start a provider from here.
    """
    import production_ledger_persistence
    import runtime_router

    if (runtime_router.image_execution_runtime()[0] != "CODEX"
            or production_ledger_persistence.mode() != "mysql"):
        return None
    import generation_attempt_authority as authority
    import logical_asset_identity as identity

    try:
        state=authority.load_asset_state(ep,identity.frame_asset_key(ep,frame))
    except Exception as exc:
        # In native MySQL production, an unavailable budget is an admission
        # block, NOT a fallback to another chargeable repair.
        return {
            "status":"BLOCKED",
            "reason_code":"GENERATION_ATTEMPT_AUTHORITY_UNVERIFIED",
            "frame":frame,"detail":type(exc).__name__,
            "model_calls":0,"attempts_reserved":0,
        }
    if not isinstance(state,dict) or "remaining_attempts" not in state:
        return {"status":"BLOCKED",
                "reason_code":"GENERATION_ATTEMPT_AUTHORITY_UNVERIFIED",
                "frame":frame,"model_calls":0,"attempts_reserved":0}
    if (int(state.get("remaining_attempts") or 0) <= 0
            and state.get("active_attempt_index") is None):
        return {"status":"NEEDS_USER",
                "reason_code":"REAL_IMAGE_ATTEMPT_BUDGET_EXHAUSTED",
                "frame":frame,
                "attempts_consumed":int(state.get("attempts_consumed") or 0),
                "remaining_attempts":0,
                "model_calls":0,"attempts_reserved":0}
    if state.get("active_attempt_index") is not None:
        return {"status":"BLOCKED",
                "reason_code":"GENERATION_ATTEMPT_STILL_ACTIVE",
                "frame":frame,"model_calls":0,"attempts_reserved":0}
    return None


def enqueue(
    ep: Path,
    *,
    frame: int,
    findings: list[str],
    source: str,
    review_note: str,
) -> dict:
    ep = Path(ep).resolve()
    frame = int(frame)
    if repair_pending(ep, frame):
        return {"status": "REPAIR_ALREADY_PENDING", "frame": frame, "attempt": review_attempt(ep, frame)}

    bounded=_native_real_attempt_budget_preflight(ep,frame)
    if bounded is not None:
        return bounded

    ledger = _ledger_frame(ep, frame)
    status = str(ledger.get("status") or "")
    if status == "REPAIR_READY":
        # A repaired candidate failed content review. The ordinary one-shot
        # budget is exhausted; Production Ledger must move it to NEEDS_USER.
        ok, msg = ledger_call.review(
            ep, frame=frame, decision="repair", notes=review_note,
            prevent_exhaustion_force_pass=True,
        )
        return {"status": "NEEDS_USER" if ok else "ERROR", "frame": frame, "ledger": msg[-800:]}

    if status == "ORIGINAL_READY":
        ok, msg = ledger_call.review(
            ep, frame=frame, decision="repair", notes=review_note,
            prevent_exhaustion_force_pass=True,
        )
        if not ok:
            return {"status": "ERROR", "frame": frame, "ledger": msg[-800:]}
        status = str(_ledger_frame(ep, frame).get("status") or "")

    if status == "CONTENT_FAILED":
        ok, msg = ledger_call.authorize_repair(
            ep,
            frame=frame,
            note=f"{source}: delegated actual-pixel critic authorized one bounded content repair",
            delegated_auto=True,
        )
        if not ok:
            return {"status": "ERROR", "frame": frame, "ledger": msg[-800:]}
        status = str(_ledger_frame(ep, frame).get("status") or "")

    if status not in {"REPAIR_AUTHORIZED", "EXCEPTION_REPAIR_AUTHORIZED", "USER_CONTINUATION_REPAIR_AUTHORIZED"}:
        return {"status": "NOT_REPAIRABLE", "frame": frame, "ledger_status": status}

    exception_repair = status == "EXCEPTION_REPAIR_AUTHORIZED"
    continuation_repair = status == "USER_CONTINUATION_REPAIR_AUTHORIZED"
    prompt_dir = ep / "prompts" / "repairs"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    if continuation_repair:
        continuation_index = int(ledger.get("user_continuation_repairs_used") or 0) + 1
        suffix = f"user-continuation-{continuation_index:02d}"
    else:
        suffix = "user-exception-a3" if exception_repair else "a2"
    prompt_path = prompt_dir / f"{frame:02d}-{source.lower().replace('_', '-')}-{suffix}.txt"
    contract = _read(ep / "meta" / "runtime" / "contracts" / "frames" / f"{frame:02d}.json")
    material = contract.get("hash_material") or {}
    directive = material.get("frame_directive") or {}
    capture = material.get("capture_event") or {}
    prompt_started = time.monotonic()
    prompt_path.write_text(
        repair_prompt(
            frame,
            findings,
            required_visual_cues=list(directive.get("required_visual_cues") or []),
            camera_owner=str(capture.get("photographer_id") or ""),
            camera_position=str(capture.get("device_position") or ""),
        ) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    try:
        import logical_asset_identity
        runtime_observability.safe_record_runtime_event(
            ep,"REPAIR_PROMPT_FINISHED",episode_id=logical_asset_identity.episode_id(ep),
            step="REPAIR_PROMPT",logical_asset_key=logical_asset_identity.frame_asset_key(ep,frame),
            frame_id=f"{frame:02d}",generation_key=f"{source}:{suffix}",
            duration_ms=(time.monotonic()-prompt_started)*1000,status="written",
            source="auto_repair_enqueue",evidence_ref=str(prompt_path.relative_to(ROOT)))
    except Exception:
        pass

    # Local import avoids a baseline_gate <-> image_scheduler import cycle.
    import image_scheduler

    source_item = _source_item(ep, frame)
    policy = image_model_policy.for_episode(ep)
    refs = image_scheduler.contract_references(ep, frame, scope="repair")
    item = image_scheduler.add_item(
        ep,
        frame=frame,
        kind="repair",
        prompt_file=prompt_path,
        scope="repair",
        references=refs,
        capture_id=(
            f"user-continuation-{source}-{frame:02d}-{continuation_index:02d}" if continuation_repair
            else (f"user-exception-{source}-{frame:02d}" if exception_repair else f"auto-repair-{source}-{frame:02d}")
        ),
        model=policy["model"],
        quality=policy["quality"],
        strict_model=bool(policy.get("strict_model")),
        depends_on=[int(x) for x in (source_item.get("depends_on") or [])],
        # Every authorized repair is a new semantic transaction. Historical
        # generated repairs (including authority refreshes) are audit evidence,
        # not reusable queue identity for a later content repair. repair_pending()
        # already prevents duplicate queued/running work for the same frame.
        replace=True,
    )
    return {
        "status": "REPAIR_ENQUEUED",
        "frame": frame,
        "queue_item_id": item.get("id"),
        "prompt_file": item.get("prompt_file"),
        "ledger_status": str(_ledger_frame(ep, frame).get("status") or ""),
        "at": now(),
    }


def self_test() -> None:
    prompt = repair_prompt(1, ["reality_first", "not_cinematic", "capture_credibility"])
    assert len(prompt) <= 260
    assert len(prompt.encode("utf-8")) <= 900
    assert "Frame01" in prompt and "不改故事" in prompt and "天界" not in prompt
    grounded = repair_prompt(
        3,
        ["ANOMALY_NOT_READABLE", "POV_RECORDER_OBVIOUSLY_ILLEGAL"],
        required_visual_cues=["dust-covered furniture", "clean enamel tea mug containing fresh water"],
        camera_owner="P01",
        camera_position="doorway chest height",
    )
    assert "dust-covered furniture" in grounded and "clean enamel tea mug containing fresh water" in grounded
    assert "持机人=P01" in grounded and "禁止幽灵机位" in grounded and "天界" not in grounded
    assert len(grounded) <= 260 and len(grounded.encode("utf-8")) <= 900
    anti_poster = repair_prompt(17, ["PROMO_FANTASY_COMPOSITION", "SUBJECTS_ARRANGED_FOR_CAMERA"])
    assert len(anti_poster) <= 260 and len(anti_poster.encode("utf-8")) <= 900
    assert "不看镜头" in anti_poster and "夕阳不要落视觉中心" in anti_poster and "禁止HDR" in anti_poster
    refresh = authority_refresh_prompt(5, "abc123")
    assert len(refresh) <= 260 and len(refresh.encode("utf-8")) <= 900
    assert "Frame05" in refresh and "权威刷新" in refresh and "abc123" in refresh
    assert authority_refresh_prompt(5, "abc123") != authority_refresh_prompt(5, "def456")
    print("AUTO REPAIR ENQUEUE SELF-TEST PASS")


if __name__ == "__main__":
    self_test()
