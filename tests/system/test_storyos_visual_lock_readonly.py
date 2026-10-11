"""Negative tests: text-only image visibility must never grant generation."""
import importlib.util
from pathlib import Path

FILE=Path(__file__).resolve().parents[2]/"scripts/storyos_visual_lock_readonly.py"
spec=importlib.util.spec_from_file_location("storyos_visual_lock_readonly_test",FILE)
assert spec and spec.loader
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
PLAN={"items":[{"frame":n,"role":role} for n,role in mod.EXPECTED_PLAN]}
REV={"visual_admission":"pending","authenticity":"pending","continuity":"pending"}
CAL={"items":[{"decision":"pending"} for _ in range(4)]}

def check(**updates):
    args={"stage":"STORYBOARD_LOCKED","attempt_status":"ATTEMPT_HISTORY_READ_ONLY",
          "reviews":REV,"plan":PLAN,"calibration":CAL}
    args.update(updates)
    return mod.classify(**args)

def test_real_native_pixel_proof_remains_unverified():
    x=check()
    assert x["status"]=="BLOCKED"
    assert x["reason"]=="REAL_NATIVE_IMAGE_PIXEL_PROOF_NOT_YET_ESTABLISHED"
    assert x["admission_frames"]==[1,16,8,17]
    assert x["pending_admission_items"]==4
    assert x["tool_generation_proven"] is False
    assert x["model_entitlement_verified"] is False
    assert x["model_calls"]==x["sql_writes"]==0
    assert x["image_generation_called"] is False
    assert x["image_attempt_reserved"] is False

def test_ambiguous_attempts_stop_admission_before_anything_else():
    for state in ("OUTCOME_UNKNOWN_BLOCKED","ACTIVE_ATTEMPT_BLOCKED",
                  "UNVERIFIED_ATTEMPT_STATUS_BLOCKED",""):
        x=check(attempt_status=state)
        assert x["reason"]=="GENERATION_ATTEMPT_RECONCILIATION_REQUIRED"
        assert x["status"]=="BLOCKED"

def test_plan_missing_or_reordered_is_blocked():
    for plan in (None,{},{"items":PLAN["items"][:3]},
                 {"items":PLAN["items"][::-1]}):
        x=check(plan=plan)
        assert x["status"]=="BLOCKED"
        assert x["reason"]=="OFFICIAL_VISUAL_LOCK_FOUR_FRAME_PLAN_MISSING_OR_DRIFTED"

def test_earlier_story_stage_is_not_visual_lock_ready():
    for stage in ("IDEA_LOCKED","RELEASED","DRAFT",""):
        x=check(stage=stage)
        assert x["status"]=="NOT_APPLICABLE"
        assert x["tool_generation_proven"] is False

def test_review_pass_does_not_infer_native_image_tool_entitlement():
    x=check(reviews={**REV,"visual_admission":"passed"})
    assert x["status"]=="REVIEW_PASS_REQUIRES_INDEPENDENT_PROVENANCE"
    assert x["tool_generation_proven"] is False
    assert x["model_entitlement_verified"] is False

def test_native_managed_plan_exposes_advisory_without_faking_image_entitlement(monkeypatch):
    from unittest.mock import patch
    import sys
    sys.path.insert(0,str(FILE.parent))
    import storyos_codex_managed as managed
    calls=[]
    def fake(_env,path,args,**_k):
        calls.append(path)
        if path.endswith("runtime_router.py"):
            return 0,{"effective_production_mode":"CODEX_MANAGED","effective_runtime":"CODEX",
                "image_execution_runtime":"CODEX","local_codex_spawn_allowed":True,
                "local_codex_image_spawn_allowed":True,"text_review_runtime":"CODEX",
                "vision_review_runtime":"CODEX","governance_review_runtime":"CODEX"}
        if path.endswith("codex_user_runner.py"):
            return 0,{"status":"ok","codex_available":True,"codex_auth_present":True}
        if path.endswith("storyos_native_model_readiness.py"):
            return 0,{"status":"CLIENT_VERSION_COMPATIBLE"}
        if path.endswith("storyos_revision_schema_readonly.py"):
            return 0,{"status":"READY_FOR_FURTHER_ADMISSION"}
        if path.endswith("storyos_episode_stage_readonly.py"):
            return 0,{"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED","source":"mysql"}
        if path.endswith("storyos_creative_recovery_readonly.py"):
            return 0,{"status":"CONTRACT_ALREADY_LOCKED_VERIFY_STORY_GATES"}
        if path.endswith("storyos_attempt_readonly_preflight.py"):
            return 0,{"status":"ATTEMPT_HISTORY_READ_ONLY"}
        if path.endswith("runtime_driver.py"):
            return 0,{"driver_state":"NEVER_STARTED"}
        if path.endswith("storyos_visual_lock_readonly.py"):
            return 0,{"status":"BLOCKED","reason":"REAL_NATIVE_IMAGE_PIXEL_PROOF_NOT_YET_ESTABLISHED",
                "tool_generation_proven":False,"read_only":True}
        raise AssertionError(path)
    with patch.object(managed,"_probe",side_effect=fake):
        result=managed.preflight({"STORYOS_MYSQL_HOST":"127.0.0.1","STORYOS_MYSQL_PORT":"3307"},
                episode=managed.ROOT/"episodes"/"00_独立篇"/"06_虚拟剧集")
    assert result["status"]=="READY_TO_START"
    assert result["visual_lock_admission"]["status"]=="BLOCKED"
    assert result["codex"]["tool_generation_proven"] is False
    assert result["blockers"]==[]
    assert any(x.endswith("storyos_visual_lock_readonly.py") for x in calls)


def test_native_managed_visual_readonly_checker_fails_closed(monkeypatch):
    from unittest.mock import patch
    import sys
    sys.path.insert(0,str(FILE.parent))
    import storyos_codex_managed as managed
    def fake(_env,path,args,**_k):
        if path.endswith("storyos_visual_lock_readonly.py"):
            return 2,{}
        base={
          "runtime_router.py":(0,{"effective_production_mode":"CODEX_MANAGED",
              "effective_runtime":"CODEX","image_execution_runtime":"CODEX",
              "local_codex_spawn_allowed":True,"local_codex_image_spawn_allowed":True,
              "text_review_runtime":"CODEX","vision_review_runtime":"CODEX","governance_review_runtime":"CODEX"}),
          "codex_user_runner.py":(0,{"status":"ok","codex_available":True,"codex_auth_present":True}),
          "storyos_native_model_readiness.py":(0,{"status":"CLIENT_VERSION_COMPATIBLE"}),
          "storyos_revision_schema_readonly.py":(0,{"status":"READY_FOR_FURTHER_ADMISSION"}),
          "storyos_episode_stage_readonly.py":(0,{"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED"}),
          "storyos_creative_recovery_readonly.py":(0,{}),
          "storyos_attempt_readonly_preflight.py":(0,{"status":"ATTEMPT_HISTORY_READ_ONLY"}),
          "runtime_driver.py":(0,{"driver_state":"NEVER_STARTED"})}
        return next(v for k,v in base.items() if path.endswith(k))
    with patch.object(managed,"_probe",side_effect=fake):
        result=managed.preflight({"STORYOS_MYSQL_HOST":"127.0.0.1","STORYOS_MYSQL_PORT":"3307"},
                                episode=managed.ROOT/"episodes"/"00_独立篇"/"06_虚拟剧集")
    assert result["visual_lock_admission"]["status"]=="BLOCKED"
    assert result["visual_lock_admission"]["reason"]=="VISUAL_LOCK_READONLY_AUTHORITY_CHECK_FAILED"
