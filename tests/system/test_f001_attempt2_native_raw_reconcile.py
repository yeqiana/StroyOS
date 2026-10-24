"""F001 native RAW vs NP01 output: fail closed and preserve paid history."""
import copy
import hashlib
import json
import sys
from pathlib import Path
import pytest
from PIL import Image

SYSTEM=Path(__file__).resolve().parents[2]/"episodes"/"_system"
sys.path.insert(0,str(SYSTEM))
import f001_attempt2_native_raw_reconcile as rec
import production_native_baseline_proof as proof

SHA="a"*64
RID=rec.RID


def episode(tmp_path):
    ep=tmp_path/"episode"
    ep.mkdir()
    (ep/"media/raw").mkdir(parents=True)
    (ep/"media/candidates/scheduled").mkdir(parents=True)
    raw=ep/"media/raw/raw.png"
    out=ep/"media/candidates/scheduled/candidate.png"
    Image.new("RGB",(1122,1402),(20,40,50)).save(raw)
    Image.open(raw).resize((1080,1350)).save(out)
    log=ep/"meta/image-workers/f001.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text('{"type":"turn.completed"}\n')
    item={"frame":1,"id":"f001","prompt_package":{
        "frame_contract_sha256":SHA,"package_sha256":SHA}}
    lease={"generation_key":"test_generation_key","attempt_index":2,"fencing_token":2}
    return ep,raw,out,log,item,lease


def test_original_archive_verified_not_normalized_candidate(tmp_path,monkeypatch):
    ep,raw,out,log,item,lease=episode(tmp_path)
    seen=[]
    monkeypatch.setattr(proof,"observe_real_tool_pixel",lambda *_:None)
    def direct(logpath,pixel,rid):
        seen.append(Path(pixel).resolve())
        return {"proof_kind":"TRUSTED_NATIVE_DIRECT_THREAD_SCOPED_IMAGE_SHA",
                "pixel_sha256":hashlib.sha256(Path(pixel).read_bytes()).hexdigest(),
                "review_pass":False}
    monkeypatch.setattr(proof,"verify_direct_runner_archived_pixel",direct)
    monkeypatch.setattr(proof,"admitted_baseline_lease",lambda *_:True)
    result=proof.record_unreviewed_pixel(ep,item,lease,log,out,RID,raw_pixel=raw)
    assert seen==[raw.resolve()]
    assert result["normalized_candidate_sha256"]==hashlib.sha256(out.read_bytes()).hexdigest()
    assert result["native_original_pixel_sha256"]==hashlib.sha256(raw.read_bytes()).hexdigest()
    assert result["review_pass"] is False
    saved=json.loads((ep/"meta/runtime/native-baseline-frame01-tool-proof.json").read_text())
    assert saved["status"]=="OBSERVED_AWAITING_INDEPENDENT_VISUAL_REVIEW"


@pytest.mark.parametrize("bad",["missing_raw","outside_raw_root","raw_symlink","broken_candidate"])
def test_native_raw_selection_fails_closed(tmp_path,monkeypatch,bad):
    ep,raw,out,log,item,lease=episode(tmp_path)
    monkeypatch.setattr(proof,"observe_real_tool_pixel",lambda *_:None)
    monkeypatch.setattr(proof,"admitted_baseline_lease",lambda *_:True)
    monkeypatch.setattr(proof,"verify_direct_runner_archived_pixel",lambda *_:{"proof_kind":"wrong"})
    src=raw
    if bad=="missing_raw":src=ep/"media/raw/missing.png"
    if bad=="outside_raw_root":src=ep/"other.png";src.write_bytes(raw.read_bytes())
    if bad=="raw_symlink":
        src=ep/"media/raw/link.png"
        try:src.symlink_to(raw)
        except OSError:pytest.skip("Windows symlinks not available")
    if bad=="broken_candidate":out.write_bytes(b"not an image")
    with pytest.raises(RuntimeError,match="NATIVE_BASELINE_PIXEL_TOOL_PROOF_UNVERIFIED"):
        proof.record_unreviewed_pixel(ep,item,lease,log,out,RID,raw_pixel=src)


def ledger():
    third={"attempt_id":"a3","kind":"original","result":"technical_failure",
           "runtime_transaction_id":"transaction",
           "request":{"frame":"01","frame_contract_sha256":SHA,
                      "model":"gpt-image-2.5-flare","quality":"high"},
           "error":{"code":"IMAGE_BACKEND_ERROR",
                    "message":rec.SOURCE_ERROR+": RuntimeError"},
           "provider_attempt":{"status":"NOT_INVOKED"}}
    return {"frames":{"01":{"status":"TECH_FAILED","number":1,
           "current_candidate":None,"attempts":[
               {"attempt_id":"a1","result":"technical_failure"},
               {"attempt_id":"a2","result":"technical_failure"},third],
           "technical_failures":[{"attempt_id":"a1"},
                                 {"attempt_id":"a2"},
                                 {"attempt_id":"a3"}]}}}


