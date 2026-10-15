"""Hermetic negative gates for the one-shot native Visual Lock baseline."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest
from PIL import Image

SYSTEM = Path(__file__).resolve().parents[2] / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import production_native_baseline_proof as proof
import image_scheduler


@pytest.fixture()
def case(monkeypatch, tmp_path):
    ep = tmp_path / "episodes" / "00_独立篇" / "06_五十亩山地之后_全新重制"
    (ep / "meta").mkdir(parents=True)
    (ep / "meta" / "visual-lock-plan.json").write_text("{}", encoding="utf-8")
    rows = [
        {"frame": frame, "role": role, "depends_on": [] if frame == 1 else [1]}
        for frame, role in proof.PLAN
    ]
    q = {"items": [
        {"id": str(frame), "frame": frame, "kind": "original",
         "model": "gpt-image-2.5-flare", "quality": "high",
         "scope": "visual_lock", "status": "queued",
         "depends_on": [] if frame == 1 else [1]}
        for frame in (1, 16, 8, 17)
    ]}
    story_gates = {"reviews": {"story": "passed", "authenticity": "pending",
                              "visual_admission": "pending", "continuity": "pending"}}
    stage = {"current_state": "STORYBOARD_LOCKED"}
    db = {"host": "127.0.0.1", "port": 3307}
    cfg = {"mode": "full_auto", "runtime": {"execution_mode": "dag"}}
    states = {frame: {"attempts_consumed": 0, "active_attempt_index": None}
              for frame in (1, 8, 16, 17)}
    monkeypatch.setattr(proof, "ROOT", tmp_path)
    monkeypatch.setattr(proof.episode_state_persistence, "load", lambda _: stage)
    monkeypatch.setattr(proof.runtime_request, "effective_for_episode", lambda _: cfg)
    monkeypatch.setattr(proof.runtime_router, "image_execution_runtime", lambda: ("CODEX","episode"))
    monkeypatch.setattr(proof.storage_config, "mysql_connection_kwargs", lambda: db)
    monkeypatch.setattr(proof.story_json, "read_json",
                        lambda p: {"items": rows} if p.name == "visual-lock-plan.json" else story_gates)
    monkeypatch.setattr(image_scheduler, "load_queue", lambda _: q)
    monkeypatch.setattr(proof.image_payload_transport, "selected_route",
                        lambda _: {"provider": "codex_subscription"})
    monkeypatch.setattr(proof.image_model_policy, "for_episode",
                        lambda _: {"model": "gpt-image-2.5-flare", "quality": "high"})
    monkeypatch.setattr(proof.logical_asset_identity, "frame_asset_key",
                        lambda _, frame: str(frame))
    monkeypatch.setattr(proof.generation_attempt_authority, "load_asset_state",
                        lambda _, k: states[int(k)])
    payload = {"model": "gpt-image-2.5-flare", "quality": "high"}
    controller = {"model": "gpt-6-luna", "reasoning_effort": "high",
                  "model_policy_sha256": "a" * 64}
    return locals()


def test_real_episode_baseline_is_only_eligible_candidate(case):
    p = proof
    assert p.eligible(case["ep"], case["q"]["items"][0],
                      case["payload"], case["controller"]) is True
    for item in case["q"]["items"][1:]:
        assert not p.eligible(case["ep"], item, case["payload"], case["controller"])


@pytest.mark.parametrize("mutate", [
    lambda c: c["stage"].update(current_state="PREIMAGE"),
    lambda c: c["db"].update(port=3306),
    lambda c: c["cfg"].update(mode="COLLABORATIVE"),
    lambda c: c["cfg"]["runtime"].update(execution_mode="manual"),
    lambda c: c["states"][1].update(attempts_consumed=1),
    lambda c: c["states"][1].update(active_attempt_index=1),
    lambda c: c["states"][8].update(attempts_consumed=1),
    lambda c: c["story_gates"]["reviews"].update(visual_admission="passed"),
    lambda c: c["q"]["items"][2].update(status="generated"),
    lambda c: c["q"]["items"].append({"frame": 99}),
    lambda c: c["rows"][0].update(role="wrong"),
    lambda c: c["controller"].update(model="gpt-5.5"),
    lambda c: c["payload"].update(model="other-image-model"),
])
def test_scope_or_authority_drift_denied(case, mutate):
    mutate(case)
    assert proof.eligible(
        case["ep"], case["q"]["items"][0],
        case["payload"], case["controller"]) is False


def test_lost_property_episode_admits_only_exact_first_baseline(case):
    """Episode 13 has its own real four-frame 1+3 plan; no blanket permission."""
    ep = case["ep"].parent / "13_失物归还的那扇门"
    (ep / "meta").mkdir(parents=True)
    (ep / "meta/visual-lock-plan.json").write_text("{}", encoding="utf-8")
    plan = proof.PRODUCTION_EPISODE_PLANS[ep.name]
    case["rows"][:] = [
        {"frame": frame, "role": role, "depends_on": [] if frame == 1 else [1]}
        for frame, role in plan
    ]
    case["q"]["items"][:] = [
        {"id": str(frame), "frame": frame, "kind": "original",
         "model": "gpt-image-2.5-flare", "quality": "high",
         "scope": "visual_lock", "status": "queued",
         "depends_on": [] if frame == 1 else [1]}
        for frame, _role in plan
    ]
    for frame, _role in plan:
        case["states"][frame] = {"attempts_consumed": 0, "active_attempt_index": None}
    baseline = case["q"]["items"][0]
    assert proof.eligible(ep, baseline, case["payload"], case["controller"])
    assert not proof.eligible(ep, case["q"]["items"][1], case["payload"], case["controller"])
    case["rows"][2]["frame"] = 4
    assert not proof.eligible(ep, baseline, case["payload"], case["controller"])



def test_episode13_second_proof_requires_exact_reconciled_failure(case, monkeypatch):
    ep = case["ep"].parent / "13_失物归还的那扇门"
    (ep / "meta").mkdir(parents=True)
    (ep / "meta/visual-lock-plan.json").write_text("{}", encoding="utf-8")
    plan = proof.PRODUCTION_EPISODE_PLANS[ep.name]
    case["rows"][:] = [
        {"frame": frame, "role": role,
         "depends_on": [] if frame == 1 else [1]}
        for frame, role in plan
    ]
    case["q"]["items"][:] = [
        {"id": str(frame), "frame": frame, "kind": "original",
         "model": "gpt-image-2.5-flare", "quality": "high",
         "scope": "visual_lock", "status": "queued",
         "depends_on": [] if frame == 1 else [1]}
        for frame, _role in plan
    ]
    for frame, _role in plan:
        case["states"][frame] = {"attempts_consumed": 0, "active_attempt_index": None}
    case["states"][1]["attempts_consumed"] = 1
    baseline = case["q"]["items"][0]
    baseline["technical_retry_source_code"] = "IMAGE_BACKEND_ERROR"
    baseline["generation_attempt_reason"] = "TECHNICAL_RETRY"
    previous = {
        "episode_id": "00_独立篇/13_失物归还的那扇门",
        "attempt_index": 1, "status": "FAILED_AFTER_DISPATCH",
        "failure_class": "IMAGE_TOOL_NETWORK_ERROR_DURABLE_RECEIPT",
        "result_ref": None, "provider": "codex_subscription",
        "payload_model": "gpt-image-2.5-flare", "payload_quality": "high",
        "dispatch_committed_at": "2026-10-15T07:14:46",
        "generation_observed_at": "2026-10-15T07:20:48",
        "generation_key": "bound",
    }
    monkeypatch.setattr(proof.generation_attempt_authority,
        "stable_generation_key", lambda *_: "bound")
    monkeypatch.setattr(proof.generation_attempt_authority,
        "load_attempt", lambda _ep, _key, ix: previous if ix == 1 else None)
    assert proof.eligible(ep, baseline, case["payload"], case["controller"])
    lease = {"attempt_index": 2, "fencing_token": 2,
             "generation_key": "generation-2", "lease_token": "token-2"}
    assert proof.admitted_baseline_lease(ep, baseline, lease)
    assert not proof.admitted_baseline_lease(ep, baseline,
        {**lease, "attempt_index": 3})
    assert not proof.admitted_baseline_lease(ep, baseline,
        {**lease, "fencing_token": 3})
    previous["status"] = "OUTCOME_UNKNOWN"
    assert not proof.eligible(ep, baseline, case["payload"], case["controller"])
    assert not proof.admitted_baseline_lease(ep, baseline, lease)
    previous["status"] = "FAILED_AFTER_DISPATCH"
    case["states"][3]["attempts_consumed"] = 1
    assert not proof.eligible(ep, baseline, case["payload"], case["controller"])


def test_unrecognized_episode_directory_denied(case):
    assert not proof.eligible(
        case["ep"].parent / "05_not_authorized", case["q"]["items"][0],
        case["payload"], case["controller"])


def good_probe():
    return {"status": "READY_FOR_REAL_CAPABILITY_PROOF",
            "tool_capability_state": "UNKNOWN",
            "image_generation_visible_secondary": True,
            "visibility_response_completed": True,
            "tool_visibility_evidence_level": "SECONDARY_ATTESTATION",
            "session_start": "PASS", "candidate_catalog_member": True,
            "provider": "codex_subscription",
            "payload_model": "gpt-image-2.5-flare", "payload_quality": "high",
            "transport_model": "gpt-6-luna", "transport_effort": "high",
            "image_generation_called": False, "image_attempt_authority_called": False,
            "explicit_negative_evidence": False, "catalog_sha256": "b"*64}


def test_secondary_visibility_not_called_on_nonunknown_strict(case, monkeypatch):
    monkeypatch.setattr(proof.codex_subscription_image, "payload_capability_preflight",
                        lambda **_: pytest.fail("unscoped probe was called"))
    out = proof.attest_secondary(
        {"status": "PASS", "image_generation_called": False},
        case["payload"], case["controller"], None)
    assert out is None


def test_secondary_visibility_is_still_unknown_not_pass(case, monkeypatch):
    monkeypatch.setattr(proof.codex_subscription_image, "payload_capability_preflight",
                        lambda **_: good_probe())
    out = proof.attest_secondary(
        {"status": "BLOCKED", "failure_class": "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN",
         "image_generation_called": False, "image_attempt_authority_called": False},
        case["payload"], case["controller"], None)
    assert out["status"] == "READY_FOR_REAL_CAPABILITY_PROOF"
    assert out["image_generation_called"] is False


@pytest.mark.parametrize("changes", [
    {"image_generation_visible_secondary": False},
    {"image_generation_called": True},
    {"transport_model": "wrong"},
    {"session_start": "FAIL"},
    {"catalog_sha256": "x"},
    {"provider": "other_provider"},
    {"explicit_negative_evidence": True},
])
def test_secondary_false_attestation_rejected(case, monkeypatch, changes):
    row = {**good_probe(), **changes}
    monkeypatch.setattr(proof.codex_subscription_image, "payload_capability_preflight",
                        lambda **_: row)
    assert proof.attest_secondary(
        {"status": "BLOCKED", "failure_class": "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN",
         "image_generation_called": False, "image_attempt_authority_called": False},
        case["payload"], case["controller"], None) is None


def test_first_attempt_fence_and_evidence_digest():
    assert proof.first_attempt_only({"attempt_index": 1, "fencing_token": 3,
                                     "generation_key": "g", "lease_token": "t"})
    assert not proof.first_attempt_only({"attempt_index": 2, "fencing_token": 3,
                                         "generation_key": "g", "lease_token": "t"})
    assert not proof.first_attempt_only({"attempt_index": 1, "fencing_token": 0,
                                         "generation_key": "g", "lease_token": "t"})
    assert len(proof.evidence_sha(good_probe())) == 64


def test_worker_retains_strict_normal_preflight():
    text = (SYSTEM / "image_worker_pool.py").read_text(encoding="utf-8")
    assert "image_payload_transport.payload_capability_preflight(" in text
    assert "production_native_baseline_proof.eligible(" in text
    assert "production_native_baseline_proof.admitted_baseline_lease(" in text
    assert "payload_preflight_status == \"PASS\"" in text



@pytest.mark.parametrize("event_lines", [
    ['{"type":"item.completed","item":{"type":"agent_message","text":"image_generation"}}'],
    ['{"type":"item.completed","item":{"type":"image_generation_call"}}'],
    ['{"type":"item.completed","item":{"type":"image_generation_call"}}',
     '{"type":"item.completed","item":{"type":"image_generation_call"}}',
     '{"type":"turn.completed"}'],
    ['{"type":"item.completed","item":{"type":"image_generation_call"}}',
     '{"type":"turn.completed"}', '{"type":"turn.failed"}'],
])
def test_real_pixel_proof_rejects_missing_or_forged_tool_call(tmp_path, event_lines):
    log = tmp_path / "codex.jsonl"
    log.write_text("\n".join(event_lines) + "\n", encoding="utf-8")
    png = tmp_path / "image.png"
    Image.new("RGB", (1024, 1024), (18, 28, 38)).save(png)
    assert proof.observe_real_tool_pixel(log, png) is None


def test_real_completed_native_pixel_receipt_is_unreviewed_and_immutable(tmp_path):
    log = tmp_path / "codex.jsonl"
    log.write_text(
        '{"type":"thread.started"}\n'
        '{"type":"item.completed","item":{"type":"image_generation_call"}}\n'
        '{"type":"turn.completed"}\n',
        encoding="utf-8")
    png = tmp_path / "image.png"
    Image.new("RGB", (1024, 1024), (18, 28, 38)).save(png)
    observed = proof.observe_real_tool_pixel(log, png)
    assert observed is not None and observed["tool_call_count"] == 1
    assert len(observed["pixel_sha256"]) == 64
    ep = tmp_path / "episode"
    item = {"frame": 1, "id": "queue-1",
            "prompt_package": {"package_sha256": "a"*64, "frame_contract_sha256": "f"*64}}
    lease = {"attempt_index": 1, "fencing_token": 2,
             "generation_key": "g1", "lease_token": "secret"}
    result = proof.record_unreviewed_pixel(ep, item, lease, log, png, "native-request")
    assert result["status"] == "OBSERVED_AWAITING_INDEPENDENT_VISUAL_REVIEW"
    assert result["review_pass"] is False
    with pytest.raises(FileExistsError):
        proof.record_unreviewed_pixel(ep, item, lease, log, png, "native-request")


def test_model_text_only_or_invalid_pixel_cannot_be_proof(tmp_path):
    log = tmp_path / "codex.jsonl"
    log.write_text('{"type":"item.completed","item":{"type":"tool_call","name":"image_generation"}}\n'
                   '{"type":"turn.completed"}\n', encoding="utf-8")
    png = tmp_path / "fake.png"
    png.write_bytes(b"not a real png file" * 4)
    assert proof.observe_real_tool_pixel(log, png) is None
    Image.new("RGB", (1024, 1024), (18, 28, 38)).save(png)
    assert proof.observe_real_tool_pixel(log, png)["tool_call_count"] == 1


def test_worker_requires_pixel_event_before_raw_commit():
    source = (SYSTEM / "image_worker_pool.py").read_text(encoding="utf-8")
    assert source.index("production_native_baseline_proof.record_unreviewed_pixel(") < source.index(
        "raw_candidate_budget.commit(ep,budget_token,reason=\"normalized_candidate_exists\")")
    assert "NATIVE_BASELINE_PIXEL_TOOL_PROOF_UNVERIFIED" in source
    assert "release_ok,release_row = raw_candidate_budget.release(" in source
    assert "native_baseline_proof_unverified_raw_consumed" not in source
