"""The native vision reviewer must use the authenticated Codex user bridge."""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes" / "_system"))
import caption_image_audit as c


def test_caption_chunk_uses_native_user_bridge_not_service_account(tmp_path):
    ep = tmp_path / "ep"
    (ep / "meta").mkdir(parents=True)
    frame_path = ep / "01.png"
    frame_path.write_bytes(b"dummy test pixels")
    row = {"frame": "01", "path": frame_path, "path_rel": "ep/01.png", "sha256": "a" * 64}
    accepted = []

    def fake_codex(argv, **kwargs):
        accepted.append((argv, kwargs))
        assert kwargs["task_type"] == "review"
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["check"] is False
        assert kwargs["input"] == "review one frame"
        assert kwargs["cwd"] == ep
        target = ep / "meta" / ".caption-image-audit-candidate-001.json"
        target.write_text(json.dumps({"frames": [{"frame": "01", "supported": True,
                                                    "subtitle_unobstructed": True,
                                                    "notes": "visual inspection evidence"}],
                                      "summary": {"passed": True}}), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, '{"type":"turn.completed"}\n')

    with patch.object(c.runtime_router, "detect", return_value=("CODEX", "test")), \
         patch.object(c.runtime_router, "vision_review_runtime", return_value=("CODEX", "test")), \
         patch.object(c.runtime_router, "vision_review_model", return_value="gpt-6"), \
         patch.object(c.runtime_router, "vision_review_effort", return_value="low"), \
         patch.object(c.base, "resolve_codex", return_value=Path("codex.cmd")), \
         patch.object(c.base, "command_prefix", return_value=["codex.cmd"]), \
         patch.object(c, "_prompt", return_value="review one frame"), \
         patch.object(c, "ROOT", tmp_path), \
         patch.object(c.codex_user_runner, "run_model_codex", side_effect=fake_codex), \
         patch.object(c.runtime_provenance, "build_vision_critic_provenance",
                      return_value={"provider": "codex_subscription"}):
        result = c._run_chunk(ep, [row], {"01": "test caption"}, None, 90, 1)
    assert len(accepted) == 1
    assert result["frames"][0]["supported"] is True
    assert result["_vision_telemetry"]["vision_call"] is True
    assert (ep / "meta" / "caption-image-audit-v2-001.jsonl").is_file()


def test_real_jsonl_fail_is_preserved_and_wrong_pass_rejected():
    rows = [
        {"frame": "01", "supported": False, "subtitle_unobstructed": True,
         "notes": "off-screen assertion is not visually established"},
        {"frame": "02", "supported": True, "subtitle_unobstructed": True,
         "notes": "pixel evidence supports this caption"},
    ]
    def log(passed, *, terminal=True):
        events = [{"type": "thread.started", "thread_id": "test-id"},
                  {"type": "item.completed",
                   "item": {"type": "agent_message", "text": json.dumps(
                       {"frames": rows, "summary": {"passed": passed}})}}]
        if terminal:
            events.append({"type": "turn.completed"})
        return "\n".join(json.dumps(event) for event in events)
    recovered = c._recover_jsonl_review(log(False), ["01", "02"])
    assert recovered is not None
    assert recovered["summary"]["passed"] is False
    assert recovered["frames"][0]["supported"] is False
    assert c._recover_jsonl_review(log(True), ["01", "02"]) is None
    assert c._recover_jsonl_review(log(False, terminal=False), ["01", "02"]) is None
    assert c._recover_jsonl_review(log(False), ["01", "03"]) is None
