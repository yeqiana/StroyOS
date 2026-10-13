#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The official detached resident Driver: `story_os.py driver start <episode>`.

A scoped step is a Codex conversation that takes tens of minutes (CREATIVE_STORY
~16 min, PREIMAGE_COMPILE ~69 min measured on 2026-09-15). The host tool that
launches Story OS gives each call 300 seconds, so a Driver started in the
foreground is killed long before the step it is running. That is not a Story OS
timeout and it is not a Codex failure -- it is the launcher's budget, and the
only fix is for the Driver to stop being a child of the launcher.

`.storyos_cache/dag_detach.py` proved the mechanism but is an operator's private
script: it is not on any Story OS entrypoint, it keeps one global pid file for
the whole repository, and it starts `runtime_dag.py` directly -- bypassing the
resident Driver that P0-B makes the single production owner. This module is the
same mechanism as a product capability, launching the one resident Driver.

What it does NOT do, deliberately:

  * It never kills anything. Not the Driver, not Codex, and never
    `taskkill /IM codex.exe` -- which would take out the user's Codex desktop
    backend along with the orphan. Recovery is "start the Driver again"; the
    orphaned task's result is claimed by in_flight_codex_task, not destroyed.
  * It does not spawn the DAG as a grandchild. The detached process *is* the
    Driver: it holds the runner owner lock, writes the heartbeat and executes
    `runtime_dag.execute` in-process, so the recorded pid is the process that
    actually does the work and the log file is that process's own stdout.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import codex_user_runner
import runtime_atomic_store
import runtime_timeout_policy
import runtime_ownership
import story_json
import hot_state_bridge
import storage_config

# `driver status` is read by the host to decide whether the Driver is alive and
# how far it got. On this machine the console defaults to cp936, which turns the
# Chinese lines into mojibake once the output is piped, so pin UTF-8 here.
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

REL = Path("meta/runtime/driver.json")
BEACON_REL = Path("meta/runtime/driver-beacon.json")
LOG_DIR = Path("meta/runtime/driver-logs")
SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ENV_PATH = REPO_ROOT / ".storyos/runtime-launcher/runtime.env"

RUNNING = "RUNNING"


class DetachedLaunchError(RuntimeError):
    """The host forbids a trustworthy direct detached launch."""

# A pid alone does not identify our Driver: Windows recycles pids, and a killed
# Driver whose pid was handed to an unrelated process would read as RUNNING
# forever -- the same class of error that hid a dead Driver for 12 minutes on
# 2026-09-15. The resident process therefore beats a beacon, and liveness is only
# trusted when something is beating for that exact pid. The window is generous
# because a scoped step blocks the Driver's own loop for tens of minutes; the
# beacon is its own thread, so it keeps beating anyway.
BEACON_INTERVAL_SECONDS = 15
BEACON_TOLERANCE_SECONDS = 90


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _record_path(ep: Path) -> Path:
    return Path(ep) / REL


def _read_record(ep: Path) -> dict:
    hot = hot_state_bridge.read(Path(ep), "DRIVER_STATE")
    value = hot_state_bridge.value_or_fallback(
        hot,
        lambda: story_json.read_json(_record_path(ep), default={}),
        default={},
    )
    return value if isinstance(value, dict) else {}


def _write_record(ep: Path, fields: dict) -> dict:
    path = _record_path(ep)
    current = _read_record(ep)
    current.update(fields)
    current["schema_version"] = SCHEMA_VERSION
    current["updated_at"] = now()
    if hot_state_bridge.compatibility_write_allowed():
        path.parent.mkdir(parents=True, exist_ok=True)
        runtime_atomic_store.atomic_write_json(path, current)
    hot_state_bridge.mirror(ep, "DRIVER_STATE", current)
    return current


def _begin_record(ep: Path, fields: dict) -> dict:
    """Start a fresh Driver epoch without leaking terminal/carrier fields from the last one."""
    path = _record_path(ep)
    current = dict(fields)
    current["schema_version"] = SCHEMA_VERSION
    current["updated_at"] = now()
    if hot_state_bridge.compatibility_write_allowed():
        path.parent.mkdir(parents=True, exist_ok=True)
        runtime_atomic_store.atomic_write_json(path, current)
    hot_state_bridge.mirror(ep, "DRIVER_STATE", current)
    return current


# --- beacon ------------------------------------------------------------------

def _beacon_path(ep: Path) -> Path:
    return Path(ep) / BEACON_REL


