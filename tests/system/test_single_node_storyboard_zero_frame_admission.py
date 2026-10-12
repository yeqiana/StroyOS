"""Single-machine storyboard admission must never pass on absent frame count.

Offline, temporary Episode only; no story generation, image Provider or release.
"""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SYSTEM=ROOT/"episodes"/"_system"
if str(SYSTEM) not in sys.path:sys.path.insert(0,str(SYSTEM))
import storyboard_density_gate as density


def _episode(tmp_path,count=None):
    ep=tmp_path/"ep"
    (ep/"meta").mkdir(parents=True)
    release={"release":{} if count is None else {"body_frame_count":count}}
    (ep/"meta"/"release-manifest.json").write_text(json.dumps(release),encoding="utf-8")
    (ep/density.REL).write_text(json.dumps({
        "schema_version":1,"status":"LOCKED","frames":[]
    }),encoding="utf-8")
    return ep


def test_missing_frame_count_never_passes_locked_empty_storyboard(tmp_path):
    ep=_episode(tmp_path)
    errors=density.validate(ep)
    assert any("body_frame_count" in err for err in errors),errors


def test_zero_frame_count_never_passes_locked_empty_storyboard(tmp_path):
    ep=_episode(tmp_path,0)
    errors=density.validate(ep)
    assert any("body_frame_count" in err for err in errors),errors


def test_positive_frame_count_does_not_accept_empty_storyboard(tmp_path):
    ep=_episode(tmp_path,20)
    errors=density.validate(ep)
    assert any("frame count mismatch" in err for err in errors),errors


def test_unlocked_draft_never_passes_without_frames(tmp_path):
    ep=_episode(tmp_path)
    assert density.validate(ep,require_locked=False)
