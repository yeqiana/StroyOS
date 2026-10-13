from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import m00_calibration_receipts as receipts


def _make(tmp_path, *, recovered=False):
    base = tmp_path / "calibration" / "C03"
    base.mkdir(parents=True)
    img = base / "generated.png"
    Image.new("RGB", (1122, 1402), (150, 140, 125)).save(img)
    digest = hashlib.sha256(img.read_bytes()).hexdigest()
    record = {
        "frame": "C03", "status": "IMAGE_RECOVERED_AFTER_RUNNER_TIMEOUT" if recovered else "IMAGE_CREATED",
        "mock": {"production_authority": False}, "request_id": "id-exact",
        "output": "calibration/C03/generated.png", "output_sha256": digest,
        "dimensions": [1122, 1402],
        "codex_returncode": None if recovered else 0,
    }
    if recovered:
        record["recovery"] = {
            "runner_returncode": 124, "request_id": "id-exact",
            "thread_id": "this-task-only",
            "type": "THREAD_SCOPED_DURABLE_ARTIFACT",
            "different_from_clean_completion": True,
        }
    path = base / "test-only-record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return tmp_path / "calibration", img, path, record


def test_normal_image_is_not_automatically_approved(tmp_path):
    root, _img, _record_path, _record = _make(tmp_path)
    receipt = receipts.inspect_frame(root, "C03")
    assert receipt["verified"] and receipt["clean_provider_completion"] is True
    assert receipt["grants_visual_lock_pass"] is False
    assert receipt["grants_production_attempt"] is False


def test_timeout_recovered_image_remains_distinct_from_clean_completion(tmp_path):
    root, _img, _record_path, _record = _make(tmp_path, recovered=True)
    receipt = receipts.inspect_frame(root, "C03")
    assert receipt["verified"] is True
    assert receipt["status"] == "IMAGE_RECOVERED_AFTER_RUNNER_TIMEOUT"
    assert receipt["clean_provider_completion"] is False
    assert receipt["may_auto_retry"] is False


def test_recovered_image_must_be_thread_scoped_and_sha_bound(tmp_path):
    root, img, path, doc = _make(tmp_path, recovered=True)
    doc["recovery"]["thread_id"] = ""
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert receipts.inspect_frame(root, "C03")["status"] == "RECOVERY_PROVENANCE_INVALID"
    doc["recovery"]["thread_id"] = "thread"
    path.write_text(json.dumps(doc), encoding="utf-8")
    img.write_bytes(b"changed")
    assert receipts.inspect_frame(root, "C03")["status"] == "IMAGE_MISSING_OR_SHA_DRIFT"


def test_missing_and_unknown_are_not_retry_permits(tmp_path):
    root, _img, path, doc = _make(tmp_path)
    doc["status"] = "STARTED"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert not receipts.inspect_frame(root, "C03")["verified"]
    assert receipts.inspect_frame(root, "C01")["status"] == "MISSING_RECEIPT"


def test_adjacent_frame_review_requires_actual_pixels_not_labels():
    checks = receipts.continuity_review_requirements([
        {"frame": "01"}, {"frame": "02"}, {"frame": "03"},
    ])
    assert len(checks) == 2
    assert checks[0]["pair"] == ["01", "02"]
    assert "prop_contact_and_state_progression" in checks[1]["check"]
    assert all(row["pixel_review_pass"] is None for row in checks)


def test_duplicate_sequence_frame_names_do_not_result_in_fake_pass():
    import pytest
    with pytest.raises(ValueError, match="DUPLICATE"):
        receipts.inspect_batch(Path("."), ("C01", "C01"))
