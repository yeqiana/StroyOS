"""Evidence-preserving PREIMAGE -> Visual Lock derived contract reconciliation.

Runs only in an explicitly started Driver, never at read-only admission.
Old SHA->current must be a proven monotonic machine projection for *each*
frame. Rebuilds derived caches/index and official pending Visual Lock plan,
but never touches Story, PREIMAGE authority, prompts, queue or real Attempts.
"""
from __future__ import annotations

from pathlib import Path

import frame_contract
import preimage_authority_snapshot
import preimage_protocol
import story_json
import runtime_atomic_store


class RebindBlocked(RuntimeError):
    pass


def _read(path: Path) -> dict:
    d=story_json.read_json(path,default={})
    return d if isinstance(d,dict) else {}


def _role_frame(row: dict) -> tuple[str,int]:
    return str(row.get("role") or ""),int(row["frame"])


def _queue_guard(ep: Path, plan: dict, current_sha: dict[int,str]) -> dict:
    import scheduler_core
    import generation_attempt_authority as attempts
    import prompt_package

    rows=(scheduler_core.load_queue(ep).get("items") or [])
    selected={int(row["frame"]) for row in plan["items"]}
    originals=[row for row in rows if row.get("scope")=="visual_lock"
               and row.get("kind")=="original"
               and str(row.get("status") or "")!="superseded"]
    if originals and (len(originals)!=4 or
                      {int(row.get("frame") or 0) for row in originals}!=selected):
        raise RebindBlocked("VISUAL_QUEUE_FRAME_IDENTITY_DRIFT_OR_DUPLICATE")
    by_frame={int(row["frame"]):row for row in originals}
    for frame in selected:
        state=attempts.load_asset_state(ep,attempts.frame_key(ep,frame))
        if (int(state.get("attempts_consumed") or 0)!=0
                or state.get("active_attempt_index") is not None):
            raise RebindBlocked(f"IMAGE_ATTEMPT_NOT_PREDISPATCH:{frame:02d}")
        row=by_frame.get(frame)
        if row is None:
            continue
        if (row.get("status") not in {"queued","blocked"}
                or row.get("output_path") or row.get("candidate_output_path")
                or (row.get("execution") and
                    not (row.get("status")=="blocked"
                         and (row.get("execution") or {}).get("phase")=="BLOCKED"))
                or (row.get("status")=="blocked" and
                    row.get("technical_failure_code")!="LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN")):
            raise RebindBlocked(f"VISUAL_QUEUE_NOT_PREDISPATCH:{frame:02d}")
        expected=current_sha[frame]
        prompt=Path(frame_contract.ROOT)/str(row.get("prompt_file") or "")
        if not prompt.is_file():
            raise RebindBlocked(f"VISUAL_QUEUE_PROMPT_MISSING:{frame:02d}")
        pkg=prompt_package.compile_frame(ep,frame,prompt,write=False)
        if (str((row.get("frame_contract") or {}).get("contract_sha256") or "")!=expected
                or str((row.get("prompt_package") or {}).get("frame_contract_sha256") or "")!=expected
                or str((row.get("prompt_package") or {}).get("package_sha256") or "")!=
                   str(pkg.get("package_sha256") or "")):
            raise RebindBlocked(f"VISUAL_QUEUE_CONTRACT_STALE:{frame:02d}")
    return {"rows_reused":len(originals),"attempts_reserved":0}


