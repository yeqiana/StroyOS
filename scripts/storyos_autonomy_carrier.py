#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Explicit Windows user-logon carrier for existing StoryOS autonomy Watchdog.

PLAN is entirely pure. Installing/uninstalling is NEVER implicit in production
and requires both a verified interactive principal and an explicit acknowledgement.
The carrier starts only the watchdog; the watchdog rechecks canonical MySQL/Attempt
gates and is not authorized to start a new Episode.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import storyos_codex_managed as native

ROOT=Path(__file__).resolve().parents[1]
WATCHDOG=ROOT/"scripts/storyos_autonomy_watchdog.py"


def _ps(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _validate_identity(identity: str) -> str:
    user=str(identity or "").strip()
    last=user.rsplit("\\",1)[-1].casefold()
    if (not user or last in {"system","localsystem","local service","network service"}
            or "nt authority" in user.casefold() or "system" == user.casefold()):
        raise ValueError("INTERACTIVE_USER_REQUIRED")
    return user


def build_plan(episode: Path, *, identity: str, interval_seconds: int = 300) -> dict:
    """Pure plan. Does not check/modify OS scheduled tasks or generate credentials."""
    if not 60 <= interval_seconds <= 86400:
        raise ValueError("WATCHDOG_INTERVAL_INVALID")
    user=_validate_identity(identity)
    ep=Path(episode).resolve()
    marker=hashlib.sha256(str(ep).casefold().encode("utf-8")).hexdigest()[:20]
    argv=[str(WATCHDOG),"watch",str(ep),"--ack-real-production",
          "--interval-seconds",str(interval_seconds)]
    return {"status":"PLAN_ONLY","task_name":"StoryOSAutonomy-"+marker,
            "executable":sys.executable,"arguments":subprocess.list2cmdline(argv),
            "principal":user,"working_directory":str(ROOT),
            "interval_seconds":interval_seconds,"trigger":"AT_USER_LOGON",
            "startup":"WAIT_FOR_INTERACTIVE_LOGON",
            "model_calls":0,"sql_writes":0,"production_authorization":False}


def _powershell(script: str) -> tuple[int,str]:
    outcome=subprocess.run(["powershell","-NoProfile","-NonInteractive","-Command",script],
                           text=True,encoding="utf-8",errors="replace",
                           capture_output=True,timeout=35,check=False,cwd=ROOT)
    return outcome.returncode,outcome.stdout.strip()


def registered_task(task_name: str) -> dict | None:
    """Read-only Scheduler evidence. On errors treat as unknown, not absent."""
    if os.name!="nt":
        raise OSError("WINDOWS_REQUIRED")
    script=(
        "$ErrorActionPreference='Stop';"
        f"$task=Get-ScheduledTask -TaskName {_ps(task_name)} -ErrorAction SilentlyContinue;"
        "if($null -eq $task){'null'}else{"
        "[pscustomobject]@{principal=$task.Principal.UserId;"
        "executable=$task.Actions[0].Execute;arguments=$task.Actions[0].Arguments;"
        "task_name=$task.TaskName} | ConvertTo-Json -Compress}"
    )
    rc,out=_powershell(script)
    if rc:
        raise OSError("SCHEDULER_QUERY_FAILED")
    try:
        value=json.loads(out)
        if value is None:
            return None
        if isinstance(value,dict) and all(k in value for k in ("principal","executable","arguments")):
            return value
    except ValueError:
        pass
    raise OSError("SCHEDULER_EVIDENCE_INVALID")


def register_task(plan: dict) -> bool:
    """Windows user-logon carrier. No -Force; never overwrite a foreign task."""
    if os.name!="nt":
        return False
    script=(
        "$ErrorActionPreference='Stop';"
        f"$name={_ps(plan['task_name'])};"
        f"$user={_ps(plan['principal'])};"
        f"$act=New-ScheduledTaskAction -Execute {_ps(plan['executable'])} "
        f"-Argument {_ps(plan['arguments'])} -WorkingDirectory {_ps(plan['working_directory'])};"
        "$trigger=New-ScheduledTaskTrigger -AtLogOn -User $user;"
        "$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive "
        "-RunLevel Limited;"
        "$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable "
        "-MultipleInstances IgnoreNew -RestartCount 3 "
        "-RestartInterval (New-TimeSpan -Minutes 5) "
        "-ExecutionTimeLimit ([TimeSpan]::Zero);"
        "Register-ScheduledTask -TaskName $name -Action $act -Trigger $trigger "
        "-Principal $principal -Settings $settings -ErrorAction Stop | Out-Null;"
        "'REGISTERED'"
    )
    rc,out=_powershell(script)
    return rc==0 and out=="REGISTERED"


def _task_matches(plan: dict, record: dict) -> bool:
    return (record.get("principal","").casefold()==plan["principal"].casefold()
            and Path(record.get("executable","")).resolve()==Path(plan["executable"]).resolve()
            and record.get("arguments")==plan["arguments"])


def _primary_checkout() -> bool:
    """Never install a long-lived task pointing at a disposable Git worktree."""
    return (ROOT/".git").is_dir()


def install(episode: Path, *, acknowledged: bool, identity: str) -> dict:
    if not acknowledged:
        return {"status":"ACK_REQUIRED","changed":False}
    try:
        plan=build_plan(episode,identity=identity)
        existing=registered_task(plan["task_name"])
        if existing is not None:
            return {"status":"TASK_ALREADY_EXISTS","changed":False}
        if not _primary_checkout():
            return {"status":"PRIMARY_CHECKOUT_REQUIRED","changed":False}
        if not register_task(plan):
            return {"status":"SCHEDULER_REGISTRATION_UNVERIFIED","changed":False}
        return {"status":"REGISTERED","changed":True,"task_name":plan["task_name"]}
    except (ValueError,OSError,subprocess.TimeoutExpired):
        return {"status":"SCHEDULER_AUTHORITY_UNVERIFIED","changed":False}


def uninstall(episode: Path, *, acknowledged: bool, identity: str) -> dict:
    if not acknowledged:
        return {"status":"ACK_REQUIRED","changed":False}
    try:
        plan=build_plan(episode,identity=identity)
        current=registered_task(plan["task_name"])
        if current is None:
            return {"status":"NOT_INSTALLED","changed":False}
        if not _task_matches(plan,current):
            return {"status":"FOREIGN_TASK_REFUSED","changed":False}
        rc,out=_powershell("$ErrorActionPreference='Stop';"
                           f"Unregister-ScheduledTask -TaskName {_ps(plan['task_name'])} "
                           "-Confirm:$false -ErrorAction Stop;'REMOVED'")
        return {"status":"REMOVED" if rc==0 and out=="REMOVED" else "UNVERIFIED",
                "changed":rc==0 and out=="REMOVED"}
    except (ValueError,OSError,subprocess.TimeoutExpired):
        return {"status":"SCHEDULER_AUTHORITY_UNVERIFIED","changed":False}


def verified_interactive_identity() -> str:
    """Reuse Driver's tested interactive-user proof, never guess an account."""
    system=native.SYSTEM
    if str(system) not in sys.path:
        sys.path.insert(0,str(system))
    import runtime_driver
    user,_source=runtime_driver.resolve_task_carrier_user()
    return _validate_identity(user)


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("plan","status","install","uninstall"))
    parser.add_argument("episode")
    parser.add_argument("--ack-real-production",action="store_true")
    args=parser.parse_args(argv)
    if args.command in {"install","uninstall"} and not args.ack_real_production:
        print(json.dumps({"status":"ACK_REQUIRED","changed":False}))
        return 2
    try:
        ep=native.canonical_episode(args.episode)
        user=verified_interactive_identity()
        plan=build_plan(ep,identity=user)
        if args.command=="plan":
            result=plan
        elif args.command=="status":
            current=registered_task(plan["task_name"])
            result={"status":"NOT_INSTALLED" if current is None else
                    ("INSTALLED" if _task_matches(plan,current) else "FOREIGN_TASK"),
                    "changed":False,"task_name":plan["task_name"]}
        elif args.command=="install":
            result=install(ep,acknowledged=True,identity=user)
        else:
            result=uninstall(ep,acknowledged=True,identity=user)
    except (ValueError,OSError,subprocess.TimeoutExpired):
        result={"status":"SCHEDULER_AUTHORITY_UNVERIFIED","changed":False}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result["status"] in {"PLAN_ONLY","NOT_INSTALLED","INSTALLED",
        "REGISTERED","REMOVED"} else 3


if __name__=="__main__":
    raise SystemExit(main())
