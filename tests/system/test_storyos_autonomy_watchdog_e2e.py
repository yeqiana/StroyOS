from test_storyos_autonomy_watchdog_common import wd,good,EP
import pytest

def test_crash_recovery_one_dispatch_then_running_then_budget(tmp_path,monkeypatch):
    report=[good(),good(),good("RUNNING"),good(),good()]
    launches=[]
    monkeypatch.setattr(wd.native,"canonical_episode",lambda _:wd.ROOT/EP)
    monkeypatch.setattr(wd.native,"native_environment",lambda:{})
    monkeypatch.setattr(wd.native,"preflight",lambda *a,**k:report.pop(0))
    def dispatch(*a):
        launches.append(1)
        return {"started":True,"driver_state":"RUNNING"}
    first=wd.tick(EP,acknowledged=True,data_root=tmp_path,
                  dispatch=dispatch,now_ts=1_800_000_000,max_attempts=1)
    assert first["status"]=="DISPATCHED" and len(launches)==1
    second=wd.tick(EP,acknowledged=True,data_root=tmp_path,
                   dispatch=dispatch,now_ts=1_800_000_400,max_attempts=1)
    assert second["status"]=="WAIT"
    third=wd.tick(EP,acknowledged=True,data_root=tmp_path,
                  dispatch=dispatch,now_ts=1_800_000_900,max_attempts=1)
    assert third["status"]=="BUDGET_EXHAUSTED"
    assert len(launches)==1

def test_launch_failure_consumes_budget_without_immediate_retry(tmp_path,monkeypatch):
    monkeypatch.setattr(wd.native,"canonical_episode",lambda _:wd.ROOT/EP)
    monkeypatch.setattr(wd.native,"native_environment",lambda:{})
    monkeypatch.setattr(wd.native,"preflight",lambda *a,**k:good())
    def broken(*a): raise TimeoutError("provider side effects unknown")
    first=wd.tick(EP,acknowledged=True,data_root=tmp_path,
                  dispatch=broken,now_ts=1_800_000_000,max_attempts=1)
    assert first["status"]=="HANDOFF_UNKNOWN"
    second=wd.tick(EP,acknowledged=True,data_root=tmp_path,
                   dispatch=broken,now_ts=1_800_000_400,max_attempts=1)
    assert second["status"]=="BUDGET_EXHAUSTED"

def test_false_positive_driver_start_is_not_claimed(tmp_path,monkeypatch):
    monkeypatch.setattr(wd.native,"canonical_episode",lambda _:wd.ROOT/EP)
    monkeypatch.setattr(wd.native,"native_environment",lambda:{})
    monkeypatch.setattr(wd.native,"preflight",lambda *a,**k:good())
    result=wd.tick(EP,acknowledged=True,data_root=tmp_path,
        dispatch=lambda *a:{"started":True,"driver_state":"EXITED"},
        now_ts=1_800_000_000,max_attempts=1)
    assert result["status"]=="HANDOFF_UNKNOWN"
    again=wd.tick(EP,acknowledged=True,data_root=tmp_path,
        dispatch=lambda *a:pytest.fail("no retry"),
        now_ts=1_800_000_800,max_attempts=1)
    assert again["status"]=="BUDGET_EXHAUSTED"