def reconcile(ep: Path, *, dry_run: bool = False) -> dict:
    import episode_state_persistence
    import visual_lock_v21

    ep=Path(ep).resolve()
    if (episode_state_persistence.load(ep) or {}).get("current_state")!="STORYBOARD_LOCKED":
        raise RebindBlocked("VISUAL_STAGE_NOT_STORYBOARD_LOCKED")
    old_plan=_read(ep/"meta/visual-lock-plan.json")
    if not old_plan:
        return {"status":"NO_EXISTING_VISUAL_PLAN"}
    if old_plan.get("production_revision_id"):
        raise RebindBlocked("FROZEN_PRODUCTION_REVISION_REBIND_UNSUPPORTED")
    items=old_plan.get("items") or []
    if (len(items)!=4 or len({_role_frame(r) for r in items})!=4
            or len({int(r["frame"]) for r in items})!=4
            or tuple(str(r.get("role") or "") for r in items)!=
               ("ordinary_baseline","worst_capture_condition",
                "first_major_anomaly","high_impact_admission")):
        raise RebindBlocked("FROZEN_VISUAL_PLAN_SHAPE_INVALID")
    gates=_read(ep/"meta/story-gates.json")
    cal=(((gates.get("visual") or {}).get("calibration") or {}).get("items") or [])
    # Once both the index and pending plan/calibration are current, this is
    # a no-op even if real pixels have since been reviewed. In the narrow
    # index-committed/plan-pending crash window, the old plan is still repaired.
    if not frame_contract.verify_all(ep):
        current_plan_shas={
            int(row["frame"]):frame_contract.compile_frame(
                ep,int(row["frame"]),write_cache=False)["contract_sha256"]
            for row in items}
        if (all(str(row.get("contract_sha256") or "")==
                current_plan_shas[int(row["frame"])] for row in items)
                and (all(str(row.get("frame_contract_sha256") or "")==
                         current_plan_shas.get(int(row.get("frame") or 0))
                         for row in cal)
                     or (gates.get("reviews") or {}).get("visual_admission")=="passed")):
            return {"status":"ALREADY_CURRENT","image_generation_called":False,
                    "authority_edited":False}
    if (len(cal)!=4 or
            any(not isinstance(x,dict) or x.get("decision")!="pending"
                or x.get("asset_path") or x.get("sha256") for x in cal) or
            {(str(x.get("role") or ""),int(x.get("frame") or 0)) for x in cal}!=
            {_role_frame(x) for x in items} or
            (gates.get("reviews") or {}).get("visual_admission")!="pending"):
        raise RebindBlocked("VISUAL_PIXELS_OR_REVIEW_ALREADY_STARTED")

    snap=_read(ep/"meta/runtime/preimage-committed-snapshot.json")
    if (snap.get("snapshot_kind")!="PREIMAGE_COMMITTED_SNAPSHOT"
            or not preimage_protocol.barrier_ready(ep)
            or preimage_authority_snapshot.stale_owned(ep,snap)):
        raise RebindBlocked("PREIMAGE_OWNED_AUTHORITY_NOT_FROZEN")
    old_idx=_read(ep/frame_contract.INDEX_REL)
    total=frame_contract.frame_count(ep)
    rows=old_idx.get("frames")
    if (not isinstance(rows,list) or len(rows)!=total or
            old_idx.get("index_sha256")!=frame_contract.sha256_json(rows) or
            [str(x.get("frame") or "") for x in rows]!=
            [f"{n:02d}" for n in range(1,total+1)]):
        raise RebindBlocked("OLD_FRAME_INDEX_NOT_CANONICAL")
    before={n:str(rows[n-1].get("contract_sha256") or "") for n in range(1,total+1)}
    current={}
    changed=[]
    for frame in range(1,total+1):
        c=frame_contract.compile_frame(ep,frame,write_cache=False)
        current[frame]=str(c["contract_sha256"])
        old_sha=before[frame]
        if old_sha!=current[frame]:
            if not frame_contract.equivalent_to_current(ep,frame,old_sha,current=c):
                raise RebindBlocked(f"NOT_A_MONOTONIC_VISUAL_PROJECTION:{frame:02d}")
            changed.append(frame)
    # A crash after atomically replacing the index but before replacing the
    # plan leaves the old four SHA bindings. Admit that exact restart only if
    # each plan/calibration SHA is itself a proven historical machine-only
    # projection, and the index SHA already equals the current full contract.
    for row in items:
        n=int(row["frame"])
        previous=str(row.get("contract_sha256") or "")
        if previous!=before[n]:
            if before[n]!=current[n] or not frame_contract.equivalent_to_current(
                    ep,n,previous):
                raise RebindBlocked("OLD_VISUAL_PLAN_NOT_BOUND_TO_INDEX")
    for row in cal:
        n=int(row["frame"])
        previous=str(row.get("frame_contract_sha256") or "")
        if previous!=before[n]:
            if before[n]!=current[n] or not frame_contract.equivalent_to_current(
                    ep,n,previous):
                raise RebindBlocked("OLD_CALIBRATION_NOT_BOUND_TO_INDEX")
    plan_refresh=any(str(row.get("contract_sha256") or "")!=current[int(row["frame"])]
                     for row in items)
    cal_refresh=any(str(row.get("frame_contract_sha256") or "")!=current[int(row["frame"])]
                    for row in cal)
    queue=_queue_guard(ep,old_plan,current)
    if not changed and not plan_refresh and not cal_refresh:
        return {"status":"ALREADY_CURRENT","index_frames":total,**queue}
    # Revalidate all owned PREIMAGE source hashes before the first mutation.
    if preimage_authority_snapshot.stale_owned(ep,snap):
        raise RebindBlocked("PREIMAGE_CHANGED_DURING_REBIND")

    if dry_run:
        return {"status":"DERIVED_REBIND_READONLY_READY",
                "frames_requiring_projection":changed,
                "visual_frames":[int(row["frame"]) for row in items],
                "preimage_owned_sha_verified":True,
                "model_calls":0,"sql_writes":0,
                "image_attempts_reserved":0,
                "image_generation_called":False}
    if changed:
        frame_contract.compile_all(ep)  # canonical cache + index; all 48, not only four
    candidate=visual_lock_v21.choose_plan(ep)
    if ([_role_frame(x) for x in candidate["items"]] !=
            [_role_frame(x) for x in items] or
            any(str(x["contract_sha256"])!=current[int(x["frame"])]
                for x in candidate["items"])):
        raise RebindBlocked("VISUAL_SELECTOR_CHANGED_AFTER_INDEX_REBUILD")
    # Original user/story/visual locks and queued image requests remain intact.
    # Only the official pending calibration/plan is rederived.
    visual_lock_v21.prepare(ep)
    actual=_read(ep/"meta/visual-lock-plan.json")
    if any(str(x.get("contract_sha256") or "")!=current[int(x["frame"])]
           for x in actual.get("items") or []):
        raise RebindBlocked("VISUAL_PLAN_REBIND_POSTCONDITION_FAILED")
    if frame_contract.verify_all(ep):
        raise RebindBlocked("FRAME_CONTRACT_REBIND_POSTCONDITION_FAILED")
    if preimage_authority_snapshot.stale_owned(ep,snap):
        raise RebindBlocked("PREIMAGE_CHANGED_AFTER_REBIND")
    audit=ep/"meta/runtime/visual-lock-contract-rebind.json"
    receipt={"schema_version":1,"status":"REBOUND_DERIVED_ONLY",
             "preimage_snapshot_id":snap.get("snapshot_id"),
             "old_index_sha256":old_idx["index_sha256"],
             "new_index_sha256":_read(ep/frame_contract.INDEX_REL).get("index_sha256"),
             "frames_rebound":changed,"visual_frames":[int(x["frame"]) for x in items],
             "old_visual_contract_sha256":{str(x["frame"]):x["contract_sha256"] for x in items},
             "new_visual_contract_sha256":{str(x["frame"]):current[int(x["frame"])] for x in items},
             "authority_edited":False,"pixels_accepted":False,
             "image_generation_called":False,**queue}
    runtime_atomic_store.atomic_write_json(audit,receipt)
    return receipt
