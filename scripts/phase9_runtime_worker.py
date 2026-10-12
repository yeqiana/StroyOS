"""Story OS V3 Phase9 常驻 Runtime Worker 载体（P9.28）。

阶段定位：
    P9.27 之前，Runtime Operations 的能力（Heartbeat / Health / Alert / 一致性巡检）
    只能在测试、冒烟脚本或人工命令里跑一次；Phase9 Production Readiness Gate 的
    阻塞项 1 就是「缺常驻 Runtime Worker 载体」。本文件补上载体本身。

每个 tick 的链路：

    WorkerHeartbeat(Redis, TTL)
        |
    依赖探针（Redis ping / MySQL 连通与三表计数）
        |
    每 N 个 tick：Legacy(JSONL) vs MySQL 一致性巡检（复用 P9.26.6 巡检器）
        |
    RuntimeHealthMonitor -> RuntimeAlertManager -> Incident 生命周期
        |
    指标（Prometheus textfile 原子落盘） + 告警 JSONL + tick JSONL

明确不做的事：
    - 不注册系统服务 / 计划任务。部署（Windows 服务、Task Scheduler、容器）需要单独
      授权；本文件只提供可被这些载体拉起的常驻命令，不自己装自己。
    - 不写业务数据、不推进 episode stage、不改 release 资产；默认不做自动修复。
      RuntimeRecoverySelfHealing + RecoveryExecutor 已通过 --auto-recover 接入本载体，
      但默认关闭（auto_recover=False）；只有显式开启并配置 --restart-agent-command
      才会对 CRITICAL 事件自动执行恢复决策。
    - 不假设已部署 Prometheus / Grafana / 告警后端：本载体只做产出侧，格式对齐
      node_exporter textfile collector 与 JSONL，后端接入属于下一步。
    - 不在证据里写凭据：只记录 host / port / database 与「是否提供了密码」。

健康口径（代理说明）：
    平台当前没有独立 memory 子系统，RuntimeHealthSnapshot 要求的 memory_health
    用 Redis 状态层可达性作代理；tick 证据用 health_mapping 字段显式标注。
    若 Redis 未探测（--no-redis），不猜健康值，直接记 UNKNOWN 并留下原因。

用法（凭据只放环境变量，不写进仓库任何文件）：

    $env:STORYOS_REDIS_HOST="127.0.0.1"; $env:STORYOS_REDIS_PORT="6379"
    $env:STORYOS_MYSQL_HOST="..."; $env:STORYOS_MYSQL_PORT="..."
    $env:STORYOS_MYSQL_USER="..."; $env:STORYOS_MYSQL_PWD="..."
    $env:STORYOS_MYSQL_DB="story_os_runtime"
    python scripts/phase9_runtime_worker.py --once
    python scripts/phase9_runtime_worker.py --interval 30 --consistency-every 10

退出码：
    0 = 正常结束且没有未消解的告警
    2 = 结束时仍有未消解的 WARNING / CRITICAL 告警
    3 = 启动环境错误（参数非法 / Redis 或 MySQL 客户端不可用）
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_JSONL_ROOT = ".storyos"
DEFAULT_RUNTIME = "V3_RUNTIME"
DEFAULT_INTERVAL_SECONDS = 30.0
DEFAULT_CONSISTENCY_EVERY = 10
DEFAULT_STUCK_MINUTES = 30.0
DEFAULT_HEALTH_WINDOW_MINUTES = 60.0
HEARTBEAT_TTL_FACTOR = 3
SLEEP_CHUNK_SECONDS = 0.25
ALERT_COMMAND_TIMEOUT_SECONDS = 15

EXIT_OK = 0
EXIT_ALERTING = 2
EXIT_ENV_ERROR = 3

ALERT_LEVELS = ("INFO", "WARNING", "CRITICAL")
ALERTING_LEVELS = ("WARNING", "CRITICAL")

# 探针只读的表；名字来自 platform/repository/mysql/schema.py 的 DDL。
# 对外指标保留逻辑实体名；实际探针使用 V2 schema 的 TB_* 表名。
PROBE_TABLES = (
    ("event_log", "TB_EVENT_LOG"),
    ("trace_span", "TB_TRACE_SPAN"),
    ("artifact_index", "TB_ARTIFACT_INDEX"),
)
ENTITY_CHOICES = ("event", "trace", "artifact")


def _default_output(name: str) -> Path:
    return PROJECT_ROOT / ".storyos" / "runtime" / name


DEFAULT_METRICS_FILE = _default_output("worker-metrics.prom")
DEFAULT_ALERT_LOG = _default_output("worker-alerts.jsonl")
DEFAULT_TICK_LOG = _default_output("worker-ticks.jsonl")
DEFAULT_EVIDENCE_FILE = _default_output("worker-run-evidence.json")


def _bootstrap_story_platform() -> None:
    """把 import platform 指向仓库内 platform 包，而不是 stdlib platform。"""
    target = (PROJECT_ROOT / "platform" / "__init__.py").resolve()
    existing = sys.modules.get("platform")
    existing_file = getattr(existing, "__file__", None)
    if existing_file:
        try:
            if Path(existing_file).resolve() == target:
                return
        except OSError:
            pass

    root = str(PROJECT_ROOT)
    while root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)

    spec = importlib.util.spec_from_file_location(
        "platform",
        target,
        submodule_search_locations=[str(target.parent)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Story OS platform package from {target}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["platform"] = module
    spec.loader.exec_module(module)


_bootstrap_story_platform()

# 连接配置唯一解析入口（应用层读 config/storyos.yaml#storage，platform/ 保持零 yaml 依赖）。
if str(PROJECT_ROOT / "episodes" / "_system") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "episodes" / "_system"))
import storage_config  # noqa: E402

from scripts.storyos_runtime_tick_rotation import maybe_rotate_tick_log  # noqa: E402
from platform.artifact.jsonl_artifact_store import JsonlArtifactStore  # noqa: E402
from platform.core.clock import utc_now  # noqa: E402
from platform.event.jsonl_event_store import JsonlEventStore  # noqa: E402
from platform.operations.runtime_alert_incident_management import (  # noqa: E402
    RuntimeAlert,
    RuntimeAlertManager,
)
from platform.operations.runtime_auto_recovery import (  # noqa: E402
    AutoRecoveryEvent,
    orchestrate,
)
from platform.operations.runtime_health_monitoring import RuntimeHealthMonitor  # noqa: E402
from platform.operations.runtime_alert_channel import build_webhook_channel  # noqa: E402
from platform.repository.artifact.mysql_artifact_repository import (  # noqa: E402
    MySqlArtifactRepository,
)
from platform.repository.consistency import (  # noqa: E402
    RuntimeConsistencyChecker,
    RuntimeConsistencyScan,
    ScanPolicy,
)
from platform.repository.mysql.mysql_connection import MySqlConnection  # noqa: E402
from platform.repository.mysql.mysql_event_repository import (  # noqa: E402
    MySqlEventRepository,
)
from platform.repository.trace.mysql_trace_repository import (  # noqa: E402
    MySqlTraceRepository,
)
from platform.state.worker_heartbeat import WorkerHeartbeat  # noqa: E402
from platform.trace.jsonl_trace_store import JsonlTraceStore  # noqa: E402
from platform.repository.trace.mysql_trace_repository import MySqlTraceRepository  # noqa: E402

HAS_MYSQL_DRIVER: bool
try:
    import pymysql  # noqa: F401

    HAS_MYSQL_DRIVER = True
except ImportError:  # pragma: no cover - 环境缺失时才走
    HAS_MYSQL_DRIVER = False


def _num(value) -> str:
    """Prometheus 数值格式：布尔转 1/0，float 去掉多余精度。"""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return format(value, ".6g")
    return str(value)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _parse_iso(value):
    if isinstance(value, datetime):
        raw = value.replace(tzinfo=None)
        return raw
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip()).replace(tzinfo=None)
    except ValueError:
        return None


def scope_health_trace_records(
    trace_records,
    *,
    now: datetime,
    window_seconds: float,
    instance_started_at: datetime | None,
) -> tuple[list[dict], dict]:
    """Scope terminal health samples to this worker instance and a sliding window.

    SUCCESS/FAILED spans are score inputs only when their terminal timestamp
    (ended_at, falling back to started_at) is at or after both the current
    worker-instance start and the rolling health window. RUNNING spans remain
    visible regardless of age so a worker restart cannot hide a genuinely
    stuck execution.
    """
    now_value = _parse_iso(now)
    if now_value is None:
        raise ValueError("health scope requires a parseable now")
    window_seconds = float(window_seconds)
    if window_seconds <= 0:
        raise ValueError("health window must be positive")

    instance_start = _parse_iso(instance_started_at)
    window_start = now_value - timedelta(seconds=window_seconds)
    effective_start = max(window_start, instance_start) if instance_start else window_start

    source = list(trace_records or ())
    scoped: list[dict] = []
    excluded_terminal = 0
    unparseable_terminal = 0
    carried_running = 0
    ignored_status = 0

    for record in source:
        status = str(record.get("status") or "").strip().upper()
        if status == "RUNNING":
            scoped.append(record)
            started_at = _parse_iso(record.get("started_at"))
            if started_at is not None and started_at < effective_start:
                carried_running += 1
            continue
        if status not in {"SUCCESS", "FAILED"}:
            ignored_status += 1
            continue

        observed_at = _parse_iso(record.get("ended_at")) or _parse_iso(record.get("started_at"))
        if observed_at is None or observed_at < effective_start:
            excluded_terminal += 1
            if observed_at is None:
                unparseable_terminal += 1
            continue
        scoped.append(record)

    return scoped, {
        "policy": "terminal_after_instance_and_window;running_always_visible",
        "instance_started_at": _iso(instance_start),
        "window_seconds": window_seconds,
        "window_started_at": _iso(window_start),
        "effective_started_at": _iso(effective_start),
        "source_records": len(source),
        "scoped_records": len(scoped),
        "excluded_terminal": excluded_terminal,
        "unparseable_terminal": unparseable_terminal,
        "carried_running": carried_running,
        "ignored_status": ignored_status,
    }


def is_stuck(record: dict, *, now: datetime, stuck_seconds: float) -> bool:
    """RUNNING 且已超过阈值仍未结束 = 卡住（阈值内算正常在途）。"""
    started_at = _parse_iso(record.get("started_at"))
    now_value = _parse_iso(now)
    if started_at is None or now_value is None:
        return False
    return (now_value - started_at).total_seconds() > stuck_seconds


def derive_health_inputs(
    trace_records,
    *,
    memory_health: bool,
    now: datetime,
    stuck_seconds: float,
) -> dict:
    """从真实 Trace 事实推导 RuntimeHealthMonitor 需要的输入。

    真实口径：
        agent_success_rate / workflow_success_rate
            按 operation 前缀分组（agent.* / workflow.*），只统计已终结的 span
            （SUCCESS / FAILED）。该组没有任何终结 span 时取 1.0，并把
            terminal=0 如实记进 counts，避免把「没数据」伪装成「执行成功」。
        trace_health
            没有超过 stuck_seconds 的 RUNNING span 即为健康。
        memory_health
            由调用方传入（Redis 状态层可达性代理）。
    """
    counts = {"total": 0, "success": 0, "failed": 0, "running": 0, "stuck": 0}
    groups: dict[str, dict[str, int]] = {}

    for record in trace_records or ():
        status = str(record.get("status") or "").strip().upper()
        operation = str(record.get("operation") or "").strip()
        group = operation.split(".")[0].lower() or "unknown"
        bucket = groups.setdefault(group, {"success": 0, "terminal": 0})
        counts["total"] += 1

        if status == "SUCCESS":
            counts["success"] += 1
            bucket["success"] += 1
            bucket["terminal"] += 1
        elif status == "FAILED":
            counts["failed"] += 1
            bucket["terminal"] += 1
        elif status == "RUNNING":
            counts["running"] += 1
            if is_stuck(record, now=now, stuck_seconds=stuck_seconds):
                counts["stuck"] += 1

    def rate(group: str) -> float:
        bucket = groups.get(group)
        if not bucket or not bucket["terminal"]:
            return 1.0
        return bucket["success"] / bucket["terminal"]

    return {
        "agent_success_rate": rate("agent"),
        "workflow_success_rate": rate("workflow"),
        "trace_health": counts["stuck"] == 0,
        "memory_health": bool(memory_health),
        "counts": counts,
        "groups": {key: dict(value) for key, value in sorted(groups.items())},
        "stuck_seconds": stuck_seconds,
    }


@dataclass(frozen=True)
class TickResult:
    """单个 tick 的执行事实；只记事实与结论，不记 Payload 明细。"""

    index: int
    started_at: str
    duration_ms: int
    heartbeat: dict
    probes: dict
    health: dict
    alerts: tuple
    open_incidents: tuple
    consistency: dict
    metrics: dict
    errors: tuple
    auto_recovery: tuple = ()


def run_alert_command(command: str, payload: dict) -> dict:
    """把告警 JSON 通过 stdin 交给外部命令（真实告警通道挂载点）。

    只有 CRITICAL 才会调用；命令由操作者显式提供，默认不配置就等于没有通道。
    """
    try:
        completed = subprocess.run(
            command,
            shell=True,
            input=json.dumps(payload, ensure_ascii=False, default=str),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=ALERT_COMMAND_TIMEOUT_SECONDS,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stderr_tail": (completed.stderr or "").strip()[-200:] or None,
        }
    except Exception as exc:  # noqa: BLE001 - 通道失败不能拖垮 Worker
        return {"command": command, "returncode": None, "error": f"{type(exc).__name__}: {exc}"}


def _component_for_alert(alert: dict) -> str:
    """从告警事实推导恢复决策层的 component。

    health_model 的告警 reason 被聚合成了 runtime_unhealthy / runtime_degraded，
    丢失了「是 agent 还是 workflow 失败」的粒度；这里回看 detail.reasons 原始
    信号，把 agent 失败映射为 AGENT_RUNTIME、workflow 失败映射为 WORKFLOW，
    其余（心跳 / 依赖探针）保守映射为 RUNTIME（默认无回退动作）。
    """
    if alert.get("source") == "health_model":
        reasons = (alert.get("detail") or {}).get("reasons") or []
        if any(reason in ("agent_success_rate_low", "agent_runtime_failure") for reason in reasons):
            return "AGENT_RUNTIME"
        if any(reason in ("workflow_success_rate_low", "workflow_failure") for reason in reasons):
            return "WORKFLOW"
    return "RUNTIME"


def _label(value) -> str:
    """Prometheus label 值转义；worker_id 来自命令行，必须净化。"""
    return str(value).replace("\\", "\\\\").replace(chr(34), "").replace("\n", " ")


def render_metrics(result: TickResult, **context) -> str:
    """把单个 tick 的结论渲染成 Prometheus textfile 格式。"""
    worker_id = _label(context.get("worker_id", ""))
    runtime = _label(context.get("runtime", DEFAULT_RUNTIME))
    ticks_total = context.get("ticks_total", 1)
    alerts_total = context.get("alerts_total", 0)
    scans_total = context.get("scans_total", 0)
    open_incidents = context.get("open_incidents", 0)
    epoch = context.get("epoch")

    worker_labels = "worker_id=" + chr(34) + worker_id + chr(34)
    runtime_labels = "runtime=" + chr(34) + runtime + chr(34)
    probes = result.probes or {}
    health = result.health or {}
    consistency = result.consistency or {}

    lines = [
        "# HELP storyos_runtime_worker_up 常驻 Worker 是否在本次 tick 正常运行",
        "# TYPE storyos_runtime_worker_up gauge",
        "storyos_runtime_worker_up{" + worker_labels + "} 1",
        "# HELP storyos_runtime_worker_ticks_total 本进程累计 tick 数",
        "# TYPE storyos_runtime_worker_ticks_total counter",
        "storyos_runtime_worker_ticks_total{" + worker_labels + "} " + _num(ticks_total),
        "# HELP storyos_runtime_worker_alerts_total 本进程累计 WARNING/CRITICAL 告警数",
        "# TYPE storyos_runtime_worker_alerts_total counter",
        "storyos_runtime_worker_alerts_total{" + worker_labels + "} " + _num(alerts_total),
        "# HELP storyos_runtime_worker_open_incidents 当前未消解的 CRITICAL 事件数",
        "# TYPE storyos_runtime_worker_open_incidents gauge",
        "storyos_runtime_worker_open_incidents{" + worker_labels + "} " + _num(open_incidents),
        "# HELP storyos_runtime_worker_consistency_scans_total 本进程累计一致性巡次数",
        "# TYPE storyos_runtime_worker_consistency_scans_total counter",
        "storyos_runtime_worker_consistency_scans_total{" + worker_labels + "} " + _num(scans_total),
    ]

    if epoch is not None:
        lines += [
            "# HELP storyos_runtime_worker_last_tick_timestamp_seconds 最近一次 tick 的 Unix 时间戳（用于识别陈旧文件）",
            "# TYPE storyos_runtime_worker_last_tick_timestamp_seconds gauge",
            "storyos_runtime_worker_last_tick_timestamp_seconds{" + worker_labels + "} " + _num(epoch),
        ]

    heartbeat_ok = 1 if (result.heartbeat or {}).get("status") == "OK" else 0
    lines += [
        "# HELP storyos_runtime_worker_heartbeat_ok 本次 tick 心跳是否写入成功（0/1）",
        "# TYPE storyos_runtime_worker_heartbeat_ok gauge",
        "storyos_runtime_worker_heartbeat_ok{" + worker_labels + "} " + _num(heartbeat_ok),
    ]

    for dependency in ("redis", "mysql"):
        status = (probes.get(dependency) or {}).get("status")
        value = 1 if status == "OK" else 0
        lines += [
            "# HELP storyos_runtime_probe_ok 依赖探针是否成功（0/1；SKIPPED 记 0）",
            "# TYPE storyos_runtime_probe_ok gauge",
            "storyos_runtime_probe_ok{" + worker_labels + ",dependency=" + chr(34)
            + dependency + chr(34) + "} " + _num(value),
        ]

    for table, count in ((probes.get("mysql") or {}).get("rows") or {}).items():
        lines += [
            "# HELP storyos_runtime_store_rows MySQL 侧表行数",
            "# TYPE storyos_runtime_store_rows gauge",
            "storyos_runtime_store_rows{" + worker_labels + ",table=" + chr(34)
            + _label(table) + chr(34) + "} " + _num(count),
        ]

    if "health_score" in health:
        lines += [
            "# HELP storyos_runtime_health_score 运行健康分（0-100）",
            "# TYPE storyos_runtime_health_score gauge",
            "storyos_runtime_health_score{" + runtime_labels + "} " + _num(health["health_score"]),
        ]

    level = health.get("level")
    for candidate in ALERT_LEVELS:
        value = 1 if candidate == level else 0
        lines += [
            "# HELP storyos_runtime_alert_level 当前健康模型告警等级（one-hot）",
            "# TYPE storyos_runtime_alert_level gauge",
            "storyos_runtime_alert_level{" + runtime_labels + ",level=" + chr(34)
            + candidate + chr(34) + "} " + _num(value),
        ]

    inputs = health.get("inputs") or {}
    counts = inputs.get("counts") or {}
    for metric, key in (
        ("storyos_runtime_traces_total", "total"),
        ("storyos_runtime_traces_success_total", "success"),
        ("storyos_runtime_traces_failed_total", "failed"),
        ("storyos_runtime_traces_running", "running"),
        ("storyos_runtime_traces_stuck", "stuck"),
    ):
        lines += [
            "# HELP " + metric + " Trace 事实计数（最近一次成功推导的窗口）",
            "# TYPE " + metric + " gauge",
            metric + "{" + runtime_labels + "} " + _num(counts.get(key, 0)),
        ]

    for metric, key in (
        ("storyos_runtime_agent_success_rate", "agent_success_rate"),
        ("storyos_runtime_workflow_success_rate", "workflow_success_rate"),
    ):
        if key in inputs:
            lines += [
                "# HELP " + metric + " 按 operation 前缀分组的成功率（无终结 span 时记 1）",
                "# TYPE " + metric + " gauge",
                metric + "{" + runtime_labels + "} " + _num(inputs[key]),
            ]

    for entity, block in (consistency.get("counts") or {}).items():
        for verdict, count in (block or {}).items():
            lines += [
                "# HELP storyos_runtime_consistency_entities 最近一次一致性巡检的实体计数",
                "# TYPE storyos_runtime_consistency_entities gauge",
                "storyos_runtime_consistency_entities{entity=" + chr(34) + _label(entity)
                + chr(34) + ",verdict=" + chr(34) + _label(verdict) + chr(34) + "} "
                + _num(count),
            ]

    health_status = health.get("status")
    for candidate in ("HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"):
        lines += [
            "# HELP storyos_runtime_health_state 运行健康状态（one-hot；UNKNOWN=信号不足未评估）",
            "# TYPE storyos_runtime_health_state gauge",
            "storyos_runtime_health_state{" + runtime_labels + ",status=" + chr(34)
            + candidate + chr(34) + "} " + _num(1 if candidate == health_status else 0),
        ]

    seen: set[str] = set()
    deduped: list[str] = []
    for line in lines:
        if line.startswith("# HELP ") or line.startswith("# TYPE "):
            token = " ".join(line.split(" ", 3)[:3])
            if token in seen:
                continue
            seen.add(token)
        deduped.append(line)
    return "\n".join(deduped) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    """原子落盘：先写同目录临时文件再 replace，避免被采集器读到半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def summarize_consistency(scan_result: dict, entities) -> dict:
    """把巡检块收敛成实体级结论；判定口径与 P9.26.6 一致，且不带回全量记录。"""
    counts: dict[str, dict] = {}
    inconsistent: list[dict] = []
    for entity in entities:
        block = scan_result.get(entity) or {}
        block_counts = dict(block.get("counts") or {})
        counts[entity] = block_counts
        issues = []
        if block_counts.get("mismatch"):
            issues.append("mismatch")
        if block_counts.get("legacy_only"):
            issues.append("legacy_only")
        if block_counts.get("mysql_only"):
            issues.append("mysql_only")
        if block.get("duplicates"):
            issues.append("duplicates")
        if issues:
            inconsistent.append({"entity": entity, "issues": issues, "counts": block_counts})
    return {
        "consistent": not inconsistent,
        "inconsistent": inconsistent,
        "counts": counts,
        "scanned_at": utc_now().isoformat(),
        "policy": {"compensating_write": False},
    }


