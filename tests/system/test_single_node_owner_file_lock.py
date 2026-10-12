"""Single-host Driver lock regression: one Writer per Episode, OS crash release.

Only temporary filesystem and child processes; no Redis, MySQL or providers.
"""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
sys.path.insert(0, str(SYSTEM))
import runner_state_store

CHILD = r"""
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import runner_state_store
ep=Path(sys.argv[2])
if not runner_state_store.acquire_lock(ep):
    print("DENIED",flush=True)
    raise SystemExit(25)
print("HELD",flush=True)
sys.stdin.readline()
runner_state_store.release_lock(ep)
"""

def _spawn(episode: Path):
    return subprocess.Popen(
        [sys.executable,"-u","-c",CHILD,str(SYSTEM),str(episode)],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,
    )

def test_two_processes_same_episode_only_one_writer(tmp_path):
    ep=tmp_path/"ep1"
    ep.mkdir()
    holder=_spawn(ep)
    try:
        assert holder.stdout.readline().strip()=="HELD"
        duplicate=_spawn(ep)
        try:
            out,err=duplicate.communicate(timeout=8)
            assert duplicate.returncode==25,err
            assert out.strip()=="DENIED"
        finally:
            if duplicate.poll() is None:duplicate.kill();duplicate.wait(timeout=3)
        assert runner_state_store.acquire_lock(ep) is False
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=6)
        for stream in (holder.stdin,holder.stdout,holder.stderr):
            if stream:stream.close()
    assert runner_state_store.acquire_lock(ep) is True
    runner_state_store.release_lock(ep)


def test_different_episodes_have_independent_owner_and_release(tmp_path):
    a=tmp_path/"ep-a"
    b=tmp_path/"ep-b"
    a.mkdir();b.mkdir()
    child_a=_spawn(a)
    child_b=_spawn(b)
    try:
        assert child_a.stdout.readline().strip()=="HELD"
        assert child_b.stdout.readline().strip()=="HELD"
        assert runner_state_store.acquire_lock(a) is False
        assert runner_state_store.acquire_lock(b) is False
    finally:
        for proc in (child_a,child_b):
            if proc.poll() is None:proc.kill();proc.wait(timeout=5)
            for stream in (proc.stdin,proc.stdout,proc.stderr):
                if stream:stream.close()


def test_fresh_zero_length_lock_file_is_valid(tmp_path):
    ep=tmp_path/"ep-fresh"
    (ep/"meta").mkdir(parents=True)
    path=ep/runner_state_store.LOCK_REL
    path.touch()
    assert path.stat().st_size==0
    assert runner_state_store.acquire_lock(ep)
    runner_state_store.release_lock(ep)
    # No pre-lock write required: avoids racing with the other process.
    assert path.stat().st_size==0
