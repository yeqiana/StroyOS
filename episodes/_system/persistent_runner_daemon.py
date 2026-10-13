#!/usr/bin/env python3
"""Single-owner lifecycle and heartbeat around the bounded episode coordinator."""
from __future__ import annotations
import argparse
import os
import threading
from pathlib import Path
import episode_runner
import runner_state_store
import writer_owner_observation
import runtime_trace


def run(episode: Path, interval: int = 10, resume: bool = False, codex: str | None = None) -> int:
    episode = Path(episode).resolve()
    if not runner_state_store.acquire_lock(episode):
        return 25  # another live owner; never overwrite its state
    epoch = writer_owner_observation.new_epoch(episode)
    stop = threading.Event()
    heartbeat_error = []
    def heartbeat():
        while not stop.wait(max(0.1, min(interval or 1, 30))):
            try:
                runner_state_store.save(episode, pid=os.getpid())
                writer_owner_observation.emit(episode, epoch, held=True)
            except Exception as exc:
                heartbeat_error.append(str(exc))
                return
    thread = threading.Thread(target=heartbeat, name="storyos-heartbeat", daemon=True)
    try:
        runner_state_store.save(episode, status="RUNNING", pid=os.getpid(), resume_enabled=resume)
        writer_owner_observation.emit(episode, epoch, held=True)
        runtime_trace.emit(episode, {"event": "RUNNER_STARTED", "resume_enabled": resume,
                                     "codex": codex or ""})
        thread.start()
        rc = episode_runner.run_episode(episode, interval=interval, resume=resume, codex=codex)
        if heartbeat_error:
            raise RuntimeError("heartbeat persistence failed: " + heartbeat_error[0])
        runtime_trace.emit(episode, {"event": "RUNNER_EXIT", "return_code": rc})
        return rc
    except BaseException as exc:
        runner_state_store.save(episode, status="FAILED", error=str(exc)[:1000])
        raise
    finally:
        stop.set()
        if thread.is_alive():
            thread.join(timeout=5)
        writer_owner_observation.emit(episode, epoch, held=False)
        runner_state_store.release_lock(episode)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("episode", type=Path)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--codex", default=None)
    args = parser.parse_args()
    return run(args.episode, args.interval, args.resume, args.codex)


if __name__ == "__main__":
    raise SystemExit(main())