def write_beacon(ep: Path, pid: int, *, beat: int | None = None) -> dict:
    path = _beacon_path(ep)
    previous = _read_beacon(ep)
    data = {
        "schema_version": SCHEMA_VERSION,
        "pid": int(pid),
        "at": now(),
        "beat": int(previous.get("beat") or 0) + 1 if beat is None else int(beat),
    }
    if hot_state_bridge.compatibility_write_allowed():
        path.parent.mkdir(parents=True, exist_ok=True)
        runtime_atomic_store.atomic_write_json(path, data)
    hot_state_bridge.mirror(ep, "DRIVER_HEARTBEAT", data)
    return data


def _read_beacon(ep: Path) -> dict:
    hot = hot_state_bridge.read(Path(ep), "DRIVER_HEARTBEAT")
    value = hot_state_bridge.value_or_fallback(
        hot,
        lambda: story_json.read_json(_beacon_path(ep), default={}),
        default={},
    )
    return value if isinstance(value, dict) else {}


def beacon_age(ep: Path, pid: int) -> float | None:
    """Seconds since that exact pid last beat, or None if it never did."""
    data = _read_beacon(ep)
    if int(data.get("pid") or 0) != int(pid):
        return None
    try:
        at = dt.datetime.fromisoformat(str(data.get("at") or ""))
    except (TypeError, ValueError):
        return None
    return (dt.datetime.now(dt.timezone.utc).astimezone() - at).total_seconds()


def _beating(ep: Path, pid: int) -> bool:
    age = beacon_age(ep, pid)
    return age is not None and age <= BEACON_TOLERANCE_SECONDS


def _start_beacon(ep: Path, pid: int, interval: float) -> threading.Thread:
    """Beat in this process for as long as it lives.

    A daemon thread on purpose: it must never keep a finished Driver alive, and it
    must keep beating while the main thread is blocked inside a 69-minute step.
    """
    def loop() -> None:
        while True:
            try:
                write_beacon(ep, pid)
            except Exception:
                pass
            time.sleep(max(1.0, float(interval)))

    thread = threading.Thread(target=loop, name="storyos-driver-beacon", daemon=True)
    thread.start()
    return thread


# --- liveness ----------------------------------------------------------------

def process_table() -> list[tuple[int, int, str]]:
    """[(pid, ppid, exe)] via Toolhelp32. Empty when the snapshot is unavailable.

    A system-wide snapshot, so it sees processes in other sessions -- which
    OpenProcess does not (2026-09-15: OpenProcess returned ACCESS_DENIED for a
    live Session 0 pid *and* for the same pid after it died, so an error code
    could not tell the two apart, and reporting "alive" off it would have hidden
    a dead Driver for 12 minutes).
    """
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.Process32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32)]
        k32.Process32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32)]
        snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)
        if not snap or snap == ctypes.c_void_p(-1).value:
            return []
        out: list[tuple[int, int, str]] = []
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            ok = k32.Process32First(ctypes.c_void_p(snap), ctypes.byref(entry))
            while ok:
                out.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID),
                            entry.szExeFile.decode("ascii", "replace")))
                ok = k32.Process32Next(ctypes.c_void_p(snap), ctypes.byref(entry))
        finally:
            k32.CloseHandle(ctypes.c_void_p(snap))
        return out
    except Exception:
        return []


def liveness(pid: int) -> str:
    """ALIVE / DEAD / UNKNOWN. UNKNOWN only when nothing could be observed."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return "DEAD"
    if pid <= 0:
        return "DEAD"
    table = process_table()
    if table:
        return "ALIVE" if any(row[0] == pid for row in table) else "DEAD"
    try:
        import codex_user_runner

        return "ALIVE" if codex_user_runner._pid_alive(pid) else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def alive(pid: int) -> bool:
    return liveness(pid) == "ALIVE"


def interpret_rc(raw: str) -> str:
    """Translate a recorded exit code. 20 is the engine's "stopped for the host"."""
    try:
        code = int(str(raw).split()[0])
    except (TypeError, ValueError, IndexError):
        return ""
    if code == 0:
        return "正常结束"
    if code == 20:
        return "HOST_ACTION_REQUIRED：引擎主动停下等宿主动作，不是崩溃"
    if code == 25:
        return "已有 Driver 持有 owner lock（双开被拒）"
    if code in {-1073741510, 0xC000013A}:
        return "Ctrl-C / 控制台关闭"
    if code < 0 or code > 0x7FFFFFFF:
        return "被强杀（TerminateProcess：taskkill 或宿主超时）"
    return ""


