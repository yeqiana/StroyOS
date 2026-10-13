"""Episode 15 review-input repair is a draft, never a new paid A9 attempt.

Four fast checks: captions, Frame15 information, wooden hairpin continuity,
and immutable official review/episode source authorization.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
EP = ROOT / "episodes/15_天界生活日常/01_天界普通女生的一天"
DOC = EP / "docs"
V1 = DOC / "03_天界普通女生的一天_20张正式分镜_V1.0.md"
V11 = DOC / "03_天界普通女生的一天_20张分镜修订草稿_V1.1.md"
CAP = DOC / "subtitles.yaml"
sys.path.insert(0, str(ROOT / "episodes/_system"))
sys.path.insert(0, str(ROOT / "scripts"))

import text_audit
import storyos_a9_receipt_reconcile as r16


def test_ep15_caption_draft_all_20_frames_from_locked_source():
    parsed = text_audit.parse_simple_subtitles_yaml(CAP)
    frames = parsed["frames"]
    assert sorted(frames) == list(range(1, 21))
    assert all(isinstance(frames[i], str) and 8 <= len(frames[i]) <= 100
               for i in range(1, 21))
    text = CAP.read_text(encoding="utf-8")
    assert "草稿" in text
    assert "不是用户确认" in text
    assert "A9" not in text or "A9" in V11.read_text(encoding="utf-8")


def test_ep15_frame15_has_new_observable_change_and_causes_frame16():
    storyboard = V11.read_text(encoding="utf-8")
    f14 = next(x for x in storyboard.splitlines() if x.startswith("14. **"))
    f15 = next(x for x in storyboard.splitlines() if x.startswith("15. **"))
    f16 = next(x for x in storyboard.splitlines() if x.startswith("16. **"))
    assert "买" in f14 and "茶摊" in f14
    assert "收桌" in f15 and "夕光" in f15 and "P01" in f15
    assert "西桥" in f15 and "西桥" in f16 and "P02" in f16
    assert "竹篮摔坏" not in f15


def test_ep15_wooden_hairpin_source_and_carry_chain_unambiguous():
    lines = V11.read_text(encoding="utf-8").splitlines()
    f12 = next(x for x in lines if x.startswith("12. **"))
    f14 = next(x for x in lines if x.startswith("14. **"))
    f20 = next(x for x in lines if x.startswith("20. **"))
    assert "P02" in f12 and "试" in f12 and "尚未确定购买" in f12
    assert "P01" in f14 and "自己" in f14 and "买" in f14
    assert "P01" in f20 and "Frame 14" in f20 and "木簪" in f20
    assert "自己" in f20


def test_ep15_locked_v1_bytes_untouched_and_a9_still_nonretryable():
    rel = V1.relative_to(ROOT).as_posix()
    committed = subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=ROOT)
    assert V1.read_bytes() == committed
    assert "待审核" in V11.read_text(encoding="utf-8")
    fail = r16.decide(
        epoch_present=True, candidate={"summary": {"passed": False}},
        candidate_exists=True, evidence_status="PAID_CRITIC_TIMEOUT_NO_AUTORETRY",
        official_review_present=False)
    assert fail["may_retry_attempt_9"] is False
    assert fail["can_mark_review_pass"] is False
    assert fail["can_dispatch_image"] is False
    assert fail["sql_writes"] == fail["model_calls"] == 0
