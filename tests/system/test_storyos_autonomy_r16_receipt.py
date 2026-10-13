"""R16 slot1: SHA-bound native Runner receipt is never a replay permit."""
from pathlib import Path
import base64
import hashlib
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_a9_receipt_reconcile as r

def sample(code=124,timeout=True):
    out=b'provider finalized unknown'
    rid="a"*32
    return {"request_id":rid,"returncode":code,
            "output_bytes":len(out),
            "output_sha256":hashlib.sha256(out).hexdigest(),
            "output_base64":base64.b64encode(out).decode(),
            "evidence":{"request_id":rid,"task_type":"critic",
                        "transport_route":"native_codex",
                        "working_directory":str(ROOT),
                        "stdin_sha256":"b"*64,
                        "returncode":code,"timed_out":timeout}}
def status(row):
    return r.classify_receipt(row,prompt_sha256="b"*64,root=ROOT)

def test_timed_out_900s_native_paid_call_never_retries():
    assert status(sample())=="PAID_CRITIC_TIMEOUT_NO_AUTORETRY"

def test_provider_success_evidence_never_promotes_a_candidate_to_pass():
    assert status(sample(0,False))=="RUNNER_SUCCEEDED_REQUIRES_CANONICAL_FINALIZATION"

def test_other_codex_requests_cannot_be_borrowed_to_unlock_a9():
    bad=sample();bad["evidence"]["stdin_sha256"]="c"*64
    assert status(bad)=="RUNNER_RECEIPT_NOT_SHA_BOUND"
    bad=sample();bad["evidence"]["transport_route"]="opencodex"
    assert status(bad)=="RUNNER_RECEIPT_NOT_SHA_BOUND"

def test_corrupt_or_disagreeing_runner_receipt_is_quarantined():
    bad=sample();bad["output_sha256"]="0"*64
    assert status(bad)=="RUNNER_OUTPUT_INTEGRITY_INVALID"
    bad=sample();bad["evidence"]["returncode"]=0
    assert status(bad)=="RUNNER_RECEIPT_CONTRADICTORY"