def exit_code_of(record: dict) -> str:
    """The recorded exit code, or "" when the process never got to write one."""
    raw = str(record.get("rc") or "").strip()
    if not raw or raw.split()[0] == RUNNING:
        return ""
    return raw.split()[0]


# --- status ------------------------------------------------------------------

def status(ep: Path) -> dict:
    """Read-only. Reports what the Driver left behind; starts nothing.

    The states, and what each one licenses:

        NEVER_STARTED          no pid was ever recorded
        RUNNING                the recorded pid is alive AND beating for that pid
        ALIVE_NOT_BEATING      the pid is alive but nothing is beating: either a
                               wedged Driver or an unrelated process that inherited
                               a recycled pid. Never treated as "our Driver is fine"
                               and never a reason to refuse a restart.
        EXITED                 it wrote an exit code and cleared its pid
        ABNORMAL_DISAPPEARANCE gone with no exit code -- killed, or the host's
                               timeout took it
        UNKNOWN                the process table could not be read at all
    """
    ep = Path(ep).resolve()
    record = _read_record(ep)
    pid = int(record.get("pid") or 0)
    state = liveness(pid) if pid else "DEAD"
    rc = exit_code_of(record)
    age = beacon_age(ep, pid) if pid else None
    log = Path(str(record.get("log"))) if record.get("log") else None
    heartbeat = {}
    try:
        import runner_state_store

        heartbeat = runner_state_store.load(ep)
    except Exception:
        heartbeat = {}

    if not pid:
        # The Driver clears its own pid as part of writing its exit code, so a
        # finished Driver is unambiguous even during the interpreter's teardown --
        # the ~2 s between recording `rc` and the process actually leaving the
        # table used to read as "alive with an exit code", which is not a state a
        # human should ever have to interpret.
        driver_state = "EXITED" if rc else "NEVER_STARTED"
    elif state == "UNKNOWN":
        driver_state = "UNKNOWN"
    elif state == "ALIVE":
        driver_state = "RUNNING" if _beating(ep, pid) else "ALIVE_NOT_BEATING"
    else:
        driver_state = "EXITED" if rc else "ABNORMAL_DISAPPEARANCE"

    log_bytes = log.stat().st_size if (log is not None and log.is_file()) else None
    return {
        "schema_version": SCHEMA_VERSION,
        "episode": ep.name,
        "driver_state": driver_state,
        "pid": pid,
        "liveness": state,
        "started_at": record.get("started_at"),
        "updated_at": record.get("updated_at"),
        "exit_code": rc,
        "exit_note": interpret_rc(rc) if rc else "",
        "log": str(log) if log is not None else "",
        "log_bytes": log_bytes,
        "beacon_at": _read_beacon(ep).get("at"),
        "beacon_age_seconds": None if age is None else round(age, 1),
        "heartbeat_status": heartbeat.get("status"),
        "heartbeat_at": heartbeat.get("heartbeat"),
        "codex": record.get("codex") or "",
        "carrier": record.get("carrier") or "",
        "carrier_task": record.get("carrier_task") or "",
        "record": record,
    }


def log_tail(ep: Path, lines: int = 20) -> list[str]:
    record = _read_record(Path(ep).resolve())
    log = Path(str(record.get("log"))) if record.get("log") else None
    if log is None or not log.is_file():
        return []
    try:
        return log.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, int(lines)):]
    except OSError:
        return []


# --- launch ------------------------------------------------------------------

def _detach(cmd: list[str], log: Path, *, require_breakaway: bool = False) -> subprocess.Popen:
    """Spawn cmd with its own console, process group and durable log.

    Generic probes may fall back to a plain detached child. Production Driver
    launch may not: under a restrictive Windows Job that fallback child is killed
    when the host tool call closes, which is exactly the false-success
    ABNORMAL_DISAPPEARANCE observed on 2026-09-15.
    """
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        flags |= getattr(subprocess, name, 0)
    cwd = str(Path(__file__).resolve().parents[2])

    def spawn(extra: int) -> subprocess.Popen:
        with log.open("ab") as handle:
            return subprocess.Popen(
                cmd, cwd=cwd, stdin=subprocess.DEVNULL,
                stdout=handle, stderr=subprocess.STDOUT,
                close_fds=True, creationflags=flags | extra,
            )

    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    try:
        return spawn(breakaway)
    except OSError as exc:
        if require_breakaway:
            raise DetachedLaunchError("HOST_JOB_BREAKAWAY_DENIED") from exc
        return spawn(0)


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def carrier_task_name(ep: Path) -> str:
    """Stable per-Episode Windows carrier identity; contains no episode title."""
    material = str(Path(ep).resolve()).casefold().encode("utf-8")
    return "StoryOSDriver-" + hashlib.sha256(material).hexdigest()[:16]


