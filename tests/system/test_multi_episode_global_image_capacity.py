"""Cross-Episode hard image cap: process crashes, batch, native and Codex."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import global_image_capacity as capacity
import image_worker_pool
import batch_image_worker
import codex_subscription_image as direct_image_cli


CHILD = r"""
import sys,time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import global_image_capacity as c
base=Path(sys.argv[2])
tag=sys.argv[3]
count=int(sys.argv[4])
with c.image_permits(count,shared_dir=base / "slots",wait_seconds=10):
    (base / (tag+".ready")).write_text("acquired",encoding="utf-8")
    release=base/(tag+".release")
    end=time.monotonic()+20
    while not release.exists() and time.monotonic() < end:
        time.sleep(.03)
"""


def _child(base: Path, tag: str, permits: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", CHILD, str(SYSTEM), str(base), tag, str(permits)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )


def _ready(base: Path, tag: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if (base / (tag+".ready")).is_file():
            return
        if process.poll() is not None:
            # The old test discarded stderr, hiding the reason why a Windows
            # worker exited before acquiring its machine-global image slots.
            # Read only after exit, so a crashed child cannot block CI.
            diagnostic = (process.stderr.read(8192).decode("utf-8", errors="replace")
                          if process.stderr else "")
            diagnostic = diagnostic[-1800:]
            raise AssertionError(
                f"worker {tag} exited early ({process.returncode}); "
                f"child_stderr_tail={diagnostic!r}"
            )
        time.sleep(.03)
    raise AssertionError("worker never claimed global capacity")


def test_failed_worker_startup_includes_child_lock_diagnostic(tmp_path):
    from io import BytesIO

    class CrashedWorker:
        returncode = 1
        stderr = BytesIO(b"GLOBAL_IMAGE_CAPACITY_LOCK_FAILED")

        def poll(self):
            return 1

    with pytest.raises(AssertionError, match="GLOBAL_IMAGE_CAPACITY_LOCK_FAILED"):
        _ready(tmp_path, "failed", CrashedWorker())


def test_two_episodes_share_one_five_image_machine_cap(tmp_path):
    a = _child(tmp_path, "episode_a", 2)
    b = _child(tmp_path, "episode_b", 3)
    try:
        _ready(tmp_path, "episode_a", a)
        _ready(tmp_path, "episode_b", b)
        with pytest.raises(capacity.GlobalImageCapacityError, match="GLOBAL_IMAGE_CAPACITY_BUSY"):
            with capacity.image_permits(1, shared_dir=tmp_path/"slots", wait_seconds=0.2):
                pytest.fail("sixth image entered")
        (tmp_path / "episode_a.release").touch()
        a.wait(timeout=10)
        assert a.returncode == 0
        with capacity.image_permits(1, shared_dir=tmp_path/"slots", wait_seconds=3):
            pass
    finally:
        for tag, proc in (("episode_a", a), ("episode_b", b)):
            (tmp_path / (tag+".release")).touch()
            if proc.poll() is None:
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            if proc.stderr:
                proc.stderr.close()


def test_fresh_slot_files_need_no_prelock_byte_initialization(tmp_path):
    shared = tmp_path / "brand-new-slot-root"
    with capacity.image_permits(capacity.CAPACITY, shared_dir=shared, wait_seconds=1):
        files = sorted(shared.glob("slot-*.lock"))
        assert len(files) == capacity.CAPACITY
        assert all(path.stat().st_size == 0 for path in files)
    # An empty locked file is also valid after a crash/restart and must not
    # be truncated, replaced, or unlinked between owners.
    with capacity.image_permits(capacity.CAPACITY, shared_dir=shared, wait_seconds=1):
        assert all(path.stat().st_size == 0 for path in files)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows byte-range initialization race")
def test_windows_concurrent_first_open_on_fresh_lock_files(tmp_path):
    # Reproduce the original hazardous sequence repeatedly: two independent
    # processes race to create the same five previously nonexistent slot files.
    # Both must acquire their disjoint 2+3 slots without early process death.
    for index in range(8):
        base = tmp_path / f"fresh-{index}"
        base.mkdir()
        a = _child(base, "episode_a", 2)
        b = _child(base, "episode_b", 3)
        try:
            _ready(base, "episode_a", a)
            _ready(base, "episode_b", b)
            with pytest.raises(capacity.GlobalImageCapacityError,
                               match="GLOBAL_IMAGE_CAPACITY_BUSY"):
                with capacity.image_permits(
                    1, shared_dir=base / "slots", wait_seconds=0.05
                ):
                    pytest.fail("a sixth slot was admitted")
        finally:
            for tag, proc in (("episode_a", a), ("episode_b", b)):
                (base / (tag + ".release")).touch()
                if proc.poll() is None:
                    try:
                        proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                if proc.stderr:
                    proc.stderr.close()
        assert a.returncode == b.returncode == 0


def test_crashed_episode_releases_machine_slots_without_stale_lock_deletion(tmp_path):
    victim = _child(tmp_path, "crashed", capacity.CAPACITY)
    try:
        _ready(tmp_path, "crashed", victim)
        with pytest.raises(capacity.GlobalImageCapacityError, match="GLOBAL_IMAGE_CAPACITY_BUSY"):
            with capacity.image_permits(1, shared_dir=tmp_path/"slots", wait_seconds=0):
                pass
    finally:
        if victim.poll() is None:
            victim.kill()
            victim.wait(timeout=5)
        if victim.stderr:
            victim.stderr.close()
    with capacity.image_permits(capacity.CAPACITY, shared_dir=tmp_path/"slots", wait_seconds=4):
        assert True


def test_count_must_be_positive_and_at_most_shared_machine_capacity(tmp_path):
    for count in (0, -1, 6, True):
        with pytest.raises(capacity.GlobalImageCapacityError, match="GLOBAL_IMAGE_CAPACITY_REQUEST_INVALID"):
            with capacity.image_permits(count, shared_dir=tmp_path):
                pass


def test_single_frame_must_claim_before_any_worker_side_effect(tmp_path):

    holder = _child(tmp_path, "other_episode", capacity.CAPACITY)
    try:
        _ready(tmp_path, "other_episode", holder)
        with patch.object(capacity, "shared_directory", return_value=tmp_path/"slots"):
            with patch.object(image_worker_pool.resource_library, "ensure_fresh") as backend:
                original = capacity.image_permits
                def immediate(count=1, **kwargs):
                    return original(count, wait_seconds=0.05, **kwargs)
                with patch.object(image_worker_pool.global_image_capacity, "image_permits", immediate):
                    with pytest.raises(capacity.GlobalImageCapacityError, match="GLOBAL_IMAGE_CAPACITY_BUSY"):
                        image_worker_pool.execute(tmp_path, {"frame": 1}, 1, None)
                backend.assert_not_called()
    finally:
        (tmp_path / "other_episode.release").touch()
        holder.wait(timeout=8)
        if holder.stderr:
            holder.stderr.close()



def test_direct_frame_cli_capacity_busy_never_reserves_attempt(tmp_path, monkeypatch, capsys):
    argv = ["codex_subscription_image.py", "generate-for-frame", str(tmp_path),
            "--frame", "01", "--prompt-file", str(tmp_path/"01.txt"),
            "--output", str(tmp_path/"01.png"), "--log", str(tmp_path/"01.jsonl")]
    monkeypatch.setattr(sys, "argv", argv)
    with (
        patch.object(direct_image_cli.runtime_timeout_policy, "resolve", return_value=120),
        patch.object(capacity, "image_permits",
                     side_effect=capacity.GlobalImageCapacityError("GLOBAL_IMAGE_CAPACITY_BUSY")),
        patch.object(direct_image_cli.raw_candidate_budget, "claim") as claim,
        patch.object(direct_image_cli, "generate_for_frame") as backend,
    ):
        assert direct_image_cli.main() == 2
        claim.assert_not_called()
        backend.assert_not_called()
    assert "GLOBAL_IMAGE_CAPACITY_BUSY" in capsys.readouterr().out


def test_native_batch_uses_weighted_shared_capacity_before_provider(tmp_path):
    items = [{"id": "batch_a"}, {"id": "batch_b"}]
    holder = _child(tmp_path, "other_episode", 4)
    try:
        _ready(tmp_path, "other_episode", holder)
        with (
            patch.object(capacity, "shared_directory", return_value=tmp_path/"slots"),
            patch.object(batch_image_worker, "_shared_refs", return_value=[]),
            patch.object(batch_image_worker.image_provider_router, "select_for_batch",
                         return_value={"provider": "openai_images_api", "logical_batch": False}),
            patch.object(batch_image_worker, "_execute_batch_with_image_capacity") as backend,
        ):
            original = capacity.image_permits
            def immediate(count=1, **kwargs):
                return original(count, wait_seconds=0.05, **kwargs)
            with patch.object(batch_image_worker.global_image_capacity, "image_permits", immediate):
                with pytest.raises(capacity.GlobalImageCapacityError, match="GLOBAL_IMAGE_CAPACITY_BUSY"):
                    batch_image_worker.execute_batch(tmp_path, {"batch_id":"test"}, items, 30, None)
            backend.assert_not_called()
    finally:
        (tmp_path / "other_episode.release").touch()
        holder.wait(timeout=8)
        if holder.stderr:
            holder.stderr.close()



def test_codex_logical_batch_does_not_double_take_permits(tmp_path):
    items = [{"id": "a"}, {"id": "b"}]
    with (
        patch.object(batch_image_worker, "_shared_refs", return_value=[]),
        patch.object(batch_image_worker.image_provider_router, "select_for_batch",
                     return_value={"provider": "codex_subscription", "logical_batch": True}),
        patch.object(batch_image_worker, "_execute_batch_with_image_capacity",
                     return_value={"results": {}}) as worker,
        patch.object(batch_image_worker.global_image_capacity, "image_permits") as permits,
    ):
        assert batch_image_worker.execute_batch(tmp_path, {}, items, 10, None) == {"results": {}}
        permits.assert_not_called()
        worker.assert_called_once()


def test_separate_git_worktrees_share_one_lock_root():
    common = capacity.shared_directory(ROOT)
    assert common.name.startswith("storyos-global-image-capacity-v2-")
    assert common.parent == Path(__import__("tempfile").gettempdir()).resolve()
    assert "episodes" not in common.parts


def test_gateway_uses_outer_worker_slot_without_double_counting(tmp_path):
    import image_generation_gateway as gateway
    lease = {"episode_id": "ep", "logical_asset_key": "ep/frame-01"}
    with (
        patch.object(capacity, "shared_directory", return_value=tmp_path),
        patch.object(gateway.authority, "commit_dispatch", return_value={"attempt_index": 1}) as committed,
        patch.object(gateway.authority, "validate_committed_dispatch", return_value=True) as fenced,
        patch.object(gateway.authority, "mark_observed") as observed,
    ):
        with capacity.image_permits(capacity.CAPACITY, shared_dir=tmp_path):
            assert gateway.provider_generate(tmp_path, lease, 1, "codex_subscription", lambda: "raw") == "raw"
            committed.assert_called_once()
            observed.assert_called_once()
            fenced.assert_called_once()


def test_nested_provider_batch_weight_must_not_exceed_outer_reservation(tmp_path):
    with patch.object(capacity, "shared_directory", return_value=tmp_path):
        with capacity.image_permits(1, shared_dir=tmp_path):
            with pytest.raises(capacity.GlobalImageCapacityError,
                               match="GLOBAL_IMAGE_CAPACITY_NESTED_WEIGHT_EXCEEDS_HELD"):
                with capacity.image_permits(2, shared_dir=tmp_path):
                    pass


def test_gateway_refuses_extra_batch_when_shared_slots_are_full(tmp_path):
    import image_generation_gateway as gateway
    leases = [{"episode_id": "ep2", "logical_asset_key": "ep2/01"},
              {"episode_id": "ep2", "logical_asset_key": "ep2/02"}]
    holder = _child(tmp_path, "other_episode", 4)
    try:
        _ready(tmp_path, "other_episode", holder)
        with patch.object(capacity, "shared_directory", return_value=tmp_path/"slots"):
            orig = capacity.image_permits
            def immediate(count=1, **kwargs):
                return orig(count, wait_seconds=.05, **kwargs)
            with patch.object(gateway.global_image_capacity, "image_permits", immediate):
                with patch.object(gateway.authority, "commit_dispatch_many") as commit:
                    with pytest.raises(capacity.GlobalImageCapacityError, match="GLOBAL_IMAGE_CAPACITY_BUSY"):
                        gateway.provider_generate_many(tmp_path, leases, "openai_images_api", lambda: "raw")
                    commit.assert_not_called()
    finally:
        (tmp_path / "other_episode.release").touch()
        holder.wait(timeout=8)
        if holder.stderr:
            holder.stderr.close()
