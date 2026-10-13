"""R8 Frame01 diagnosis: distinguish legacy UNKNOWN recovery from fresh visual lock."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_canary as canary
from test_storyos_autonomy_r3_canary import healthy,baseline
from test_storyos_autonomy_watchdog_common import EP

def _setup(monkeypatch,ep):
    monkeypatch.setattr(canary.native,"canonical_episode",lambda _:canary.native.ROOT/ep)
    monkeypatch.setattr(canary.native,"native_environment",lambda:{})
    monkeypatch.setattr(canary.native,"preflight",lambda *a,**k:healthy())
    monkeypatch.setattr(canary.native_cli,"report",lambda:{
       "status":"NATIVE_AUTH_CONTEXT_READY","model_calls":0,"sql_writes":0,
       "may_start_paid_production":False,"cli_runner_same_binary_verified":True,
       "opencodex_used":False})

def test_nonlegacy_storyboard_does_not_probe_one_off_unknown_recovery(monkeypatch):
    _setup(monkeypatch,EP)
    report=healthy()
    report["visual_lock_admission"]={"status":"BLOCKED","reason":"OFFICIAL_VISUAL_LOCK_FOUR_FRAME_PLAN_MISSING_OR_DRIFTED","read_only":True}
    monkeypatch.setattr(canary.native,"preflight",lambda *a,**k:report)
    monkeypatch.setattr(canary.native,"_probe",lambda *a,**k:(_ for _ in ()).throw(AssertionError("legacy called")))
    result=canary.plan(EP)
    assert result["status"]=="BLOCKED"
    assert result["reason"]=="OFFICIAL_VISUAL_LOCK_FOUR_FRAME_PLAN_MISSING_OR_DRIFTED"
    assert result["can_dispatch_image"] is False
    assert result["model_calls"]==0

def test_nonlegacy_complete_visual_plan_is_not_payment_permission(monkeypatch):
    _setup(monkeypatch,EP)
    report=healthy()
    report["visual_lock_admission"]={"status":"REVIEW_PASS_REQUIRES_INDEPENDENT_PROVENANCE",
                                     "reason":"REVIEW_PASS_DOES_NOT_PROVE_NATIVE_IMAGE_TOOL_ENTITLEMENT","read_only":True}
    monkeypatch.setattr(canary.native,"preflight",lambda *a,**k:report)
    monkeypatch.setattr(canary.native,"_probe",lambda *a,**k:(_ for _ in ()).throw(AssertionError("legacy called")))
    result=canary.plan(EP)
    assert result["status"]=="EVIDENCE_ONLY"
    assert result["can_dispatch_image"] is False
    assert result["model_entitlement_verified"] is False


def test_genuine_episode_specific_four_frame_selection_is_valid():
    """Anomaly frame may be #5 or #3, never hardcode frame #8 globally."""
    import importlib.util
    module_path=ROOT/"scripts"/"storyos_visual_lock_readonly.py"
    spec=importlib.util.spec_from_file_location("r8_visual_lock",module_path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    names=["ordinary_baseline","worst_capture_condition","first_major_anomaly","high_impact_admission"]
    for frames in ([1,16,5,17],[1,3,5,15],[1,12,3,15]):
        plan={"schema_version":1,"items":[{"frame":frame,"role":name} for frame,name in zip(frames,names)]}
        out=mod.classify(stage="STORYBOARD_LOCKED",attempt_status="ATTEMPT_HISTORY_READ_ONLY",
                         reviews={"visual_admission":"pending"},plan=plan,calibration={})
        assert out["reason"]=="REAL_NATIVE_IMAGE_PIXEL_PROOF_NOT_YET_ESTABLISHED"
        assert out["admission_frames"]==frames
        assert out["model_entitlement_verified"] is False

def test_visual_lock_rejects_duplicate_or_out_of_bounds_frame():
    import importlib.util
    spec=importlib.util.spec_from_file_location("r8_visual_lock2",ROOT/"scripts"/"storyos_visual_lock_readonly.py")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    names=["ordinary_baseline","worst_capture_condition","first_major_anomaly","high_impact_admission"]
    for frames in ([1,16,16,17],[1,16,21,17],[1,16,True,17],[2,16,5,17]):
        plan={"schema_version":1,"items":[{"frame":f,"role":name} for f,name in zip(frames,names)]}
        out=mod.classify(stage="STORYBOARD_LOCKED",attempt_status="ATTEMPT_HISTORY_READ_ONLY",
                         reviews={},plan=plan,calibration={})
        assert out["reason"]=="OFFICIAL_VISUAL_LOCK_FOUR_FRAME_PLAN_MISSING_OR_DRIFTED"

def test_real_legacy_scope_uses_original_strict_unknown_path(monkeypatch):
    episode="episodes/00_独立篇/06_五十亩山地之后_全新重制"
    _setup(monkeypatch,episode)
    inputs=[]
    monkeypatch.setattr(canary.native,"_probe",lambda env,script,args:(inputs.append(script) or (0,baseline())))
    result=canary.plan(episode)
    assert any("storyos_native_frame01_preflight.py" in x for x in inputs)
    assert result["status"]=="EVIDENCE_ONLY"