def resolve_task_carrier_user() -> tuple[str, str]:
    """Resolve the interactive Windows principal that must own the Driver.

    A service/SYSTEM launcher is allowed to *request* production, but the durable
    Driver must not inherit that identity: Codex uses the logged-in user's profile
    and credentials. Prefer the current identity when it is already interactive;
    otherwise accept only a live interactive codex-user-runner endpoint as proof.
    Never guess a username and never register an AtLogOn task for SYSTEM.
    """
    current = str(codex_user_runner.current_identity() or "").strip()
    if current and not codex_user_runner.is_non_interactive(current):
        return current, "current_interactive_identity"
    endpoint = codex_user_runner.read_endpoint(required=False)
    endpoint_user = str(endpoint.get("user") or "").strip()
    endpoint_pid = endpoint.get("pid")
    if (endpoint_user and not codex_user_runner.is_non_interactive(endpoint_user)
            and codex_user_runner._pid_alive(endpoint_pid)):
        expected = codex_user_runner.expected_user()
        if expected and not codex_user_runner.user_matches(expected, endpoint_user):
            raise DetachedLaunchError(
                f"TASK_CARRIER_INTERACTIVE_USER_MISMATCH expected={expected} endpoint={endpoint_user}"
            )
        return endpoint_user, "live_codex_user_runner_endpoint"
    raise DetachedLaunchError(
        "TASK_CARRIER_INTERACTIVE_USER_UNAVAILABLE: launcher is non-interactive and no live "
        "interactive Codex user-runner endpoint can prove the target user"
    )


def task_carrier_script(ep: Path, cmd: list[str], *, carrier_user: str | None = None) -> tuple[str, str]:
    """Build a Task Scheduler carrier for the exact same resident Driver."""
    task = carrier_task_name(ep)
    user = str(carrier_user or resolve_task_carrier_user()[0]).strip()
    if not user or codex_user_runner.is_non_interactive(user):
        raise DetachedLaunchError(f"TASK_CARRIER_NON_INTERACTIVE_USER_FORBIDDEN: {user or '<empty>'}")
    executable = str(cmd[0])
    arguments = subprocess.list2cmdline([str(x) for x in cmd[1:]])
    root = str(Path(__file__).resolve().parents[2])
    script = (
        "$name={task}; "
        "$user={user}; "
        "$a=New-ScheduledTaskAction -Execute {exe} -Argument {args} -WorkingDirectory {cwd}; "
        "$t=New-ScheduledTaskTrigger -AtLogOn -User $user; "
        "$p=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited; "
        "$s=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero); "
        "Register-ScheduledTask -TaskName $name -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null; "
        "Start-ScheduledTask -TaskName $name"
    ).format(task=_ps_quote(task), user=_ps_quote(user), exe=_ps_quote(executable),
             args=_ps_quote(arguments), cwd=_ps_quote(root))
    return task, script


def _start_task_carrier(ep: Path, cmd: list[str]) -> tuple[str, str, str]:
    """Ask Windows Task Scheduler to own the Driver under a proven interactive user."""
    if os.name != "nt":
        raise DetachedLaunchError("TASK_SCHEDULER_CARRIER_REQUIRES_WINDOWS")
    carrier_user, carrier_user_source = resolve_task_carrier_user()
    task, script = task_carrier_script(ep, cmd, carrier_user=carrier_user)
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=str(Path(__file__).resolve().parents[2]), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=runtime_timeout_policy.seconds("driver_carrier_control"),
    )
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip().replace("\n", " ")[-1200:]
        raise DetachedLaunchError(f"TASK_SCHEDULER_CARRIER_FAILED rc={done.returncode}: {detail}")
    return task, carrier_user, carrier_user_source


