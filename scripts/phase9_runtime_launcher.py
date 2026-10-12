"""Phase9 常驻 Runtime 编排入口（P9.34）。

P9.28-P9.33 交付了常驻 Worker、Metrics 端点、告警通道与存活观察者，但这些命令需要
分别拉起。本文件提供一个单一编排入口，把「常驻 Worker + Metrics 端点」作为一个可部署
单元统一启动、统一优雅退出。它是系统服务 / 计划任务部署（阻塞项 #1）的直接前置。

编排内容（常驻，持续运行）：
    - metrics exporter：把 Worker 的 Prometheus textfile 暴露在 /metrics
    - worker：心跳 / 探针 / 巡检 / 健康 / 告警 / 指标

明确不做的事：
    - 不自己注册系统服务 / 计划任务（部署需单独授权）。
    - 不自动重启失联 Worker（自愈由后续 policy 决策，需单独授权）。
    - 不把 Watchdog 当作常驻子进程：Watchdog 是「跑 N 轮」的一次性巡检命令，应由
      计划任务 / 系统调度器周期性拉起，不在本编排内常驻。
    - 不写凭据；证据只记 host / port / database 与布尔。

退出码：
    0 = 收到停止信号或达到 max-seconds 后优雅退出
    4 = 有子进程提前退出（fail-fast，不自动重启）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKER_SCRIPT = PROJECT_ROOT / "scripts" / "phase9_runtime_worker.py"
EXPORTER_SCRIPT = PROJECT_ROOT / "scripts" / "phase9_metrics_exporter.py"

EXIT_OK = 0
EXIT_CHILD_FAILED = 4
RUNTIME_ENV_KEYS = {
    "STORYOS_MYSQL_HOST",
    "STORYOS_MYSQL_PORT",
    "STORYOS_MYSQL_USER",
    "STORYOS_MYSQL_PWD",
    "STORYOS_MYSQL_DB",
    "STORYOS_REDIS_HOST",
    "STORYOS_REDIS_PORT",
    "STORYOS_REDIS_DB",
    "STORYOS_REDIS_PASSWORD",
    "STORYOS_EPISODE_META_STORE_MODE",
    "STORYOS_HOT_STATE_MODE",
    "STORYOS_RUNTIME_STORE_MODE",
    "STORYOS_RUNTIME_JSONL_ROOT",
}


def load_runtime_env_file(path: Path, env: dict[str, str]) -> tuple[dict[str, str], tuple[str, ...]]:
    """Load local runtime connection settings without exposing values in evidence.

    The default location lives under ``.storyos/runtime-launcher`` which is
    git-ignored. Only the explicit allowlist above is accepted. Explicit process
    environment values win over the file, matching normal .env override semantics
    and allowing tests/services to select hermetic storage without file mutation.
    """
    if not path.is_file():
        return env, ()
    loaded: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid runtime env line: {raw!r}")
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in RUNTIME_ENV_KEYS:
            raise ValueError(f"unsupported runtime env key: {key}")
        if key in env:
            continue
        env[key] = value.strip()
        loaded.append(key)
    return env, tuple(sorted(set(loaded)))


@dataclass
class ChildSpec:
    name: str
    cmd: list[str]


def build_children(
    *,
    run_root,
    worker_id,
    interval,
    consistency_every,
    stuck_minutes,
    jsonl_root,
    tick_log_max_mib=64,
    alert_webhook=None,
    alert_webhook_format="json",
    metrics_host="127.0.0.1",
    metrics_port=18081,
    auto_recover=False,
    restart_agent_command=None,
) -> list[ChildSpec]:
    """构造 Worker 与 Metrics 端点的子进程命令；两者共享同一个 metrics 文件。"""
    run_root = Path(run_root)
    metrics_file = run_root / "worker-metrics.prom"
    alert_log = run_root / "worker-alerts.jsonl"
    tick_log = run_root / "worker-ticks.jsonl"
    worker_evidence = run_root / "worker-evidence.json"

    worker_cmd = [
        sys.executable, str(WORKER_SCRIPT),
        "--worker-id", worker_id,
        "--interval", str(interval),
        "--consistency-every", str(consistency_every),
        "--stuck-minutes", str(stuck_minutes),
        "--jsonl-root", str(jsonl_root),
        "--metrics-file", str(metrics_file),
        "--alert-log", str(alert_log),
        "--tick-log", str(tick_log),
        "--tick-log-max-mib", str(tick_log_max_mib),
        "--evidence-file", str(worker_evidence),
    ]
    if alert_webhook:
        worker_cmd += [
            "--alert-webhook", alert_webhook,
            "--alert-webhook-format", alert_webhook_format,
        ]
    if auto_recover:
        worker_cmd += ["--auto-recover"]
    if restart_agent_command:
        worker_cmd += ["--restart-agent-command", restart_agent_command]

    exporter_cmd = [
        sys.executable, str(EXPORTER_SCRIPT),
        "--metrics-file", str(metrics_file),
        "--host", metrics_host,
        "--port", str(metrics_port),
    ]

    return [
        ChildSpec("worker", worker_cmd),
        ChildSpec("metrics-exporter", exporter_cmd),
    ]


class RuntimeLauncher:
    """启动、等待、统一优雅退出多个 sidecar；fail-fast，不自动重启。"""

    def __init__(self, *, spawn=None, clock=time.monotonic, sleep=time.sleep):
        self._spawn_fn = spawn
        self._clock = clock
        self._sleep = sleep
        self._procs: dict[str, subprocess.Popen] = {}

    def start(self, children, env) -> dict:
        started: dict[str, int | None] = {}
        for spec in children:
            if self._spawn_fn is not None:
                proc = self._spawn_fn(spec=spec, env=env)
            else:
                proc = subprocess.Popen(
                    spec.cmd,
                    cwd=str(PROJECT_ROOT),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            self._procs[spec.name] = proc
            started[spec.name] = getattr(proc, "pid", None)
        return started

    def _first_exited(self) -> str | None:
        for name, proc in self._procs.items():
            if proc is not None and proc.poll() is not None:
                return name
        return None

    def stop(self, timeout: float = 10.0) -> dict:
        for proc in self._procs.values():
            if proc is None:
                continue
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        deadline = self._clock() + timeout
        outcomes: dict[str, dict] = {}
        for name, proc in list(self._procs.items()):
            if proc is None:
                continue
            remaining = max(0.0, deadline - self._clock())
            try:
                code = proc.wait(timeout=remaining)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                    code = proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    code = None
            outcomes[name] = {"pid": getattr(proc, "pid", None), "exit_code": code}
        self._procs = {}
        return outcomes

    def run(self, children, env, *, max_seconds=None) -> dict:
        started = self.start(children, env)
        begun = self._clock()
        exited_early = None
        try:
            while max_seconds is None or self._clock() - begun < max_seconds:
                exited_early = self._first_exited()
                if exited_early is not None:
                    break
                self._sleep(0.2)
        except KeyboardInterrupt:
            pass
        stopped = self.stop()
        return {
            "started": started,
            "exited_early": exited_early,
            "children": stopped,
        }


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="Story OS V3 Phase9 常驻 Runtime 编排入口")
    parser.add_argument("--worker-id", default="runtime-worker")
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--consistency-every", type=int, default=10)
    parser.add_argument("--stuck-minutes", type=float, default=30.0)
    parser.add_argument("--jsonl-root", default=".storyos")
    parser.add_argument("--tick-log-max-mib", type=float, default=64,
                        help="Tick JSONL 无损轮转阈值 MiB；0=禁用")
    parser.add_argument("--run-root", default=str(PROJECT_ROOT / ".storyos" / "runtime-launcher"))
    parser.add_argument("--alert-webhook", default=None)
    parser.add_argument("--alert-webhook-format", default="json", choices=("json", "dingtalk"))
    parser.add_argument("--auto-recover", action="store_true")
    parser.add_argument("--restart-agent-command", default=None)
    parser.add_argument("--metrics-port", type=int, default=18081)
    parser.add_argument(
        "--runtime-env-file",
        default=None,
        help="本地运行环境文件；默认 <run-root>/runtime.env（目录已 git-ignore）",
    )
    parser.add_argument(
        "--evidence-file",
        default=str(PROJECT_ROOT / ".storyos" / "runtime-launcher" / "launcher-evidence.json"),
    )
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    run_root = Path(args.run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    children = build_children(
        run_root=run_root,
        worker_id=args.worker_id,
        interval=args.interval,
        consistency_every=args.consistency_every,
        stuck_minutes=args.stuck_minutes,
        jsonl_root=args.jsonl_root,
        tick_log_max_mib=args.tick_log_max_mib,
        alert_webhook=args.alert_webhook,
        alert_webhook_format=args.alert_webhook_format,
        metrics_port=args.metrics_port,
        auto_recover=args.auto_recover,
        restart_agent_command=args.restart_agent_command,
    )
    env = dict(os.environ)
    runtime_env_path = Path(args.runtime_env_file) if args.runtime_env_file else run_root / "runtime.env"
    env, loaded_env_keys = load_runtime_env_file(runtime_env_path, env)
    launcher = RuntimeLauncher()
    if not args.quiet:
        print("Story OS V3 Phase9 常驻 Runtime 编排入口")
        print("  worker_id=" + args.worker_id + " metrics_port=" + str(args.metrics_port))
        print("  children=" + ",".join(c.name for c in children))

    result = launcher.run(children, env, max_seconds=args.max_seconds)

    evidence_path = Path(args.evidence_file)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": result,
        "config": {
            "worker_id": args.worker_id,
            "interval": args.interval,
            "consistency_every": args.consistency_every,
            "stuck_minutes": args.stuck_minutes,
            "jsonl_root": args.jsonl_root,
            "tick_log_max_mib": args.tick_log_max_mib,
            "metrics_port": args.metrics_port,
            "alert_webhook_configured": bool(args.alert_webhook),
            "runtime_env_file": str(runtime_env_path) if runtime_env_path.is_file() else None,
            "runtime_env_keys": list(loaded_env_keys),
        },
    }
    tmp = evidence_path.with_name(evidence_path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, evidence_path)

    if not args.quiet:
        print("  exited_early=" + str(result["exited_early"]))
        print("  children=" + json.dumps(result["children"], ensure_ascii=False))
        print("  evidence=" + str(evidence_path))
    return EXIT_CHILD_FAILED if result["exited_early"] is not None else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