def source(tmp_path):
    e=tmp_path/"episode";e.mkdir()
    candidate=e/"media/candidates/scheduled/01.png"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"candidate")
    return {"episode":e,"item":{"frame_contract":{"contract_sha256":SHA}},
            "candidate":candidate,"candidate_sha256":"b"*64,
            "raw_sha256":"c"*64,"runner_receipt_sha256":"d"*64,
            "provider_receipt_sha256":"e"*64,"thread_id":"native-thread",
            "proof_kind":"TRUSTED_NATIVE_DIRECT_THREAD_SCOPED_IMAGE_SHA"}


def test_pure_ledger_repair_keeps_two_prior_failures_and_no_review(tmp_path,monkeypatch):
    import production_ledger as core
    monkeypatch.setattr(core,"verify_attempt_visual_provenance",lambda *_:None)
    monkeypatch.setattr(core,"verify_attempt_frame_contract_provenance",lambda *_:None)
    original=ledger();prior=copy.deepcopy(original)
    src=source(tmp_path)
    monkeypatch.setattr(rec,"ROOT",tmp_path)
    new=rec._ledger_repair(original,src)
    assert original==prior
    a=new["frames"]["01"]["attempts"][-1]
    assert new["frames"]["01"]["attempts"][:2]==prior["frames"]["01"]["attempts"][:2]
    assert new["frames"]["01"]["status"]=="ORIGINAL_READY"
    assert a["generation_attempt_index"]==2
    assert a["result"]=="success"
    assert a["recovery_correction"]["review_pass"] is False
    assert a["recovery_correction"]["previous_result"]=="technical_failure"
    assert a["recovery_correction"]["previous_error"]==prior["frames"]["01"]["attempts"][-1]["error"]
    rec._verify_repaired(new,src)


@pytest.mark.parametrize("change",["missing_attempt","wrong_error","provider_marked_completed","wrong_contract"])
def test_pure_ledger_repair_rejects_history_drift(tmp_path,monkeypatch,change):
    import production_ledger as core
    monkeypatch.setattr(core,"verify_attempt_visual_provenance",lambda *_:None)
    monkeypatch.setattr(core,"verify_attempt_frame_contract_provenance",lambda *_:None)
    doc=ledger()
    att=doc["frames"]["01"]["attempts"][-1]
    if change=="missing_attempt":doc["frames"]["01"]["attempts"].pop(0)
    if change=="wrong_error":att["error"]["message"]="provider timeout"
    if change=="provider_marked_completed":att["provider_attempt"]["status"]="COMPLETED"
    if change=="wrong_contract":att["request"]["frame_contract_sha256"]="f"*64
    with pytest.raises(rec.ProvenanceDenied):
        rec._ledger_repair(doc,source(tmp_path))


def test_unreviewed_proof_does_not_claim_visual_pass(tmp_path,monkeypatch):
    ep,raw,out,log,item,lease=episode(tmp_path)
    s={"item":item,"log":log,"raw":raw,"candidate":out,
       "raw_sha256":hashlib.sha256(raw.read_bytes()).hexdigest(),
       "candidate_sha256":hashlib.sha256(out.read_bytes()).hexdigest()}
    monkeypatch.setattr(rec.baseline,"verify_direct_runner_archived_pixel",
                        lambda *_:{"proof_kind":"TRUSTED_NATIVE_DIRECT_THREAD_SCOPED_IMAGE_SHA",
                                   "pixel_sha256":s["raw_sha256"],"review_pass":False})
    rec._create_unreviewed_proof(ep,s)
    proof_path=ep/"meta/runtime/native-baseline-frame01-tool-proof.json"
    value=json.loads(proof_path.read_text(encoding="utf-8"))
    assert value["visual_review_pass"] is False
    assert value["attempt_index"]==2
    assert value["status"]=="OBSERVED_AWAITING_INDEPENDENT_VISUAL_REVIEW"
    rec._create_unreviewed_proof(ep,s)
    value["visual_review_pass"]=True
    proof_path.write_text(json.dumps(value),encoding="utf-8")
    with pytest.raises(rec.ProvenanceDenied,match="PROOF_DRIFT"):
        rec._create_unreviewed_proof(ep,s)


def test_no_sql_or_provider_when_ack_missing(tmp_path):
    with pytest.raises(rec.ProvenanceDenied,match="ACK_REQUIRED"):
        rec.commit(tmp_path,expected_sha=SHA,acknowledged=False)