def _wait_for_task_carrier(ep: Path, requested_settle: float) -> dict:
    """Wait until an async scheduled task has actually entered or exited Driver.

    With settle=0, proving that the Driver process entered is enough.  With a
    positive settle window, preserve the old direct-launch contract: keep watching
    for a quick normal exit instead of returning the instant the PID appears.
    """
    requested = float(requested_settle or 0.0)
    deadline = time.monotonic() + max(5.0, requested)
    latest = _read_record(ep)
    while time.monotonic() < deadline:
        latest = _read_record(ep)
        rc = exit_code_of(latest)
        if rc:
            return latest
        if int(latest.get("pid") or 0) > 0 and requested <= 0:
            return latest
        time.sleep(0.1)
    return latest


def _storage_mode_args() -> list[str]:
    """Serialize only non-secret storage authority modes into detached child argv."""
    return [
        "--runtime-store-mode", storage_config.runtime_store_config()["mode"],
        "--episode-meta-store-mode", storage_config.episode_meta_store_config()["mode"],
        "--hot-state-mode", storage_config.hot_state_config()["mode"],
    ]


def _native_child_scope_args() -> list[str]:
    """Carry a validated native Codex route across detached/task carriers."""
    mode = str(os.environ.get("STORY_OS_PRODUCTION_MODE") or "")
    image = str(os.environ.get("STORY_OS_IMAGE_EXECUTOR") or "")
    if mode != "CODEX_MANAGED":
        return []
    if image != "CODEX":
        raise ValueError("NATIVE_DRIVER_SCOPE_MISMATCH")
    return ["--production-mode", "CODEX_MANAGED", "--image-executor", "CODEX"]


def _load_child_runtime_environment(
    *,
    runtime_store_mode: str,
    episode_meta_store_mode: str,
    hot_state_mode: str,
    production_mode: str | None = None,
    image_executor: str | None = None,
) -> None:
    """Load secrets, then restore explicitly bound authority and Codex routing."""
    if bool(production_mode) != bool(image_executor) or (
        production_mode and (production_mode, image_executor) != ("CODEX_MANAGED", "CODEX")
    ):
        raise ValueError("NATIVE_DRIVER_SCOPE_MISMATCH")
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts.phase9_runtime_launcher import load_runtime_env_file

    merged, _loaded = load_runtime_env_file(RUNTIME_ENV_PATH, dict(os.environ))
    os.environ.update(merged)
    os.environ["STORYOS_RUNTIME_STORE_MODE"] = runtime_store_mode
    os.environ["STORYOS_EPISODE_META_STORE_MODE"] = episode_meta_store_mode
    os.environ["STORYOS_HOT_STATE_MODE"] = hot_state_mode
    if production_mode == "CODEX_MANAGED":
        # Task Scheduler may inherit an unrelated service account proxy.
        for key in ("OPENAI_BASE_URL", "OPENAI_API_BASE", "CODEX_BASE_URL",
                    "STORY_OS_OPENCODEX_URL", "OPENAI_API_KEY", "STORY_OS_RUNTIME",
                    "STORY_OS_IMAGE_RUNTIME"):
            os.environ.pop(key, None)
        os.environ["STORY_OS_PRODUCTION_MODE"] = production_mode
        os.environ["STORY_OS_IMAGE_EXECUTOR"] = image_executor


def _add_storage_mode_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runtime-store-mode", choices=("jsonl", "mysql", "dual"), required=True)
    parser.add_argument("--episode-meta-store-mode", choices=("json", "mysql", "dual"), required=True)
    parser.add_argument("--hot-state-mode", choices=("file", "redis", "dual"), required=True)