class RuntimeOperationsWorker:
    """常驻 Runtime Worker 载体。

    store / redis_client / connection 全部可注入，离线测试不碰真实依赖。
    进程不排程自己：常驻能力由外层载体（系统服务 / 计划任务 / 容器）提供。
    """

    HEALTH_MAPPING = "memory_health := redis 状态层可达性（平台当前无独立 memory 子系统）"

    def __init__(
        self,
        *,
        worker_id: str,
        runtime: str = DEFAULT_RUNTIME,
        store=None,
        redis_client=None,
        connection=None,
        trace_repository=None,
        runtime_store_mode=None,
        jsonl_root: str = DEFAULT_JSONL_ROOT,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        consistency_every: int = DEFAULT_CONSISTENCY_EVERY,
        consistency_entities=ENTITY_CHOICES,
        stuck_seconds: float = DEFAULT_STUCK_MINUTES * 60,
        health_window_seconds: float = DEFAULT_HEALTH_WINDOW_MINUTES * 60,
        instance_id: str | None = None,
        instance_started_at: datetime | None = None,
        metrics_file=None,
        alert_log=None,
        tick_log=None,
        tick_log_max_mib: float = 64,
        alert_command: str | None = None,
        alert_webhook: str | None = None,
        alert_webhook_format: str = "json",
        alert_channel=None,
        auto_recover: bool = False,
        restart_agent_command: str | None = None,
        sleeper=time.sleep,
        clock=utc_now,
        max_retained_ticks: int = 200,
    ) -> None:
        if not worker_id:
            raise ValueError("worker_id is required")
        if float(interval_seconds) <= 0:
            raise ValueError("interval_seconds must be positive")
        if float(health_window_seconds) <= 0:
            raise ValueError("health_window_seconds must be positive")

        self.worker_id = str(worker_id)
        self.runtime = str(runtime)
        self.store = store
        self.redis_client = redis_client
        self.connection = connection
        self.trace_repository = trace_repository
        self.runtime_store_mode = runtime_store_mode
        self.jsonl_root = str(jsonl_root)
        self.interval_seconds = float(interval_seconds)
        self.consistency_every = max(1, int(consistency_every))
        self.consistency_entities = tuple(consistency_entities)
        self.stuck_seconds = float(stuck_seconds)
        self.health_window_seconds = float(health_window_seconds)
        self.instance_started_at = _parse_iso(instance_started_at) or _parse_iso(clock())
        if self.instance_started_at is None:
            raise ValueError("instance_started_at must be parseable")
        self.instance_id = str(
            instance_id or f"{self.worker_id}@{self.instance_started_at.isoformat()}"
        )
        self.metrics_file = Path(metrics_file) if metrics_file else DEFAULT_METRICS_FILE
        self.alert_log = Path(alert_log) if alert_log else DEFAULT_ALERT_LOG
        self.tick_log = Path(tick_log) if tick_log else DEFAULT_TICK_LOG
        if float(tick_log_max_mib) < 0:
            raise ValueError("tick_log_max_mib must be non-negative")
        self.tick_log_max_bytes = int(float(tick_log_max_mib) * 1024 * 1024)
        self.alert_command = alert_command or None
        self.alert_webhook = alert_webhook or None
        self._alert_channel = (
            alert_channel
            if alert_channel is not None
            else build_webhook_channel(self.alert_webhook, format=alert_webhook_format)
        )
        self.auto_recover = bool(auto_recover)
        self.restart_agent_command = restart_agent_command or None
        self.max_retained_ticks = max(1, int(max_retained_ticks))

        self._sleep = sleeper
        self._clock = clock
        self._stop = False
        self._results: list[TickResult] = []
        self._open_incidents: dict[str, dict] = {}
        self._resolved_incidents: list[dict] = []
        self._started_at: datetime | None = None
        self._shutdown: dict = {}
        self._alerts_total = 0
        self._scans_total = 0
        self._auto_recovery_outcomes: list = []

        self.heartbeat = WorkerHeartbeat(store) if store is not None else None
        self.health_monitor = RuntimeHealthMonitor()
        self.alert_manager = RuntimeAlertManager()

    # ---- 对外控制 ----

    def request_stop(self) -> None:
        """信号处理与测试用：请求跑完当前 tick 后优雅退出。"""
        self._stop = True

    @property
    def stop_requested(self) -> bool:
        return self._stop

    def heartbeat_key(self) -> str:
        return WorkerHeartbeat.PREFIX + self.worker_id + ":heartbeat"

    def heartbeat_ttl_seconds(self) -> int:
        """TTL 取 3 倍间隔：进程被 kill -9 后，心跳最多过期 3 个周期。"""
        return max(1, int(round(self.interval_seconds * HEARTBEAT_TTL_FACTOR)))

    # ---- 单步动作 ----

    def _write_heartbeat(self) -> dict:
        ttl = self.heartbeat_ttl_seconds()
        if self.heartbeat is None:
            return {"status": "SKIPPED", "reason": "no_state_store", "ttl_seconds": ttl}
        try:
            self.heartbeat.heartbeat(self.worker_id, "ONLINE", ttl_seconds=ttl)
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "ttl_seconds": ttl,
            }
        return {
            "status": "OK",
            "ttl_seconds": ttl,
            "written_at": self._clock().isoformat(),
        }

    def _probe_redis(self) -> dict:
        if self.redis_client is None:
            return {"status": "SKIPPED", "reason": "no_redis_client"}
        try:
            alive = bool(self.redis_client.ping())
        except Exception as exc:  # noqa: BLE001
            return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
        if not alive:
            return {"status": "ERROR", "error": "ping_returned_false"}
        return {"status": "OK"}

    def _probe_mysql(self) -> dict:
        if self.connection is None:
            return {"status": "SKIPPED", "reason": "no_mysql_connection"}
        try:
            ping = self.connection.query_one("SELECT 1 AS ok")
            rows = {}
            for logical_name, table in PROBE_TABLES:
                row = self.connection.query_one("SELECT COUNT(*) AS c FROM " + table)
                rows[logical_name] = int((row or {}).get("c") or 0)
        except Exception as exc:  # noqa: BLE001
            return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
        return {"status": "OK", "ping": bool(ping and ping.get("ok") == 1), "rows": rows}

    def _trace_records(self) -> list:
        if self.trace_repository is not None:
            return self.trace_repository.list_all()
        store = JsonlTraceStore(str(Path(self.jsonl_root) / "traces.jsonl"))
        return store.read_all()

    def _build_health(self, probes: dict) -> dict:
        redis_status = (probes.get("redis") or {}).get("status")
        if redis_status != "OK":
            return {
                "status": "UNKNOWN",
                "reason": "memory_signal_unavailable",
                "health_mapping": self.HEALTH_MAPPING,
            }

        try:
            records = self._trace_records()
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "UNKNOWN",
                "reason": "trace_signal_unavailable",
                "error": f"{type(exc).__name__}: {exc}",
                "health_mapping": self.HEALTH_MAPPING,
            }

        now = self._clock()
        scoped_records, health_scope = scope_health_trace_records(
            records,
            now=now,
            window_seconds=self.health_window_seconds,
            instance_started_at=self.instance_started_at,
        )
        inputs = derive_health_inputs(
            scoped_records,
            memory_health=True,
            now=now,
            stuck_seconds=self.stuck_seconds,
        )
        inputs["scope"] = health_scope
        snapshot = self.health_monitor.evaluate(
            runtime=self.runtime,
            agent_success_rate=inputs["agent_success_rate"],
            workflow_success_rate=inputs["workflow_success_rate"],
            trace_health=inputs["trace_health"],
            memory_health=inputs["memory_health"],
        )
        alert = self.alert_manager.evaluate(snapshot)
        status = snapshot.status
        health_score = snapshot.health_score
        reasons = list(snapshot.reasons)
        mysql_status = (probes.get("mysql") or {}).get("status")
        if mysql_status == "ERROR":
            status = "UNHEALTHY"
            health_score = 0
            if "mysql_unreachable" not in reasons:
                reasons.append("mysql_unreachable")
        return {
            "status": status,
            "health_score": health_score,
            "reasons": reasons,
            "level": alert.level,
            "alert_reason": alert.reason,
            "inputs": inputs,
            "health_mapping": self.HEALTH_MAPPING,
            "instance_id": self.instance_id,
            "instance_started_at": _iso(self.instance_started_at),
        }

    def _run_consistency_scan(self):
        """返回 (summary, error)。无 MySQL 连接时返回 (None, reason)。"""
        if self.runtime_store_mode == "mysql":
            # MySQL 已是唯一事实源；把「MySQL 有、Legacy 没有」误报成
            # mysql_only 会把正常切换状态打成 WARNING。
            return None, None
        if self.connection is None:
            return None, "no_mysql_connection"
        root = Path(self.jsonl_root)
        try:
            checker = RuntimeConsistencyChecker(
                event_legacy=JsonlEventStore(str(root / "events.jsonl")),
                event_mysql=MySqlEventRepository(self.connection),
                trace_legacy=JsonlTraceStore(str(root / "traces.jsonl")),
                trace_mysql=MySqlTraceRepository(self.connection),
                artifact_legacy=JsonlArtifactStore(str(root / "artifacts.jsonl")),
                artifact_mysql=MySqlArtifactRepository(self.connection),
            )
            raw = RuntimeConsistencyScan(checker).run(ScanPolicy(compensating_write=False))
        except Exception as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"
        return summarize_consistency(raw, self.consistency_entities), None

    def _evaluate_alerts(self, *, heartbeat, probes, health, consistency) -> list[dict]:
        """把三类真实事实收敛成告警；Redis 故障只由健康模型报一次，避免重复告警。"""
        alerts: list[dict] = []

        if (heartbeat or {}).get("status") == "ERROR":
            alerts.append({
                "source": "heartbeat",
                "level": "CRITICAL",
                "reason": "heartbeat_write_failed",
                "detail": {"error": (heartbeat or {}).get("error")},
            })

        if health.get("level") in ALERTING_LEVELS:
            alerts.append({
                "source": "health_model",
                "level": health["level"],
                "reason": health.get("alert_reason"),
                "detail": {
                    "status": health.get("status"),
                    "health_score": health.get("health_score"),
                    "reasons": health.get("reasons"),
                    "health_mapping": health.get("health_mapping"),
                },
            })

        mysql_probe = probes.get("mysql") or {}
        if mysql_probe.get("status") == "ERROR":
            alerts.append({
                "source": "dependency_probe",
                "level": "CRITICAL",
                "reason": "mysql_unreachable",
                "detail": {"error": mysql_probe.get("error")},
            })

        if consistency and not consistency.get("consistent"):
            alerts.append({
                "source": "consistency_scan",
                "level": "WARNING",
                "reason": "data_inconsistent",
                "detail": {
                    "inconsistent": consistency.get("inconsistent"),
                    "counts": consistency.get("counts"),
                },
            })

        return alerts

    def _apply_incidents(self, alerts, index: int) -> None:
        """CRITICAL 告警开事件；条件消失时置 RESOLVED。WARNING 只记录不建事件。"""
        seen: dict[str, dict] = {}
        for alert in alerts:
            if alert.get("level") != "CRITICAL":
                continue
            key = str(alert.get("reason"))
            seen[key] = alert
            existing = self._open_incidents.get(key)
            if existing is not None:
                existing["occurrences"] += 1
                existing["last_seen_tick"] = index
                alert["incident_id"] = existing["incident_id"]
                continue
            incident = self.alert_manager.create_incident(
                RuntimeAlert(level="CRITICAL", reason=key, health_score=0.0),
                "inc_" + self.worker_id + "_" + str(index) + "_" + key,
            )
            self._open_incidents[key] = {
                "incident_id": incident.incident_id,
                "status": incident.status,
                "alert_level": incident.alert_level,
                "reason": incident.reason,
                "opened_tick": index,
                "occurrences": 1,
                "last_seen_tick": index,
            }
            alert["incident_id"] = incident.incident_id

        for key in list(self._open_incidents):
            if key in seen:
                continue
            record = self._open_incidents.pop(key)
            record["status"] = "RESOLVED"
            record["resolved_tick"] = index
            self._resolved_incidents.append(record)

    def _emit_alerts(self, alerts, index: int) -> None:
        for alert in alerts:
            record = {"worker_id": self.worker_id, "runtime": self.runtime, "tick": index}
            record.update(alert)
            record["timestamp"] = self._clock().isoformat()
            self._append_jsonl(self.alert_log, record)
            self._alerts_total += 1
            if alert.get("level") == "CRITICAL" and self.alert_command:
                outcome = run_alert_command(self.alert_command, record)
                alert["command"] = outcome
                self._append_jsonl(
                    self.alert_log,
                    {
                        "worker_id": self.worker_id,
                        "tick": index,
                        "timestamp": self._clock().isoformat(),
                        "alert_command_result": outcome,
                        "reason": alert.get("reason"),
                    },
                )
            if alert.get("level") == "CRITICAL" and self._alert_channel:
                outcome = asdict(self._alert_channel.deliver(record))
                alert["webhook"] = outcome
                self._append_jsonl(
                    self.alert_log,
                    {
                        "worker_id": self.worker_id,
                        "tick": index,
                        "timestamp": self._clock().isoformat(),
                        "alert_webhook_result": outcome,
                        "reason": alert.get("reason"),
                    },
                )

    def _run_auto_recovery(self, alerts, index: int) -> list:
        """CRITICAL 且带 incident_id 的告警，按 auto_recover 开关做自动恢复。

        默认关闭（self.auto_recover=False 时直接返回空）；开启后对 AGENT_RUNTIME
        决策 RESTART_AGENT 执行注入的 restart_agent_command。结果写回 alert_log
        （auto_recovery_result），失败如实记录，不静默。
        """
        if not self.auto_recover:
            return []
        events = [
            AutoRecoveryEvent(
                incident_id=alert["incident_id"],
                severity="CRITICAL",
                reason=str(alert.get("reason")),
                component=_component_for_alert(alert),
            )
            for alert in alerts
            if alert.get("level") == "CRITICAL" and alert.get("incident_id")
        ]
        if not events:
            return []

        handlers = {}
        if self.restart_agent_command:
            def restart_handler(decision):
                return run_alert_command(self.restart_agent_command, asdict(decision))

            handlers["RESTART_AGENT"] = restart_handler

        outcomes = orchestrate(
            events=tuple(events),
            auto_recover=True,
            handlers=handlers,
        )
        for outcome in outcomes:
            payload = {
                "worker_id": self.worker_id,
                "tick": index,
                "timestamp": self._clock().isoformat(),
                "incident_id": outcome.incident_id,
                "action": outcome.action,
                "executed": outcome.executed,
                "reason": outcome.reason,
                "auto_recovery_result": (
                    asdict(outcome.record) if outcome.record is not None else None
                ),
            }
            self._append_jsonl(self.alert_log, payload)
            self._auto_recovery_outcomes.append(payload)
        return [asdict(outcome) for outcome in outcomes]

    @staticmethod
    def _append_jsonl(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def _epoch(self, value) -> int | None:
        parsed = _parse_iso(value)
        if parsed is None:
            return None
        return int(parsed.replace(tzinfo=timezone.utc).timestamp())

    def _write_metrics(self, result: TickResult) -> dict:
        text = render_metrics(
            result,
            worker_id=self.worker_id,
            runtime=self.runtime,
            ticks_total=len(self._results) + 1,
            alerts_total=self._alerts_total,
            scans_total=self._scans_total,
            open_incidents=len(self._open_incidents),
            epoch=self._epoch(result.started_at),
        )
        try:
            _write_atomic(self.metrics_file, text)
        except Exception as exc:  # noqa: BLE001
            return {
                "path": str(self.metrics_file),
                "written": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        return {
            "path": str(self.metrics_file),
            "written": True,
            "bytes": len(text.encode("utf-8")),
        }

    # ---- tick / run ----

    def tick(self, index: int) -> TickResult:
        started_wall = self._clock()
        started = time.perf_counter()
        errors: list[str] = []

        heartbeat = self._write_heartbeat()
        if heartbeat.get("status") == "ERROR":
            errors.append("heartbeat: " + str(heartbeat.get("error")))

        probes = {"redis": self._probe_redis(), "mysql": self._probe_mysql()}
        for name, probe in probes.items():
            if probe.get("status") == "ERROR":
                errors.append(name + ": " + str(probe.get("error")))

        consistency = None
        if index % self.consistency_every == 0:
            consistency, scan_error = self._run_consistency_scan()
            if scan_error:
                errors.append("consistency: " + scan_error)
            if consistency is not None:
                self._scans_total += 1

        health = self._build_health(probes)
        if health.get("status") == "UNKNOWN":
            errors.append("health: " + str(health.get("reason")))

        alerts = self._evaluate_alerts(
            heartbeat=heartbeat, probes=probes, health=health, consistency=consistency
        )
        self._apply_incidents(alerts, index)
        auto_recovery = self._run_auto_recovery(alerts, index)
        self._emit_alerts(alerts, index)

        provisional = TickResult(
            index=index,
            started_at=started_wall.isoformat(),
            duration_ms=int((time.perf_counter() - started) * 1000),
            heartbeat=heartbeat,
            probes=probes,
            health=health,
            alerts=tuple(alerts),
            open_incidents=tuple(dict(value) for value in self._open_incidents.values()),
            consistency=consistency,
            metrics={},
            auto_recovery=tuple(auto_recovery),
            errors=tuple(errors),
        )
        result = replace(provisional, metrics=self._write_metrics(provisional))
        # Single-writer tick boundary: rotate only tick telemetry, never alert evidence.
        maybe_rotate_tick_log(self.tick_log, max_bytes=self.tick_log_max_bytes)
        self._append_jsonl(
            self.tick_log,
            {"worker_id": self.worker_id, "runtime": self.runtime, **asdict(result)},
        )
        self._results.append(result)
        if len(self._results) > self.max_retained_ticks:
            del self._results[: len(self._results) - self.max_retained_ticks]
        return result

    def _sleep_between_ticks(self) -> None:
        remaining = self.interval_seconds
        while remaining > 0 and not self._stop:
            step = min(SLEEP_CHUNK_SECONDS, remaining)
            self._sleep(step)
            remaining -= step

    def run(self, *, max_ticks=None, max_seconds=None) -> dict:
        self._started_at = self._clock()
        started = time.perf_counter()
        index = 0
        while not self._stop:
            index += 1
            self.tick(index)
            if max_ticks is not None and index >= int(max_ticks):
                break
            if max_seconds is not None and (time.perf_counter() - started) >= float(max_seconds):
                break
            if self._stop:
                break
            self._sleep_between_ticks()
        self.shutdown()
        return self.summary()

    def shutdown(self) -> dict:
        """优雅退出：删心跳键（避免下线的 Worker 一直显示 ONLINE）+ 关连接。"""
        outcome: dict = {"heartbeat_removed": False, "closed": []}
        if self.store is not None:
            try:
                self.store.delete_state(self.heartbeat_key())
                outcome["heartbeat_removed"] = True
            except Exception as exc:  # noqa: BLE001
                outcome["heartbeat_error"] = f"{type(exc).__name__}: {exc}"
        for name, target in (("redis", self.redis_client), ("mysql", self.connection)):
            closer = getattr(target, "close", None)
            if not callable(closer):
                continue
            try:
                closer()
                outcome["closed"].append(name)
            except Exception:  # noqa: BLE001
                pass
        self._shutdown = outcome
        return outcome

    def summary(self) -> dict:
        alerts = [alert for result in self._results for alert in result.alerts]
        levels = {
            level: sum(1 for alert in alerts if alert.get("level") == level)
            for level in ALERT_LEVELS
        }
        return {
            "worker_id": self.worker_id,
            "runtime": self.runtime,
            "instance_id": self.instance_id,
            "instance_started_at": _iso(self.instance_started_at),
            "health_window_seconds": self.health_window_seconds,
            "ticks": len(self._results),
            "started_at": _iso(self._started_at),
            "finished_at": self._clock().isoformat(),
            "interval_seconds": self.interval_seconds,
            "consistency_every": self.consistency_every,
            "alert_counts": levels,
            "open_incidents": [dict(value) for value in self._open_incidents.values()],
            "resolved_incidents": [dict(value) for value in self._resolved_incidents],
            "last_tick": asdict(self._results[-1]) if self._results else None,
            "shutdown": self._shutdown,
        }


def exit_code(summary: dict) -> int:
    """0 = 无未消解告警；2 = 结束时仍有 WARNING / CRITICAL。"""
    if summary.get("open_incidents"):
        return EXIT_ALERTING
    last_tick = summary.get("last_tick") or {}
    for alert in last_tick.get("alerts") or ():
        if alert.get("level") in ALERTING_LEVELS:
            return EXIT_ALERTING
    return EXIT_OK


def _env_summary() -> dict:
    """Resolved topology plus explicit-env provenance; credentials stay presence-only."""
    return storage_config.storage_summary()


def build_worker(args) -> RuntimeOperationsWorker:
    """按 CLI / 环境装配真实依赖；依赖不可用直接抛异常，由 main 转成退出码 3。"""
    worker_id = (
        args.worker_id
        or os.environ.get("STORYOS_WORKER_ID")
        or ("runtime-worker-" + str(os.getpid()))
    )
    jsonl_root = args.jsonl_root or storage_config.runtime_store_config()["jsonl_root"]

    store = None
    redis_client = None
    if not args.no_redis:
        from platform.state.redis_connection import RedisConnection
        from platform.state.redis_runtime_state_store import RedisRuntimeStateStore

        adapter = RedisConnection(**storage_config.redis_connection_kwargs())
        redis_client = adapter.client
        # 启动即探活：连不上就退出 3，不允许一个写不了心跳的 Worker 假装常驻。
        redis_client.ping()
        store = RedisRuntimeStateStore(redis_client)

    connection = None
    trace_repository = None
    runtime_store_mode = storage_config.runtime_store_config()["mode"]
    if not args.no_mysql:
        if not HAS_MYSQL_DRIVER:
            raise RuntimeError("pymysql is not installed; use --no-mysql for offline runs")
        connection = MySqlConnection(**storage_config.mysql_connection_kwargs())
        if runtime_store_mode == "mysql":
            trace_repository = MySqlTraceRepository(connection)

    return RuntimeOperationsWorker(
        worker_id=worker_id,
        runtime=args.runtime,
        store=store,
        redis_client=redis_client,
        connection=connection,
        trace_repository=trace_repository,
        runtime_store_mode=runtime_store_mode,
        jsonl_root=jsonl_root,
        interval_seconds=args.interval,
        consistency_every=args.consistency_every,
        stuck_seconds=args.stuck_minutes * 60,
        health_window_seconds=args.health_window_minutes * 60,
        instance_id=args.instance_id or os.environ.get("STORYOS_WORKER_INSTANCE_ID"),
        metrics_file=args.metrics_file,
        alert_log=args.alert_log,
        tick_log=args.tick_log,
        tick_log_max_mib=args.tick_log_max_mib,
        alert_command=args.alert_command,
        alert_webhook=args.alert_webhook,
        alert_webhook_format=args.alert_webhook_format,
        auto_recover=args.auto_recover,
        restart_agent_command=args.restart_agent_command,
    )


def _install_signal_handlers(worker) -> list:
    """SIGINT / SIGTERM / SIGBREAK -> 优雅退出；装不上的平台跳过。"""
    installed: list[str] = []
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            signal.signal(number, lambda signum, frame: worker.request_stop())
        except (ValueError, OSError, RuntimeError):
            continue
        installed.append(name)
    return installed


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Story OS V3 Phase9 常驻 Runtime Worker 载体（心跳 / 探针 / 巡检 / 指标 / 告警）"
    )
    parser.add_argument("--worker-id", default=None, help="默认 STORYOS_WORKER_ID 或 runtime-worker-<pid>")
    parser.add_argument(
        "--instance-id",
        default=None,
        help="Worker 运行实例 ID；默认 STORYOS_WORKER_INSTANCE_ID 或由 worker_id+启动时间生成",
    )
    parser.add_argument("--runtime", default=DEFAULT_RUNTIME)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS, help="tick 间隔秒")
    parser.add_argument(
        "--consistency-every",
        type=int,
        default=DEFAULT_CONSISTENCY_EVERY,
        help="每 N 个 tick 跑一次 Legacy vs MySQL 一致性巡检",
    )
    parser.add_argument(
        "--stuck-minutes",
        type=float,
        default=DEFAULT_STUCK_MINUTES,
        help="RUNNING span 超过该分钟数判为卡住",
    )
    parser.add_argument(
        "--health-window-minutes",
        type=float,
        default=DEFAULT_HEALTH_WINDOW_MINUTES,
        help="健康评分终结 Trace 的滑动时间窗；同时受当前 Worker 实例启动时间约束",
    )
    parser.add_argument("--once", action="store_true", help="只跑一个 tick（CI / 验收用）")
    parser.add_argument("--max-ticks", type=int, default=None)
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument("--jsonl-root", default=None, help="默认 STORYOS_RUNTIME_JSONL_ROOT 或 .storyos")
    parser.add_argument("--no-redis", action="store_true", help="不探 Redis、不写心跳（离线）")
    parser.add_argument("--no-mysql", action="store_true", help="不探 MySQL，也不做一致性巡检")
    parser.add_argument("--metrics-file", default=None)
    parser.add_argument("--alert-log", default=None)
    parser.add_argument("--tick-log", default=None)
    parser.add_argument("--tick-log-max-mib", type=float, default=64,
                        help="轮转 tick JSONL 的 MiB 阈值；0=关闭，原始日志无损 gzip 归档")
    parser.add_argument(
        "--alert-command",
        default=None,
        help="CRITICAL 时执行的外部命令；告警 JSON 走 stdin（真实告警通道挂载点）",
    )
    parser.add_argument("--evidence-file", default=None)
    parser.add_argument(
        "--alert-webhook",
        default=None,
        help="CRITICAL 时 POST 告警 JSON 的 webhook URL（真实告警通道）",
    )
    parser.add_argument(
        "--alert-webhook-format",
        default="json",
        choices=("json", "dingtalk"),
        help="webhook 消息格式：json=原始 JSON，dingtalk=钉钉 markdown",
    )
    parser.add_argument(
        "--auto-recover",
        action="store_true",
        help="开启后对 CRITICAL 事件自动执行恢复决策（默认关闭，需显式授权）",
    )
    parser.add_argument(
        "--restart-agent-command",
        default=None,
        help="RESTART_AGENT 决策时执行的外部命令；决策 JSON 走 stdin（默认不配置则不执行）",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv=None, *, install_signals: bool = True) -> int:
    args = _parse_args(argv)
    max_ticks = 1 if args.once else args.max_ticks

    try:
        worker = build_worker(args)
    except Exception as exc:  # noqa: BLE001 - 环境不可用必须显式退出
        print("启动失败：" + type(exc).__name__ + ": " + str(exc))
        return EXIT_ENV_ERROR

    installed = _install_signal_handlers(worker) if install_signals else []
    if not args.quiet:
        print("Story OS V3 Phase9 常驻 Runtime Worker")
        print("  worker_id=" + worker.worker_id + " runtime=" + worker.runtime)
        print("  interval=" + str(worker.interval_seconds) + "s consistency_every="
              + str(worker.consistency_every))
        print("  jsonl_root=" + worker.jsonl_root)
        print("  signals=" + (",".join(installed) if installed else "none"))
        print("  metrics=" + str(worker.metrics_file))

    try:
        summary = worker.run(max_ticks=max_ticks, max_seconds=args.max_seconds)
    except Exception as exc:  # noqa: BLE001
        print("运行中断：" + type(exc).__name__ + ": " + str(exc))
        try:
            worker.shutdown()
        except Exception:  # noqa: BLE001
            pass
        return EXIT_ENV_ERROR

    evidence_path = Path(args.evidence_file) if args.evidence_file else DEFAULT_EVIDENCE_FILE
    try:
        _write_atomic(
            evidence_path,
            json.dumps(
                {
                    "summary": summary,
                    "environment": _env_summary(),
                    "config": {
                        "worker_id": worker.worker_id,
                        "runtime": worker.runtime,
                        "interval_seconds": worker.interval_seconds,
                        "consistency_every": worker.consistency_every,
                        "stuck_seconds": worker.stuck_seconds,
                        "health_window_seconds": worker.health_window_seconds,
                        "instance_id": worker.instance_id,
                        "instance_started_at": _iso(worker.instance_started_at),
                        "jsonl_root": worker.jsonl_root,
                        "metrics_file": str(worker.metrics_file),
                        "alert_log": str(worker.alert_log),
                        "tick_log": str(worker.tick_log),
                        "alert_command_configured": bool(worker.alert_command),
                        "alert_webhook_configured": bool(worker.alert_webhook),
                        "auto_recover_configured": bool(worker.auto_recover),
                        "restart_agent_command_configured": bool(worker.restart_agent_command),
                    },
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        print("证据写入失败：" + type(exc).__name__ + ": " + str(exc))

    if not args.quiet:
        print("== 汇总 ==")
        print("  ticks=" + str(summary["ticks"]) + " alert_counts="
              + json.dumps(summary["alert_counts"], ensure_ascii=False))
        print("  open_incidents=" + str(len(summary["open_incidents"])))
        print("  heartbeat_removed="
              + str((summary.get("shutdown") or {}).get("heartbeat_removed")))
        print("  evidence=" + str(evidence_path))
        if summary["open_incidents"]:
            print("  未消解事件：" + ", ".join(
                str(item.get("reason")) for item in summary["open_incidents"]))
        print("  退出码=" + str(exit_code(summary)) + "（0=正常 2=仍有告警 3=环境错误）")

    return exit_code(summary)


if __name__ == "__main__":
    raise SystemExit(main())
