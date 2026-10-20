"""Reference slots and SHA identity must survive Controller/Provider handoff."""
from __future__ import annotations
import hashlib
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import image_worker_pool as pool
import image_scheduler as scheduler


def test_two_identity_overlays_before_capture_style():
    selected=scheduler._merge_execution_references(
        [{"path":"master.png","kind":"identity","role":"P01"}],
        [{"path":"look.png","kind":"capture_style","role":"style"},
         {"path":"p02.png","kind":"identity","role":"P02"}])
    assert [row["path"] for row in selected]==["master.png","p02.png"]


def test_binding_rejects_duplicate_or_overbudget(tmp_path):
    p=tmp_path/"identity.png"
    p.write_bytes(b"original-reference-bytes")
    with pytest.raises(ValueError,match="DUPLICATE_SOURCE"):
        pool._payload_reference_evidence(tmp_path,tmp_path,[p,p])
    with pytest.raises(ValueError,match="BUDGET_EXCEEDED"):
        pool._payload_reference_evidence(tmp_path,tmp_path,[p,p,p])


def test_role_kind_and_source_sha_must_match(tmp_path):
    p=tmp_path/"identity.png"
    p.write_bytes(b"original-reference-bytes")
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    rows=pool._payload_reference_evidence(tmp_path,tmp_path,[p],
        declarations=[{"path":"identity.png","sha256":sha,
                       "role":"P01","kind":"identity"}])
    assert rows == [{"path":"identity.png","authority_id":None,
                     "sha256":sha,"role":"P01","kind":"identity"}]
    with pytest.raises(ValueError,match="SOURCE_SHA_DRIFT"):
        pool._payload_reference_evidence(tmp_path,tmp_path,[p],
            declarations=[{"path":"identity.png","sha256":"0"*64,
                           "role":"P01","kind":"identity"}])
    with pytest.raises(ValueError,match="ROLE_KIND_INVALID"):
        pool._payload_reference_evidence(tmp_path,tmp_path,[p],
            declarations=[{"path":"identity.png","sha256":sha,
                           "role":"style","kind":"wrong"}])