def launch(ep: Path, *, codex: str | None = None, interval: int = 10,
           resume: bool = False, settle_seconds: float = 3.0) -> dict:
    """Start the one resident Driver with a carrier that really outlives the host."""
    ep = Path(ep).resolve()
    # W-11: the detached Driver is the resident production owner. A recorded
    # rollback to V2 must stop new V3 Driver launches instead of being ignored.
    runtime_ownership.assert_v3_owner("runtime_driver.launch")
    if not (ep / "meta").is_dir():
        return {"started": False, "reason": "NOT_AN_EPISODE", "episode": str(ep)}
    current = status(ep)
    if current["driver_state"] == "RUNNING":
        return {"started": False, "reason": "DRIVER_ALREADY_RUNNING", "pid": current["pid"],
                "episode": str(ep)}

    log_dir = ep / LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log = log_dir / f"driver_{stamp}.log"
    direct_cmd = [sys.executable, "-u", str(Path(__file__).resolve()), "_serve", str(ep),
                  "--interval", str(max(0, int(interval)))]
    direct_cmd += _storage_mode_args() + _native_child_scope_args()
    if codex:
        direct_cmd += ["--codex", str(codex)]
    if resume:
        direct_cmd.append("--resume")

    carrier = "DIRECT_BREAKAWAY"
    carrier_task = ""
    carrier_user = ""
    carrier_user_source = ""
    pid = 0
    try:
        process = _detach(direct_cmd, log, require_breakaway=True)
        pid = int(process.pid)
        _begin_record(ep, {
            "pid": pid, "episode": str(ep), "log": str(log), "cmd": direct_cmd,
            "codex": str(codex or ""), "interval": int(interval), "resume": bool(resume),
            "started_at": now(), "rc": RUNNING, "carrier": carrier,
        })
        write_beacon(ep, pid, beat=1)
    except DetachedLaunchError as direct_error:
        carrier = "WINDOWS_TASK_SCHEDULER"
        task_cmd = [sys.executable, "-u", str(Path(__file__).resolve()), "_serve_task", str(ep),
                    "--interval", str(max(0, int(interval))), "--log", str(log)]
        task_cmd += _storage_mode_args() + _native_child_scope_args()
        if codex:
            task_cmd += ["--codex", str(codex)]
        if resume:
            task_cmd.append("--resume")
        _begin_record(ep, {
            "pid": 0, "episode": str(ep), "log": str(log), "cmd": task_cmd,
            "codex": str(codex or ""), "interval": int(interval), "resume": bool(resume),
            "started_at": now(), "rc": RUNNING, "carrier": carrier,
            "direct_detach_error": str(direct_error),
        })
        try:
            carrier_task, carrier_user, carrier_user_source = _start_task_carrier(ep, task_cmd)
        except DetachedLaunchError as task_error:
            _write_record(ep, {"pid": 0, "rc": f"901 {now()}", "carrier_error": str(task_error)})
            return {"started": False, "pid": 0, "log": str(log), "episode": str(ep),
                    "reason": "NO_DURABLE_WINDOWS_CARRIER", "exit_code": "901",
                    "exit_note": str(task_error), "carrier": carrier}
        _write_record(ep, {"carrier_task": carrier_task, "carrier_user": carrier_user,
                           "carrier_user_source": carrier_user_source})

    if carrier == "WINDOWS_TASK_SCHEDULER":
        record = _wait_for_task_carrier(ep, settle_seconds)
    else:
        if settle_seconds:
            time.sleep(float(settle_seconds))
        record = _read_record(ep)
    pid = int(record.get("pid") or pid or 0)
    rc = exit_code_of(record)
    final = liveness(pid) if pid else "DEAD"
    if rc:
        return {"started": True, "pid": pid, "log": str(log), "episode": str(ep),
                "driver_state": "EXITED", "exit_code": rc, "exit_note": interpret_rc(rc),
                "carrier": carrier, "carrier_task": carrier_task}
    if final == "ALIVE":
        return {"started": True, "pid": pid, "log": str(log), "episode": str(ep),
                "driver_state": "RUNNING", "carrier": carrier, "carrier_task": carrier_task}
    return {"started": False, "pid": pid, "log": str(log), "episode": str(ep),
            "reason": "EXITED_DURING_STARTUP", "exit_code": "", "exit_note": "",
            "carrier": carrier, "carrier_task": carrier_task}


def recover(ep: Path) -> dict:
    """Report an abnormally gone Driver and what a safe recovery is.

    Safe recovery is a relaunch. Nothing is killed: a Codex task the dead Driver
    started is still running under the resident user-mode runner, and
    in_flight_codex_task claims its result instead of destroying it.
    """
    report = status(Path(ep))
    if report["driver_state"] == "RUNNING":
        return {**report, "recovery": "NONE_REQUIRED"}
    if report["driver_state"] == "NEVER_STARTED":
        return {**report, "recovery": "START"}
    if report["driver_state"] == "EXITED":
        # Read-only advice must not invite blind restarts after a hard stop,
        # exhausted technical budget or unresolved host action.
        code = str(report.get("exit_code") or "").strip().split(" ", 1)[0]
        if code != "0":
            return {**report, "recovery": "REMEDIATION_REQUIRED",
                    "note": "Driver exited nonzero; inspect canonical gates/Attempt authority "
                            "before a new production admission."}
        return {**report, "recovery": "START_IF_WORK_REMAINS"}
    if report["driver_state"] in {"UNKNOWN", "ALIVE_NOT_BEATING"}:
        return {**report, "recovery": "VERIFY_BEFORE_START",
                "note": f"{report['driver_state']}：该 pid 存在，但没有为该 pid 跳动的心跳——"
                        "可能是 Driver 卡死，也可能是无关进程复用了这个 pid。"
                        "start 会照常放行，真正的双开防线是 owner lock（双开返回 25）。"}
    return {
        **report,
        "recovery": "START",
        "note": "Driver 异常消失（退出码未落盘，通常是被 TerminateProcess 强杀或宿主超时连带）。"
                "恢复方式是重新 start；若它当时正跑 scoped 步骤，Codex 结果由 in-flight 附件领取，不要杀 codex。",
    }


