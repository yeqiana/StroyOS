"""Multiple canonical Episode Drivers may be managed without image dispatch."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import storyos_multi_episode as multi


def _eps(tmp_path):
    a = tmp_path / "episodes" / "a"
    b = tmp_path / "episodes" / "b"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    return a, b


def test_requires_two_distinct_canonical_episodes(tmp_path):
    a, b = _eps(tmp_path)
    assert multi.validate_episodes(["episodes/a", str(b)], root=tmp_path) == [a, b]
    with pytest.raises(ValueError, match="MULTI_EPISODE_AT_LEAST_TWO_REQUIRED"):
        multi.validate_episodes(["episodes/a"], root=tmp_path)
    with pytest.raises(ValueError, match="MULTI_EPISODE_DUPLICATE"):
        multi.validate_episodes(["episodes/a", str(a)], root=tmp_path)


def test_rejects_foreign_paths_without_side_effects(tmp_path):
    a, b = _eps(tmp_path)
    stranger = tmp_path / "other"
    stranger.mkdir()
    with pytest.raises(ValueError, match="MULTI_EPISODE_PATH_INVALID"):
        multi.validate_episodes([str(a), str(stranger)], root=tmp_path)


def test_status_is_diagnostic_and_never_starts_model(tmp_path):
    a, b = _eps(tmp_path)
    status = Mock(side_effect=[{"driver_state": "RUNNING"},
                               {"driver_state": "NEVER_STARTED"}])
    snapshot = Mock(return_value={"global_max_inflight_images": 5,
                                 "observed_busy": 2, "observed_available": 3})
    with patch.object(multi, "ROOT", tmp_path):
        row = multi.multi_status([a, b], status_fn=status, snapshot_fn=snapshot)
    assert row["model_calls"] == 0
    assert row["episode_count"] == 2
    assert row["episodes"][0]["driver_state"] == "RUNNING"
    assert row["global_image_capacity"]["observed_available"] == 3
    assert status.call_count == 2
    snapshot.assert_called_once()



def test_status_read_failure_is_fail_closed_without_database_secret(tmp_path):
    a, b = _eps(tmp_path)
    def status(ep):
        if ep == b:
            raise ConnectionError("private-mysql-password")
        return {"driver_state": "RUNNING", "liveness": "VERIFIED"}
    with patch.object(multi, "ROOT", tmp_path):
        output = multi.multi_status(
            [a, b], status_fn=status,
            snapshot_fn=lambda: {"global_max_inflight_images": 5,
                                 "observed_busy": 1, "advisory_snapshot_only": True})
    assert output["episode_count"] == 2
    assert output["episodes"][0]["driver_state"] == "RUNNING"
    assert output["episodes"][1]["driver_state"] == "UNKNOWN"
    assert output["episodes"][1]["diagnostic_error"] == "DRIVER_STATUS_READ_FAILED"
    assert output["diagnostic_incomplete"] is True
    assert output["production_authorization"] is False
    assert output["model_calls"] == 0
    assert "private-mysql-password" not in str(output)


def test_capacity_snapshot_failure_does_not_claim_free_image_slots(tmp_path):
    a, b = _eps(tmp_path)
    with patch.object(multi, "ROOT", tmp_path):
        output = multi.multi_status(
            [a, b], status_fn=lambda _: {"driver_state": "NEVER_STARTED"},
            snapshot_fn=lambda: (_ for _ in ()).throw(
                OSError("secret-shared-lock-path")))
    capacity = output["global_image_capacity"]
    assert output["diagnostic_incomplete"] is True
    assert output["production_authorization"] is False
    assert capacity["observation_status"] == "UNAVAILABLE"
    assert "observed_available" not in capacity
    assert "secret-shared-lock-path" not in str(output)


def test_unknown_driver_owner_never_claims_diagnostic_complete(tmp_path):
    a, b = _eps(tmp_path)
    with patch.object(multi, "ROOT", tmp_path):
        output = multi.multi_status(
            [a, b], status_fn=lambda _: {"driver_state": "UNKNOWN"},
            snapshot_fn=lambda: {"observed_available": 5,
                                 "advisory_snapshot_only": True})
    assert output["diagnostic_incomplete"] is True
    assert output["production_authorization"] is False
    assert all(row["diagnostic_error"] == "DRIVER_OWNER_UNVERIFIED"
               for row in output["episodes"])


def test_plan_and_status_return_nonzero_if_authoritative_owner_is_unavailable(
        tmp_path, capsys):
    a, b = _eps(tmp_path)
    with (patch.object(multi, "ROOT", tmp_path),
          patch.object(multi, "start_episodes") as starter,
          patch.object(multi, "multi_status", return_value={
              "authority": "DIAGNOSTIC_ONLY",
              "model_calls": 0,
              "diagnostic_incomplete": True,
              "production_authorization": False,
              "episodes": [], "global_image_capacity": {
                  "advisory_snapshot_only": True,
                  "observation_status": "UNAVAILABLE"}})):
        assert multi.main(["status", "--episode", str(a), "--episode", str(b)]) == 3
        assert multi.main(["plan", "--episode", str(a), "--episode", str(b)]) == 3
    assert '"diagnostic_incomplete": true' in capsys.readouterr().out
    starter.assert_not_called()



def test_owner_read_failure_never_starts_any_episode_or_leaks_credentials(tmp_path):
    a, b = _eps(tmp_path)
    start = Mock()
    def read_owner(ep):
        if ep == b:
            raise ConnectionError("mysql-secret-dsn=private")
        return {"driver_state": "NEVER_STARTED"}
    with patch.object(multi, "ROOT", tmp_path):
        output = multi.start_episodes(
            [a, b], status_fn=read_owner, start_fn=start)
    assert output["ok"] is False
    assert output["reason"] == "MULTI_EPISODE_DRIVER_OWNER_UNVERIFIED"
    assert output["starts_attempted"] == 0
    assert output["blocked_episodes"] == ["episodes/b"]
    assert "mysql-secret" not in str(output)
    start.assert_not_called()


def test_owner_invalid_status_shape_never_dispatches(tmp_path):
    a, b = _eps(tmp_path)
    start = Mock()
    with patch.object(multi, "ROOT", tmp_path):
        output = multi.start_episodes(
            [a, b], status_fn=lambda _: None, start_fn=start)
    assert output["ok"] is False
    assert output["starts_attempted"] == 0
    assert output["error_type"] == "TypeError"
    start.assert_not_called()


def test_unknown_owner_blocks_all_starts(tmp_path):
    a, b = _eps(tmp_path)
    start = Mock()
    with patch.object(multi, "ROOT", tmp_path):
        out = multi.start_episodes(
            [a, b],
            status_fn=lambda ep: {"driver_state": "UNKNOWN" if ep == b else "NEVER_STARTED"},
            start_fn=start,
        )
    assert out["ok"] is False
    assert out["starts_attempted"] == 0
    start.assert_not_called()


def test_running_episode_is_not_double_started_other_episode_resumes(tmp_path):
    a, b = _eps(tmp_path)
    start = Mock(return_value={"started": True})
    with patch.object(multi, "ROOT", tmp_path):
        out = multi.start_episodes(
            [a, b],
            status_fn=lambda ep: {"driver_state": "RUNNING" if ep == a else "EXITED"},
            start_fn=start,
        )
    assert out["ok"]
    assert [x["status"] for x in out["results"]] == ["ALREADY_RUNNING", "STARTED"]
    start.assert_called_once_with(b, resume=True)


@pytest.mark.parametrize("executor", ["PRODUCT_RUNTIME", "AUTO"])
def test_multi_episode_start_refuses_unbounded_async_host_image_route(tmp_path, executor):
    a, b = _eps(tmp_path)
    start = Mock()
    status = Mock()
    with (patch.object(multi, "ROOT", tmp_path),
          patch.object(multi.runtime_router, "image_execution_runtime",
                       return_value=(executor, "test override"))):
        with pytest.raises(ValueError, match="MULTI_EPISODE_NATIVE_CODEX_IMAGE_EXECUTOR_REQUIRED"):
            multi.start_episodes([a, b], status_fn=status, start_fn=start)
    status.assert_not_called()
    start.assert_not_called()


def test_real_production_requires_explicit_ack_before_any_launch(tmp_path, capsys):
    a, b = _eps(tmp_path)
    with (patch.object(multi, "ROOT", tmp_path),
          patch.object(multi, "start_episodes") as starter,
          patch.object(multi.global_image_capacity, "snapshot") as snapshot):
        rc = multi.main(["start", "--episode", str(a), "--episode", str(b)])
    assert rc == 2
    assert "MULTI_EPISODE_REAL_PRODUCTION_ACK_REQUIRED" in capsys.readouterr().out
    starter.assert_not_called()
    snapshot.assert_not_called()


def test_shared_capacity_unavailable_prevents_all_driver_starts(tmp_path, capsys):
    a, b = _eps(tmp_path)
    with (patch.object(multi, "ROOT", tmp_path),
          patch.object(multi.global_image_capacity, "snapshot",
                       side_effect=multi.global_image_capacity.GlobalImageCapacityError(
                           "GLOBAL_IMAGE_CAPACITY_SHARED_ROOT_UNAVAILABLE")),
          patch.object(multi, "start_episodes") as starter):
        rc = multi.main(["start", "--episode", str(a), "--episode", str(b),
                         "--ack-real-production"])
    assert rc == 2
    assert "GLOBAL_IMAGE_CAPACITY_SHARED_ROOT_UNAVAILABLE" in capsys.readouterr().out
    starter.assert_not_called()
