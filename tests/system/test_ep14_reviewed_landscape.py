"""Offline: Episode14 visual-inspection-bound editor reframing, never billed."""
from pathlib import Path
import hashlib
import sys
import pytest
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"episodes/_system")]
import production_ep14_reviewed_landscape as editorial
import image_unknown_raw_reconcile as recovery
import canvas_normalize

def _fixture(tmp_path,monkeypatch,frame=22):
    root=tmp_path
    monkeypatch.setattr(editorial,"ROOT",root)
    monkeypatch.setattr(editorial,"EP",root/"episodes"/"00_独立篇"/
                        "14_深渊疗愈所_第一集_净土生命还原")
    ep=editorial.EP
    raw=ep/"media/raw"/f"{frame:02d}-original.png"
    raw.parent.mkdir(parents=True)
    Image.new("RGB",(1448,1086),"grey").save(raw)
    sha=hashlib.sha256(raw.read_bytes()).hexdigest()
    _,box,note=editorial.PROOFS[frame]
    monkeypatch.setitem(editorial.PROOFS,frame,(sha,box,note))
    receipt={"raw_sha256":sha,"requested_canvas":{"width":1080,"height":1350}}
    return ep,raw,receipt

@pytest.mark.parametrize("frame",[22,39,40])
def test_frozen_crops_are_exact_4_to_5_and_keep_authority(frame,tmp_path,monkeypatch):
    ep,raw,receipt=_fixture(tmp_path,monkeypatch,frame)
    assert editorial.verify_original(ep,frame,raw,receipt,0.666666667)
    out=ep/"media/candidates/scheduled"/f"{frame:02d}-review.png"
    result=editorial.normalize_verified(ep,frame,raw,out,1080,1350)
    assert result["original_raw_sha256"]==receipt["raw_sha256"]
    assert result["user_approved"] is False
    assert result["requires_independent_vision_review"] is True
    assert result["crop_box"]==list(editorial.PROOFS[frame][1])
    with Image.open(out) as im:
        assert im.size==(1080,1350)
        im.verify()
    assert hashlib.sha256(raw.read_bytes()).hexdigest()==receipt["raw_sha256"]
    with pytest.raises(canvas_normalize.NormalizeError,match="candidate exists"):
        editorial.normalize_verified(ep,frame,raw,out,1080,1350)

def test_scope_raw_tamper_canvas_and_unsupported_frames_fail_closed(tmp_path,monkeypatch):
    ep,raw,receipt=_fixture(tmp_path,monkeypatch)
    assert not editorial.is_scoped(ep,23)
    assert not editorial.is_scoped(ep.parent/"13_失物归还的那扇门",22)
    assert not editorial.verify_original(ep,22,raw,{**receipt,"raw_sha256":"0"*64},2/3)
    assert not editorial.verify_original(ep,22,raw,receipt,0.4)
    assert not editorial.verify_original(ep,22,raw,{
        **receipt,"requested_canvas":{"width":1080,"height":1080}},2/3)
    raw.write_bytes(b"tampered")
    assert not editorial.verify_original(ep,22,raw,receipt,2/3)

def test_cropped_raw_cannot_override_ep_canvas_or_set_unapproved_box(tmp_path,monkeypatch):
    ep,raw,receipt=_fixture(tmp_path,monkeypatch)
    out=ep/"media/candidates/scheduled/22-reviewed.png"
    with pytest.raises(canvas_normalize.NormalizeError,match="approved Episode14 canvas"):
        editorial.normalize_verified(ep,22,raw,out,1080,1080)
    _,box,note=editorial.PROOFS[22]
    monkeypatch.setitem(editorial.PROOFS,22,(receipt["raw_sha256"],(0,0,1448,1086),note))
    # A changed box cannot be reinterpreted as the original frozen 4:5 selection.
    assert not editorial.verify_original(ep,22,raw,receipt,2/3)