# --- the detached process itself ---------------------------------------------

def serve(ep: Path, *, codex: str | None = None, interval: int = 10, resume: bool = False) -> int:
    """Run the resident Driver in THIS process. Returns its exit code.

    Returns it as the process exit code too, and records it in driver.json: a
    detached process has no parent left to `wait()` on it, so this file is the
    only place its exit code can survive.
    """
    ep = Path(ep).resolve()
    write_beacon(ep, os.getpid(), beat=1)
    _write_record(ep, {"pid": os.getpid(), "rc": RUNNING})
    _start_beacon(ep, os.getpid(), BEACON_INTERVAL_SECONDS)
    try:
        import persistent_runner_daemon

        rc = persistent_runner_daemon.run(ep, interval=interval, resume=resume, codex=codex)
    except BaseException as exc:  # a crash must still leave an exit code behind
        _finish(ep, 900)
        print(f"DRIVER CRASH {exc!r}", flush=True)
        raise
    _finish(ep, rc)
    print(f"DRIVER EXIT rc={rc} {interpret_rc(str(rc))}", flush=True)
    return rc


def serve_task(ep: Path, log: Path, *, codex: str | None = None,
               interval: int = 10, resume: bool = False) -> int:
    """Task-Scheduler entry: own stdout/stderr and run the exact same Driver."""
    ep = Path(ep).resolve()
    log = Path(log).resolve()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8", errors="replace", buffering=1) as handle:
        with contextlib.redirect_stdout(handle), contextlib.redirect_stderr(handle):
            existing = status(ep)
            if existing["driver_state"] == "RUNNING" and int(existing.get("pid") or 0) != os.getpid():
                print(f"DRIVER TASK CARRIER SKIP existing_pid={existing['pid']}", flush=True)
                return 0
            print(f"DRIVER TASK CARRIER pid={os.getpid()} task={carrier_task_name(ep)}", flush=True)
            return serve(ep, codex=codex, interval=interval, resume=resume)


