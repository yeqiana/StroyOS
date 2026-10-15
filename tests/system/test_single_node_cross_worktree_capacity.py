"""Real OS locks across linked Git worktrees; isolated temp repo only.

No production Provider, MySQL, Redis, or shared project capacity directories.
The mechanism remains local to one git-common-dir, not a cross-host lock.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT=Path(__file__).resolve().parents[2]
SYS=ROOT/"episodes"/"_system"
if str(SYS) not in sys.path:sys.path.insert(0,str(SYS))
import global_image_capacity as cap


CHILD=r"""
from pathlib import Path
import sys,time
sys.path.insert(0,sys.argv[1])
import global_image_capacity as cap
directory=cap.shared_directory(Path.cwd())
flag=Path(sys.argv[2]);count=int(sys.argv[3])
with cap.image_permits(count,shared_dir=directory,wait_seconds=6):
    flag.write_text("READY",encoding="utf-8")
    time.sleep(25)
"""


def _git(*args,cwd):
    p=subprocess.run(["git",*args],cwd=cwd,capture_output=True,text=True,timeout=15)
    assert p.returncode==0,(p.stderr or p.stdout)[-1000:]


def _await_ready(proc,flag):
    deadline=time.monotonic()+12
    while time.monotonic()<deadline:
        if flag.is_file():return
        if proc.poll() is not None:
            _,err=proc.communicate(timeout=3)
            pytest.fail(f"test worker died: {err[-1500:]}")
        time.sleep(.03)
    pytest.fail("test worker did not acquire OS permits")


def test_real_os_permits_shared_across_two_git_linked_worktrees_and_crash_cleanup(tmp_path):
    parent=tmp_path/"primary"
    linked=tmp_path/"linked"
    parent.mkdir()
    _git("init","-q",cwd=parent)
    _git("config","user.email","storyos-test-only@invalid",cwd=parent)
    _git("config","user.name","StoryOS Test",cwd=parent)
    _git("commit","--allow-empty","-qm","test-only-head",cwd=parent)
    _git("worktree","add","-q","-b","isolated-linked",str(linked),cwd=parent)
    shared=cap.shared_directory(parent)
    assert shared==cap.shared_directory(linked)
    # Git metadata is not a writable sandbox root on Windows. Both worktrees
    # must still share one local, crash-safe namespace outside protected .git.
    assert ".git" not in shared.parts
    assert shared.name.startswith("storyos-global-image-capacity-v2-")
    flag_a=tmp_path/"A.ready";flag_b=tmp_path/"B.ready"
    procs=[]
    try:
        for cwd,flag,num in ((parent,flag_a,2),(linked,flag_b,3)):
            process=subprocess.Popen([sys.executable,"-u","-c",CHILD,
                str(SYS),str(flag),str(num)],cwd=cwd,stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,text=True)
            procs.append(process)
        _await_ready(procs[0],flag_a)
        _await_ready(procs[1],flag_b)
        snapshot=cap.snapshot(shared_dir=shared)
        assert snapshot["observed_busy"]==5 and snapshot["observed_available"]==0
        with pytest.raises(cap.GlobalImageCapacityError,match="CAPACITY_BUSY"):
            with cap.image_permits(1,shared_dir=shared,wait_seconds=.1):
                pytest.fail("sixth image should never start")
        procs[0].kill();procs[0].wait(timeout=8)
        # OS locks must be released automatically after abrupt termination.
        with cap.image_permits(2,shared_dir=shared,wait_seconds=3):
            pass
        remaining=cap.snapshot(shared_dir=shared)
        assert remaining["observed_busy"]==3
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill();proc.wait(timeout=7)
            if proc.stderr:proc.stderr.close()


def test_independent_clones_have_different_scope_and_are_not_cross_host_authority(tmp_path):
    a=tmp_path/"a";b=tmp_path/"b"
    a.mkdir()
    _git("init","-q",cwd=a)
    _git("config","user.email","storyos-test-only@invalid",cwd=a)
    _git("config","user.name","StoryOS Test",cwd=a)
    _git("commit","--allow-empty","-qm","test-only-head",cwd=a)
    _git("clone","-q",str(a),str(b),cwd=tmp_path)
    assert cap.shared_directory(a)!=cap.shared_directory(b)
    assert cap.snapshot(shared_dir=cap.shared_directory(a))["scope"]=="LOCAL_GIT_COMMON_DIRECTORY"
