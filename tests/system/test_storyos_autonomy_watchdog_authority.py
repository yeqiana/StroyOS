from test_storyos_autonomy_watchdog_common import wd,good,EP
import pytest

def test_no_ack_never_writes_or_dispatches(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(wd.native,"canonical_episode",lambda _: wd.ROOT/EP)
    monkeypatch.setattr(wd.native,"native_environment",lambda:{})
    monkeypatch.setattr(wd.native,"preflight",lambda *a,**k:good())
    result=wd.tick(EP,acknowledged=False,data_root=tmp_path,
                   dispatch=lambda *a:calls.append(1),now_ts=1_800_000_000)
    assert result["status"]=="ACK_REQUIRED"
    assert not calls and list(tmp_path.iterdir())==[]

def test_second_authority_probe_blocks_toc_tou_without_spending(tmp_path,monkeypatch):
    reports=[good(),good()]
    reports[1]["attempt"]["outcome_unknown_assets"]=["frame-06"]
    calls=[]
    monkeypatch.setattr(wd.native,"canonical_episode",lambda _: wd.ROOT/EP)
    monkeypatch.setattr(wd.native,"native_environment",lambda:{})
    monkeypatch.setattr(wd.native,"preflight",lambda *a,**k:reports.pop(0))
    result=wd.tick(EP,acknowledged=True,data_root=tmp_path,
                   dispatch=lambda *a:calls.append(1),now_ts=1_800_000_000)
    assert result["status"]=="AUTHORITY_CHANGED"
    assert not calls
    assert not list(tmp_path.glob("*.json"))

def test_same_episode_process_lock_is_exclusive(tmp_path):
    with wd.episode_lock(tmp_path,EP):
        with pytest.raises(wd.LockBusy):
            with wd.episode_lock(tmp_path,EP):
                pass

def test_cross_process_lock_refuses_second_writer(tmp_path):
    import subprocess, sys
    source = (
        "import sys,time; from pathlib import Path;"
        "import platform as stdlib_platform;"
        "stdlib_platform.__path__=[str(Path(sys.argv[1]).resolve().parent/'platform')];"
        "sys.path.insert(0,sys.argv[1]);import storyos_autonomy_watchdog as w;"
        "ctx=w.episode_lock(Path(sys.argv[2]),sys.argv[3]);"
        "ctx.__enter__();print('LOCKED',flush=True);time.sleep(1.5);ctx.__exit__(None,None,None)"
    )
    process=subprocess.Popen(
        [sys.executable,"-P","-c",source,str(wd.ROOT/"scripts"),str(tmp_path),EP],
        cwd=wd.ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        child_banner=process.stdout.readline().strip()
        assert child_banner=="LOCKED", ("watchdog child startup", process.poll(), process.stderr.read()[-800:])
        with pytest.raises(wd.LockBusy):
            with wd.episode_lock(tmp_path,EP):
                pass
    finally:
        process.wait(timeout=5)
    assert process.returncode==0


def test_plan_is_pure_and_never_creates_watchdog_state(tmp_path,monkeypatch):
    monkeypatch.setattr(wd.native,"canonical_episode",lambda _:wd.ROOT/EP)
    monkeypatch.setattr(wd.native,"native_environment",lambda:{})
    monkeypatch.setattr(wd.native,"preflight",lambda *a,**k:good())
    monkeypatch.setattr(wd,"_canonical_data_root",
                        lambda:pytest.fail("plan may not create or inspect watchdog data"))
    assert wd.plan(EP)["action"]=="RECOVER"
    assert list(tmp_path.iterdir())==[]

def test_transient_authority_outage_does_not_reserve_or_dispatch(tmp_path,monkeypatch):
    monkeypatch.setattr(wd.native,"canonical_episode",lambda _:wd.ROOT/EP)
    monkeypatch.setattr(wd.native,"native_environment",lambda:{})
    monkeypatch.setattr(wd.native,"preflight",
                        lambda *a,**k: (_ for _ in ()).throw(OSError("db disconnect")))
    result=wd.tick(EP,acknowledged=True,data_root=tmp_path,
        dispatch=lambda *a:pytest.fail("never dispatch"),now_ts=1_800_000_000)
    assert result["status"]=="PREFLIGHT_UNAVAILABLE"
    assert not list(tmp_path.glob("*.json"))