def _finish(ep: Path, rc: int) -> None:
    """Record the exit code and give up the pid in one write.

    Clearing the pid is what makes "is the Driver still running" answerable: a
    recorded pid plus a recorded exit code used to be readable as both, and the
    ~2 s of interpreter teardown in between reported as a live process holding a
    finished exit code.
    """
    _write_record(ep, {"rc": f"{int(rc)} {now()}", "pid": 0, "exited_at": now()})
    # Stop claiming the pid in the beacon too: otherwise a process that inherited
    # that pid within the tolerance window would read as a live Driver.
    try:
        write_beacon(ep, 0)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Story OS detached resident Driver")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start"); p.add_argument("episode_dir")
    p.add_argument("--codex"); p.add_argument("--interval", type=int, default=10)
    p.add_argument("--resume", action="store_true"); p.add_argument("--json", action="store_true")

    p = sub.add_parser("status"); p.add_argument("episode_dir"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("recover"); p.add_argument("episode_dir"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("logs"); p.add_argument("episode_dir"); p.add_argument("--lines", type=int, default=20)

    p = sub.add_parser("_serve"); p.add_argument("episode_dir")
    p.add_argument("--codex"); p.add_argument("--interval", type=int, default=10)
    p.add_argument("--resume", action="store_true")
    _add_storage_mode_arguments(p)
    p.add_argument("--production-mode", choices=("CODEX_MANAGED",))
    p.add_argument("--image-executor", choices=("CODEX",))

    p = sub.add_parser("_serve_task"); p.add_argument("episode_dir")
    p.add_argument("--codex"); p.add_argument("--interval", type=int, default=10)
    p.add_argument("--resume", action="store_true"); p.add_argument("--log", required=True)
    _add_storage_mode_arguments(p)
    p.add_argument("--production-mode", choices=("CODEX_MANAGED",))
    p.add_argument("--image-executor", choices=("CODEX",))

    args = ap.parse_args(argv)

    if args.cmd == "_serve":
        _load_child_runtime_environment(
            runtime_store_mode=args.runtime_store_mode,
            episode_meta_store_mode=args.episode_meta_store_mode,
            hot_state_mode=args.hot_state_mode,
            production_mode=args.production_mode, image_executor=args.image_executor,
        )
        return serve(Path(args.episode_dir), codex=args.codex, interval=args.interval, resume=args.resume)

    if args.cmd == "_serve_task":
        # Task Scheduler otherwise discards Python bootstrap exceptions before
        # serve_task() has redirected stdout/stderr to the durable Driver log.
        try:
            _load_child_runtime_environment(
                runtime_store_mode=args.runtime_store_mode,
                episode_meta_store_mode=args.episode_meta_store_mode,
                hot_state_mode=args.hot_state_mode,
                production_mode=args.production_mode, image_executor=args.image_executor,
            )
        except Exception:
            import traceback
            log_path = Path(args.log).resolve()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8", errors="replace", buffering=1) as handle:
                print("DRIVER TASK BOOTSTRAP FAILED", file=handle)
                traceback.print_exc(file=handle)
            return 1
        return serve_task(Path(args.episode_dir), Path(args.log), codex=args.codex,
                          interval=args.interval, resume=args.resume)
    if args.cmd == "start":
        result = launch(Path(args.episode_dir), codex=args.codex, interval=args.interval, resume=args.resume)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else format_start(result))
        return 0 if result.get("started") else 3
    if args.cmd == "status":
        data = status(Path(args.episode_dir))
        print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else format_status(data))
        return 0
    if args.cmd == "recover":
        data = recover(Path(args.episode_dir))
        print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else format_status(data))
        return 0
    if args.cmd == "logs":
        for line in log_tail(Path(args.episode_dir), args.lines):
            print(line)
        return 0
    return 2


def format_status(data: dict) -> str:
    rows = [
        f"DRIVER {data.get('driver_state')} pid={data.get('pid')} liveness={data.get('liveness')}",
        f"STARTED {data.get('started_at') or '-'}",
    ]
    if data.get("exit_code"):
        rows.append(f"EXIT rc={data['exit_code']} {data.get('exit_note') or ''}".rstrip())
    else:
        rows.append("EXIT 未记录（进程没有机会写退出码：被强杀，或仍在运行）")
    if data.get("beacon_at"):
        age = data.get("beacon_age_seconds")
        rows.append(f"BEACON {data['beacon_at']}" + (f" age={age}s" if age is not None else ""))
    if data.get("heartbeat_status"):
        rows.append(f"HEARTBEAT {data['heartbeat_status']} at {data.get('heartbeat_at')}")
    if data.get("carrier"):
        rows.append(f"CARRIER {data['carrier']} task={data.get('carrier_task') or '-'}")
    rows.append(f"LOG {data.get('log') or '（无）'} bytes={data.get('log_bytes')}")
    if data.get("recovery"):
        rows.append(f"RECOVERY {data['recovery']}")
    if data.get("note"):
        rows.append(f"NOTE {data['note']}")
    return "\n".join(rows)


def format_start(result: dict) -> str:
    if result.get("started") and result.get("exit_code"):
        return "\n".join([
            f"DETACHED pid={result['pid']}",
            f"LOG {result['log']}",
            f"EXIT rc={result['exit_code']} {result.get('exit_note') or ''}".rstrip(),
            "OK 启动成功，但它在启动窗口内就结束了——引擎停下等宿主动作，或这条 Episode 已经到了终点。",
            "看 `driver logs` 确认它最后说了什么；要续跑就再 `driver start`。",
        ])
    if result.get("started"):
        return "\n".join([
            f"DETACHED pid={result['pid']}",
            f"LOG {result['log']}",
            "OK 本进程退出不影响它。之后用 `driver status` / `driver logs` 轮询，不要前台重跑。",
        ])
    return "\n".join([
        f"NOT STARTED reason={result.get('reason')} pid={result.get('pid')}",
        f"LOG {result.get('log') or '（无）'}",
        f"EXIT rc={result.get('exit_code')} {result.get('exit_note') or ''}".rstrip(),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
