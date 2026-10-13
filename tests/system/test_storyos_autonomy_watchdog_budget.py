from test_storyos_autonomy_watchdog_common import wd,good,EP
import pytest
import json

def test_budget_persists_across_processes_and_limits_restarts(tmp_path):
    file=tmp_path/"journal.json"
    assert wd.reserve_recovery(file,EP,now_ts=1_800_000_000,max_attempts=2,cooldown=300)["ok"]
    assert wd.reserve_recovery(file,EP,now_ts=1_800_000_050,max_attempts=2,cooldown=300)["reason"]=="COOLDOWN"
    assert wd.reserve_recovery(file,EP,now_ts=1_800_000_300,max_attempts=2,cooldown=300)["ok"]
    assert wd.reserve_recovery(file,EP,now_ts=1_800_000_900,max_attempts=2,cooldown=300)["reason"]=="BUDGET_EXHAUSTED"
    assert len(json.loads(file.read_text(encoding="utf-8"))["attempts"])==2

def test_corrupt_journal_or_rollback_fails_closed(tmp_path):
    file=tmp_path/"journal.json"
    file.write_text('{"schema_version":99}',encoding="utf-8")
    assert wd.reserve_recovery(file,EP,now_ts=1_800_000_000)["reason"]=="JOURNAL_INVALID"
    file.unlink()
    assert wd.reserve_recovery(file,EP,now_ts=1_800_000_000)["ok"]
    assert wd.reserve_recovery(file,EP,now_ts=1_799_999_990)["reason"]=="CLOCK_ROLLBACK"

def test_reservation_survives_crash_and_new_window(tmp_path):
    file=tmp_path/"journal.json"
    assert wd.reserve_recovery(file,EP,now_ts=1_800_000_000,max_attempts=1)["ok"]
    assert wd.reserve_recovery(file,EP,now_ts=1_800_000_400,max_attempts=1)["reason"]=="BUDGET_EXHAUSTED"
    assert wd.reserve_recovery(file,EP,now_ts=1_800_100_000,max_attempts=1)["ok"]

def test_journal_from_other_episode_is_rejected(tmp_path):
    file=tmp_path/"journal.json"
    assert wd.reserve_recovery(file,EP,now_ts=1_800_000_000)["ok"]
    assert wd.reserve_recovery(file,"episodes/00_独立篇/other",
                                now_ts=1_800_000_500)["reason"]=="JOURNAL_INVALID"


def test_handoff_receipt_failure_never_claims_started(tmp_path,monkeypatch):
    monkeypatch.setattr(wd.native,"canonical_episode",lambda _: wd.ROOT/EP)
    monkeypatch.setattr(wd.native,"native_environment",lambda:{})
    monkeypatch.setattr(wd.native,"preflight",lambda *a,**k:good())
    monkeypatch.setattr(wd,"_mark_handoff",lambda *a:False)
    result=wd.tick(EP,acknowledged=True,data_root=tmp_path,
        dispatch=lambda *a:{"started":True,"driver_state":"RUNNING"},
        now_ts=1_800_000_000)
    assert result["status"]=="HANDOFF_UNKNOWN"
    assert result["dispatched"] is False
    assert result["recovery_attempt_reserved"] is True

def test_nan_journal_and_nan_clock_fail_closed(tmp_path):
    file=tmp_path/"journal.json"
    assert wd.reserve_recovery(file,EP,now_ts=float("nan"))["reason"]=="BUDGET_POLICY_INVALID"
    assert not file.exists()
    file.write_text('{"schema_version":1,"episode":"'+EP+
                    '","last_observed_at":NaN,"attempts":[]}',encoding="utf-8")
    assert wd.reserve_recovery(file,EP,now_ts=1_800_000_000)["reason"]=="JOURNAL_INVALID"
