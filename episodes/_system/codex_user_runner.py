#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Story OS V2.7 Codex user-mode execution bridge.

Problem solved: a workspace/automation host may run as ``NT AUTHORITY\\SYSTEM`` while the Codex
sign-in, config and model cache belong to the interactive Windows user. A
SYSTEM process that launches ``codex exec`` therefore dies with
``Access Denied`` / ``os error 5`` (for example on
``%USERPROFILE%\\.codex\\models_cache.json``).

This module is the single Codex process execution adapter for that boundary:

- ``serve`` starts a loopback-only HTTP runner in the *interactive user*
  context, which owns the Codex credential and launches ``codex``.
- ``run_codex()`` is a faithful ``subprocess.run`` replacement used by every
  Story OS codex call site. It runs codex directly when Story OS already runs
  as the interactive user, and transparently forwards the same task over the
  loopback bridge when Story OS runs as a non-interactive identity.
- ``exec`` exposes the same transport to a plain shell so a SYSTEM-hosted command
  line can never be forced to read ``C:\\Users\\<user>\\.codex`` itself.

Hard boundaries this adapter keeps:

- executable is always Codex; the caller may never nominate an arbitrary exe;
- the runner is the only process that reads the Codex credential;
- ``auth.json`` / session tokens are never copied to the caller, the repo or
  the request;
- the runner never records a Story OS stage, ledger, gate or repair budget.
  It only reports "Codex execution succeeded/failed".

Transport contract (loopback only, `127.0.0.1`):

    POST /v1/codex/exec   run one declarative Codex task
    GET  /v1/health       runner identity / codex availability (no secrets)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
import dataclasses
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import runtime_timeout_policy
import story_json

SCHEMA_VERSION = 1
RUNNER_PROTOCOL_REVISION = 2
ROOT = Path(__file__).resolve().parents[2]
RUNTIME_REL = Path("runtime/codex-user-runner")
ENDPOINT_NAME = "endpoint.json"
TOKEN_NAME = "token"
LOG_NAME = "runner-log.jsonl"
RESULT_DIR_NAME = "task-results"
RUNNER_TMP_NAME = "tmp"
RUNNER_TASK_HOME_NAME = "codex-task-homes"
RUNNER_INPUT_DIR_NAME = "codex-inputs"
# Provider artifacts are minted inside the runner user's throwaway CODEX_HOME,
# which the caller cannot read; the runner mirrors them into the caller-owned
# task workdir under this name so cross-bridge image recovery still works.
EXPORT_DIR_NAME = "codex-generated-images"
IMAGE_ARTIFACT_SETTLE_SECONDS = 2.0
IMAGE_ARTIFACT_SETTLE_POLL_SECONDS = 0.10

DRIVER_EXE = "exe"
DRIVER_CMD = "cmd"
DRIVER_PY = "py"

ALLOWED_CODEX_BASENAMES = {
    "codex", "codex.exe", "codex.cmd", "codex.bat", "codex.py", "codex.ps1",
}
ALLOWED_TASK_TYPES = {
    "critic", "scoped_step", "image", "review", "smoke", "generic_codex",
}
# Only these request-supplied environment keys are applied on the runner side.
ENV_ALLOWED_EXACT = {"PYTHONUTF8", "PYTHONIOENCODING", "STORY_OS_WORKER_ID"}
ENV_ALLOWED_PREFIX = ("STORY_OS_",)
# The Codex Windows sandbox driver is user-level machine state. When the user's
# config says ``elevated`` and the sandbox account cannot be logged on, every
# ``-s workspace-write`` run dies with CreateProcessWithLogonW error 1385. The
# runner pins a working driver here (single Codex adapter) instead of failing at
# each call site. Set the env var to "" to defer to the user's own config.
WINDOWS_SANDBOX_ENV = "STORY_OS_CODEX_WINDOWS_SANDBOX"
DEFAULT_WINDOWS_SANDBOX = "unelevated"
# CODEX_HOME is deliberately not passed through from the caller: the runner
# owns its own Codex home. `isolated` asks for a throwaway per-task home that is
# seeded from the runner user's real ``~/.codex`` credentials.
CODEX_HOME_MODES = {"inherit", "isolated"}

NON_INTERACTIVE_ACCOUNTS = {"SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE"}

DEFAULT_MAX_TIMEOUT_SECONDS = 7200
DEFAULT_TASK_TIMEOUT_SECONDS = 900
# Transport-level probe bounds are named so no bare timeout literal bypasses
# the runtime timeout policy sweep.
VERSION_PROBE_TIMEOUT_SECONDS = 30
HEALTH_TIMEOUT_SECONDS = 15.0
ACL_TIMEOUT_SECONDS = 20
# The policy roles that own this bridge's own defaults (config/storyos.yaml).
DEFAULT_TASK_TIMEOUT_ROLE = "review_critic"
DEFAULT_MAX_TIMEOUT_ROLE = "codex_supervisor_run"
HTTP_MARGIN_SECONDS = 60
MAX_REQUEST_BYTES = 64 * 1024 * 1024

TRANSPORT_ENV = "STORY_OS_CODEX_TRANSPORT"
RUNNER_URL_ENV = "STORY_OS_CODEX_RUNNER_URL"
RUNNER_TOKEN_ENV = "STORY_OS_CODEX_RUNNER_TOKEN"
EXPECTED_USER_ENV = "STORY_OS_CODEX_RUNNER_USER"
MAX_TIMEOUT_ENV = "STORY_OS_CODEX_BRIDGE_MAX_TIMEOUT"

# Native Codex is the only permitted CLI model transport. API keys use a separate adapter.
NATIVE_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
PROVIDER_EVIDENCE_KEYS = (
    "transport_route", "transport_route_reason", "transport_base_url",
)


# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------
class CodexUserRunnerError(RuntimeError):
    """Technical/infrastructure failure of the Codex user-mode transport.

    Subclasses RuntimeError so every existing Story OS technical-failure lane
    keeps its current handling, while the machine code stays explicit.
    """

    code = "CODEX_USER_RUNNER_UNAVAILABLE"

    def __init__(self, code: str | None = None, detail: str = "") -> None:
        self.code = code or type(self).code
        self.detail = detail or ""
        super().__init__(f"{self.code}: {self.detail}" if self.detail else self.code)


class CodexUserRunnerUnavailable(CodexUserRunnerError):
    code = "CODEX_USER_RUNNER_UNAVAILABLE"


class CodexUserRunnerWrongIdentity(CodexUserRunnerError):
    code = "CODEX_USER_RUNNER_WRONG_IDENTITY"


class CodexUserRunnerAuthFailed(CodexUserRunnerError):
    code = "CODEX_USER_RUNNER_AUTH_FAILED"


class CodexUserRunnerWorkspaceUnavailable(CodexUserRunnerError):
    code = "CODEX_USER_RUNNER_WORKSPACE_UNAVAILABLE"


class CodexUserRunnerRejected(CodexUserRunnerError):
    code = "CODEX_USER_RUNNER_TASK_REJECTED"


class CodexUserRunnerTimeout(CodexUserRunnerError, subprocess.TimeoutExpired):
    """Timeout that is both an explicit runner code and a subprocess timeout."""

    code = "CODEX_USER_RUNNER_TIMEOUT"

    def __init__(self, cmd, timeout, detail: str = "") -> None:
        self.cmd = cmd
        self.timeout = timeout
        self.output = None
        self.stderr = None
        self.returncode = 124
        self.remote = {"timed_out": True, "returncode": 124}
        self.detail = detail or f"Codex task exceeded {timeout}s"
        RuntimeError.__init__(self, f"{self.code}: {self.detail}")


class CodexExecFailed(CodexUserRunnerError):
    code = "CODEX_EXEC_FAILED"


TECHNICAL_CODES = frozenset(
    {
        "CODEX_USER_RUNNER_UNAVAILABLE",
        "CODEX_USER_RUNNER_WRONG_IDENTITY",
        "CODEX_USER_RUNNER_AUTH_FAILED",
        "CODEX_USER_RUNNER_TIMEOUT",
        "CODEX_USER_RUNNER_TASK_REJECTED",
        "CODEX_USER_RUNNER_WORKSPACE_UNAVAILABLE",
        "CODEX_EXEC_FAILED",
    }
)


def error_code(exc: BaseException) -> str | None:
    return getattr(exc, "code", None) if isinstance(exc, CodexUserRunnerError) else None


def is_technical(exc: BaseException) -> bool:
    code = error_code(exc)
    return bool(code) and code in TECHNICAL_CODES


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
def current_identity() -> str:
    """Return ``DOMAIN\\user`` for the effective process token."""
    if os.name == "nt":
        try:
            import ctypes

            size = ctypes.c_ulong(256)
            buf = ctypes.create_unicode_buffer(256)
            if ctypes.windll.advapi32.GetUserNameW(buf, ctypes.byref(size)):
                user = buf.value
                domain = os.environ.get("USERDOMAIN") or ""
                return f"{domain}\\{user}" if domain and user else (user or domain)
        except Exception:
            pass
    domain = os.environ.get("USERDOMAIN") or ""
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if not user:
        try:
            import getpass

            user = getpass.getuser()
        except Exception:
            user = "unknown"
    return f"{domain}\\{user}" if domain and user else user


def account_name(identity: str | None = None) -> str:
    raw = str(identity if identity is not None else current_identity()).strip()
    return raw.rsplit("\\", 1)[-1].upper()


def is_non_interactive(identity: str | None = None) -> bool:
    """True for identities that cannot own an interactive Codex profile."""
    return account_name(identity) in NON_INTERACTIVE_ACCOUNTS


def expected_user() -> str | None:
    raw = str(os.environ.get(EXPECTED_USER_ENV) or "").strip()
    return raw or None


def user_matches(expected: str, actual: str) -> bool:
    exp = str(expected or "").strip().lower()
    act = str(actual or "").strip().lower()
    if not exp or not act:
        return False
    return exp == act or account_name(exp) == account_name(act)


# ---------------------------------------------------------------------------
# Transport routing
# ---------------------------------------------------------------------------
def configured_transport() -> str:
    raw = str(os.environ.get(TRANSPORT_ENV) or "auto").strip().lower()
    if raw in {"direct", "local", "local_codex"}:
        return "direct"
    if raw in {"user_runner", "bridge", "runner"}:
        return "user_runner"
    if raw in {"", "auto"}:
        return "auto"
    raise CodexUserRunnerRejected(
        "CODEX_USER_RUNNER_TASK_REJECTED", f"invalid {TRANSPORT_ENV}={raw!r}"
    )


def bridge_required() -> bool:
    """True when Codex must run through the interactive-user runner."""
    mode = configured_transport()
    if mode == "user_runner":
        return True
    if mode == "direct":
        return False
    if os.name != "nt":
        return False
    return is_non_interactive()


def transport_name() -> str:
    return "user_runner" if bridge_required() else "direct"


def _config_overrides(argv: list[str]) -> list[str]:
    values: list[str] = []
    tokens = [str(x) for x in argv]
    for index, token in enumerate(tokens):
        if token in {"-c", "--config"} and index + 1 < len(tokens):
            values.append(tokens[index + 1])
    return values


def resolve_provider_transport(
    argv: list[str], *, env: dict | None = None, task_type: str = "generic_codex",
    health_probe=None, image_capability_probe=None,
) -> dict | None:
    """Pin every Codex model execution to the native backend.

    Never auto-discover OpenCodex, never accept arbitrary provider endpoints.
    Login and model-catalog diagnostics do not execute a model and are left
    untouched. Probe arguments remain solely for call-site compatibility;
    they are never invoked. API_KEY_DIRECT has its own adapter.
    """
    command = [str(x) for x in argv]
    if "exec" not in command:
        return None
    source = dict(env) if env is not None else dict(os.environ)
    if task_type == "image":
        # Native image execution must never accept a legacy proxy/HTTP route,
        # including when OPENAI_BASE_URL is otherwise unset. API images use a
        # separate official adapter, not Codex subscription transport.
        image_route = str(source.get("STORY_OS_IMAGE_PROVIDER_ROUTE") or "").strip().lower()
        if image_route and image_route not in {"native_codex", "codex_subscription"}:
            raise CodexUserRunnerRejected("CODEX_NATIVE_IMAGE_PROVIDER_REQUIRED",
                                          "non-native Codex image route")
    env_base = str(source.get("OPENAI_BASE_URL") or "").strip()
    if env_base and env_base.rstrip("/") != NATIVE_CODEX_BASE_URL:
        raise CodexUserRunnerRejected(
            "MODEL_TRANSPORT_FORBIDDEN", "non-native inherited Codex endpoint"
        )
    overrides = _config_overrides(command)
    for token in command:
        if token.startswith("--config="):
            overrides.append(token[len("--config="):])
        elif token.startswith("-c") and token != "-c" and "=" in token[2:]:
            overrides.append(token[2:])
    explicit_native = False
    for item in overrides:
        key, sep, raw_value = str(item).strip().partition("=")
        if not sep:
            continue
        key = key.strip()
        value = raw_value.strip().strip("\"'")
        if key == "model_provider":
            if value != "openai":
                raise CodexUserRunnerRejected(
                    "MODEL_TRANSPORT_FORBIDDEN", "custom Codex model_provider"
                )
        elif key == "openai_base_url":
            if value.rstrip("/") != NATIVE_CODEX_BASE_URL:
                raise CodexUserRunnerRejected(
                    "MODEL_TRANSPORT_FORBIDDEN", "custom Codex base_url"
                )
            explicit_native = True
        elif key.startswith("model_providers."):
            raise CodexUserRunnerRejected(
                "MODEL_TRANSPORT_FORBIDDEN", "custom Codex provider configuration"
            )
    return {
        "transport_route": "native_codex",
        "transport_route_reason": (
            "native_only_explicit_native" if explicit_native else "native_only_policy"
        ),
        "transport_base_url": NATIVE_CODEX_BASE_URL,
        "provider_args": [
            "-c", 'model_provider="openai"',
            "-c", f'openai_base_url="{NATIVE_CODEX_BASE_URL}"',
        ],
    }


def _insert_codex_args(command: list[str], extra: list[str]) -> list[str]:
    if not extra:
        return command
    for index, token in enumerate(command):
        if is_codex_basename(token):
            return command[: index + 1] + list(extra) + command[index + 1 :]
    return command


def provider_transport_evidence(remote) -> dict:
    data = remote if isinstance(remote, dict) else {}
    return {key: data.get(key) for key in PROVIDER_EVIDENCE_KEYS if data.get(key) is not None}


# ---------------------------------------------------------------------------
# Shared on-disk channel
# ---------------------------------------------------------------------------
def _shared_worktree_root(root: Path) -> Path:
    """Use the authoritative repository checkout for transient Runner state.

    A git-linked worktree contains a .git *file* pointing into the parent
    repository's .git/worktrees/<slot>. No git subprocess, credentials,
    arbitrary endpoint override, or branch mutation is needed.
    """
    marker = root / ".git"
    if not marker.is_file():
        return root
    try:
        content = marker.read_text(encoding="utf-8-sig").strip()
        if not content.startswith("gitdir: "):
            return root
        pointer = Path(content[len("gitdir: "):].strip())
        if not pointer.is_absolute():
            pointer = root / pointer
        pointer = pointer.resolve()
        if pointer.parent.name != "worktrees" or pointer.parent.parent.name != ".git":
            return root
        common = pointer.parent.parent
        if not common.is_dir() or not pointer.is_dir():
            return root
        # Only accept a Git marker pointing back to this repo's own linked slots.
        # A forged pointer must not disclose another repo's Runner endpoint.
        root.resolve(strict=True).relative_to((common.parent / ".worktrees").resolve(strict=True))
        return common.parent
    except (OSError, RuntimeError, ValueError):
        return root


def runtime_dir() -> Path:
    return _shared_worktree_root(ROOT) / RUNTIME_REL


def endpoint_path() -> Path:
    local = runtime_dir() / ENDPOINT_NAME
    if local.is_file() or runtime_dir().resolve() != (ROOT / RUNTIME_REL).resolve():
        return local
    # Git worktrees must reuse the one interactive user's existing native
    # Codex runner. Never copy its token into a worktree or discover an
    # arbitrary endpoint outside the same canonical StoryOS repository.
    git_pointer = ROOT / ".git"
    if not git_pointer.is_file():
        return local
    try:
        pointer = git_pointer.read_text(encoding="utf-8-sig").strip()
        if not pointer.startswith("gitdir: "):
            return local
        gitdir = Path(pointer[len("gitdir: "):].strip())
        if not gitdir.is_absolute():
            gitdir = (ROOT / gitdir).resolve()
        gitdir = gitdir.resolve()
        if gitdir.parent.name != "worktrees" or gitdir.parent.parent.name != ".git":
            return local
        main_root = gitdir.parents[2].resolve()
        ROOT.resolve().relative_to((main_root / ".worktrees").resolve())
        shared = main_root / RUNTIME_REL / ENDPOINT_NAME
        return shared if shared.is_file() else local
    except (OSError, UnicodeError, ValueError):
        return local


def token_path() -> Path:
    return runtime_dir() / TOKEN_NAME


def tmp_root() -> Path:
    return runtime_dir() / RUNNER_TMP_NAME


def _read_json(path: Path) -> dict:
    return story_json.read_json(path)


def _write_json(path: Path, data: dict) -> None:
    story_json.write_json(path, data)


def task_result_path(request_id: str) -> Path:
    rid = str(request_id or "").strip()
    if not rid or any(ch not in "0123456789abcdefABCDEF-" for ch in rid):
        raise ValueError(f"invalid runner request_id: {request_id!r}")
    # Direct execution evidence belongs to this checkout. Only the bridge
    # endpoint and its token are shared with the interactive Runner.
    return ROOT / RUNTIME_REL / RESULT_DIR_NAME / f"{rid}.json"


def read_task_result(request_id: str) -> dict:
    """Read the durable result from the Runner which actually executed it.

    In a trusted Git worktree the interactive user Runner is shared with the
    canonical checkout, but this process's own runtime_dir() is not shared.
    Reading that local directory loses the persisted evidence and can falsely
    quarantine Final Semantic work as unverified. The already-validated
    endpoint_path() locates only the runner in this same repository.
    Direct-mode results stay in this checkout and retain the original path.
    """
    local = task_result_path(request_id)  # Always validate caller's ID.
    if bridge_required():
        endpoint = endpoint_path()
        if not endpoint.is_file():
            return {}
        path = endpoint.parent / RESULT_DIR_NAME / local.name
    else:
        path = local
    result = _read_json(path) if path.is_file() else {}
    if result and (not isinstance(result, dict)
                   or str(result.get("request_id") or "") != str(request_id)):
        return {}
    return result


def _direct_result_output(stdout, completed) -> bytes:
    """Read the exact merged Codex log bytes for a durable direct-mode receipt.

    A task with an Authority-owned request ID may not dispatch if its output
    would be invisible to recovery. The caller validated the sink first.
    """
    if stdout is subprocess.PIPE:
        data = completed.stdout
        return data.encode("utf-8") if isinstance(data, str) else bytes(data or b"")
    stdout.flush()
    return Path(stdout.name).read_bytes()


def _persist_direct_result(request_id: str, completed, stdout, evidence: dict) -> None:
    """Atomically publish a non-overwritable direct-mode Runner receipt.

    This records exact output and execution evidence; it does not authorize a
    Review PASS or another paid model attempt.
    """
    path = task_result_path(request_id)
    output = _direct_result_output(stdout, completed)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "request_id": request_id,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "returncode": int(completed.returncode),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "output_bytes": len(output),
        "output_base64": base64.b64encode(output).decode("ascii"),
        "evidence": evidence,
    }
    fd, pending = tempfile.mkstemp(prefix=f".{request_id}.", suffix=".pending", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(pending, path)  # atomic NO-REPLACE
    finally:
        Path(pending).unlink(missing_ok=True)


def _pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) needs PROCESS_ALL_ACCESS on Windows and can report a
        # live same-user process as dead. Query the exit code instead.
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            try:
                code = ctypes.c_ulong(0)
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return False
                return int(code.value) == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            pass
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except Exception:
        return True
    return True


def reconcile_dead_endpoint() -> dict:
    """Reclaim only this user's provably dead Runner pointer, never its Codex credentials.

    This is invoked by the *interactive* Task Scheduler carrier, not SYSTEM.
    A live, foreign, malformed or unverifiable endpoint always blocks.
    """
    identity = current_identity()
    if is_non_interactive(identity):
        return {"status": "BLOCKED", "reason": "NON_INTERACTIVE_IDENTITY"}
    path = endpoint_path()
    if not path.is_file():
        return {"status": "ENDPOINT_ABSENT"}
    try:
        snapshot = path.read_bytes()
        record = json.loads(snapshot.decode("utf-8-sig"))
        if not isinstance(record, dict):
            return {"status": "BLOCKED", "reason": "ENDPOINT_IDENTITY_UNVERIFIED"}
        recorded_pid = record.get("pid")
        if (
            not isinstance(record, dict)
            or record.get("schema_version") != SCHEMA_VERSION
            or str(record.get("user") or "").casefold() != identity.casefold()
            or record.get("host") != "127.0.0.1"
            or not isinstance(record.get("port"), int)
            or not 1 <= record["port"] <= 65535
            or not isinstance(recorded_pid, int)
            or recorded_pid <= 0
            or not str(record.get("token") or "")
            or Path(str(record.get("codex_user_runner") or "")).resolve() != Path(__file__).resolve()
        ):
            return {"status": "BLOCKED", "reason": "ENDPOINT_IDENTITY_UNVERIFIED"}
        import psutil

        # A PID being alive includes reuse by an unrelated process; never reclaim
        # unless the OS confirms no process with this PID exists.
        if psutil.pid_exists(recorded_pid):
            return {"status": "BLOCKED", "reason": "ENDPOINT_PID_OCCUPIED"}
        if path.read_bytes() != snapshot or psutil.pid_exists(recorded_pid):
            return {"status": "BLOCKED", "reason": "ENDPOINT_CHANGED_OR_PID_OCCUPIED"}
        path.unlink()
        return {"status": "STALE_ENDPOINT_RECOVERED"}
    except (OSError, ValueError, TypeError, ImportError) as exc:
        return {"status": "BLOCKED", "reason": "ENDPOINT_RECOVERY_UNVERIFIED", "error_type": type(exc).__name__}

def read_endpoint(*, required: bool = True) -> dict:
    path = endpoint_path()
    if not path.is_file():
        if not required:
            return {}
        raise CodexUserRunnerUnavailable(
            "CODEX_USER_RUNNER_UNAVAILABLE",
            f"no runner endpoint at {path}; start it in the interactive user session with "
            "scripts/start_codex_user_runner.ps1",
        )
    try:
        return _read_json(path)
    except Exception as exc:
        raise CodexUserRunnerUnavailable(
            "CODEX_USER_RUNNER_UNAVAILABLE", f"unreadable runner endpoint {path}: {exc}"
        ) from exc


def client_credentials() -> dict:
    """Resolve runner URL/token, preferring explicit env over the shared file."""
    url = str(os.environ.get(RUNNER_URL_ENV) or "").strip()
    token = str(os.environ.get(RUNNER_TOKEN_ENV) or "").strip()
    if url and token:
        return {"url": url.rstrip("/"), "token": token, "source": "env"}
    endpoint = read_endpoint()
    if not _pid_alive(endpoint.get("pid")):
        raise CodexUserRunnerUnavailable(
            "CODEX_USER_RUNNER_UNAVAILABLE",
            f"runner pid {endpoint.get('pid')} from {endpoint_path()} is not running",
        )
    host = str(endpoint.get("host") or "127.0.0.1")
    port = endpoint.get("port")
    if not port:
        raise CodexUserRunnerUnavailable(
            "CODEX_USER_RUNNER_UNAVAILABLE", f"runner endpoint has no port: {endpoint_path()}"
        )
    return {
        "url": url.rstrip("/") if url else f"http://{host}:{int(port)}",
        "token": token or str(endpoint.get("token") or ""),
        "source": "endpoint_file",
        "endpoint": endpoint,
    }


# ---------------------------------------------------------------------------
# Codex executable resolution (never arbitrary executables)
# ---------------------------------------------------------------------------
def _codex_candidates() -> list[Path]:
    out: list[Path] = []
    raw = str(os.environ.get("CODEX_EXE") or "").strip()
    if raw:
        out.append(Path(raw).expanduser())
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            root = Path(local) / "OpenAI" / "Codex" / "bin"
            if root.is_dir():
                found = [p for p in list(root.glob("*/codex.exe")) + list(root.glob("codex.exe")) if p.is_file()]
                if found:
                    out.append(max(found, key=lambda p: p.stat().st_mtime_ns))
    for name in ("codex", "codex.exe", "codex.cmd", "codex.bat"):
        which = shutil.which(name)
        if which:
            out.append(Path(which))
    return out


def is_codex_basename(value: str | Path) -> bool:
    return Path(str(value)).name.strip().lower() in ALLOWED_CODEX_BASENAMES


def resolve_codex(prefer: str | Path | None = None) -> tuple[Path, str]:
    """Resolve the Codex CLI, optionally preferring a caller-nominated path.

    The nominated path is accepted only when its basename is a Codex CLI name and
    the file exists; anything else is replaced by the runner's own resolution.
    """
    if prefer:
        candidate = Path(str(prefer)).expanduser()
        if is_codex_basename(candidate) and candidate.is_file():
            return candidate.resolve(), "caller_nominated_codex"
    for candidate in _codex_candidates():
        if is_codex_basename(candidate) and candidate.is_file():
            return candidate.resolve(), "runner_resolved"
    raise CodexUserRunnerUnavailable(
        "CODEX_USER_RUNNER_UNAVAILABLE",
        "Codex CLI not found for the runner user; set CODEX_EXE for that user",
    )


def codex_driver(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return DRIVER_PY
    if suffix in {".cmd", ".bat"}:
        return DRIVER_CMD
    return DRIVER_EXE


def driver_prefix(codex: Path, driver: str) -> list[str]:
    if driver == DRIVER_PY:
        return [sys.executable, str(codex)]
    if driver == DRIVER_CMD:
        return ["cmd.exe", "/d", "/c", str(codex)]
    return [str(codex)]


def split_argv(argv: list[str]) -> tuple[str, list[str]]:
    """Split a caller-built codex command into (codex path, codex args)."""
    if not isinstance(argv, (list, tuple)) or not argv:
        raise CodexUserRunnerRejected("CODEX_USER_RUNNER_TASK_REJECTED", "codex argv must be a non-empty list")
    items = [str(x) for x in argv]
    head = items[0]
    rest = items[1:]
    if Path(head).name.lower() == "cmd.exe" and len(rest) >= 2 and rest[0].lower() in {"/d", "/c", "/s"}:
        rest = rest[2:] if rest[1].lower() in {"/c", "/s"} else rest[1:]
        head = rest[0] if rest else ""
        rest = rest[1:]
    if head and Path(head).name.lower() == Path(sys.executable).name.lower() and rest:
        head = rest[0]
        rest = rest[1:]
    if not head or not is_codex_basename(head):
        raise CodexUserRunnerRejected(
            "CODEX_USER_RUNNER_TASK_REJECTED",
            f"only Codex may be executed through this runner; got {head!r}",
        )
    return head, rest


def codex_home() -> tuple[Path, str]:
    """The Codex home the runner user actually uses (dynamic, never hardcoded)."""
    env = str(os.environ.get("CODEX_HOME") or "").strip()
    if env:
        return Path(env).expanduser(), "CODEX_HOME"
    profile = str(os.environ.get("USERPROFILE") or "").strip()
    if profile:
        candidate = Path(profile).expanduser() / ".codex"
        if candidate.is_dir():
            return candidate, "USERPROFILE"
    home = str(os.environ.get("HOME") or "").strip()
    if home:
        candidate = Path(home).expanduser() / ".codex"
        if candidate.is_dir():
            return candidate, "HOME"
    return Path.home() / ".codex", "home_default"


def codex_version(codex: Path, timeout: int = VERSION_PROBE_TIMEOUT_SECONDS) -> str | None:
    try:
        cp = subprocess.run(
            [*driver_prefix(codex, codex_driver(codex)), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except Exception:
        return None
    if cp.returncode != 0:
        return None
    # Native Codex may print a benign cleanup/sandbox warning to stderr
    # before its --version banner. stderr is intentionally merged with stdout;
    # treating only line 1 as the version made StoryOS reject an otherwise
    # healthy CLI and blocked the independent Concept Ambition critic.
    # Accept exactly one full-line version banner; never parse a version
    # embedded inside arbitrary output or a conflicting pair of banners.
    banners = {
        line.strip() for line in (cp.stdout or "").splitlines()
        if re.fullmatch(
            r"(?:codex-cli|codex)\s+\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?",
            line.strip(),
        )
    }
    return next(iter(banners)) if len(banners) == 1 else None


# ---------------------------------------------------------------------------
# Task schema
# ---------------------------------------------------------------------------
@dataclass
class CodexTask:
    argv: list[str]
    task_type: str = "generic_codex"
    working_directory: str | None = None
    stdin_text: str | None = None
    stdin_base64: str | None = None
    timeout_seconds: int | None = None
    env: dict = field(default_factory=dict)
    codex_home_mode: str = "inherit"
    client: dict = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def stdin_bytes(self) -> bytes:
        if self.stdin_base64 is not None:
            return base64.b64decode(self.stdin_base64)
        if self.stdin_text is not None:
            return self.stdin_text.encode("utf-8")
        return b""

    def to_payload(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "request_id": self.request_id,
            "task_type": self.task_type,
            "argv": list(self.argv),
            "working_directory": self.working_directory,
            "stdin_base64": (
                self.stdin_base64
                if self.stdin_base64 is not None
                else base64.b64encode(self.stdin_text.encode("utf-8")).decode("ascii")
                if self.stdin_text is not None
                else None
            ),
            "timeout_seconds": self.timeout_seconds,
            "env": dict(self.env),
            "codex_home_mode": self.codex_home_mode,
            "client": dict(self.client),
        }

    @classmethod
    def from_payload(cls, payload: dict) -> "CodexTask":
        if not isinstance(payload, dict):
            raise CodexUserRunnerRejected("CODEX_USER_RUNNER_TASK_REJECTED", "request body must be a JSON object")
        version = payload.get("schema_version", SCHEMA_VERSION)
        if int(version) != SCHEMA_VERSION:
            raise CodexUserRunnerRejected(
                "CODEX_USER_RUNNER_TASK_REJECTED", f"unsupported task schema_version={version}"
            )
        task = cls(
            argv=payload.get("argv") or [],
            task_type=str(payload.get("task_type") or "generic_codex"),
            working_directory=payload.get("working_directory"),
            stdin_text=payload.get("stdin_text"),
            stdin_base64=payload.get("stdin_base64"),
            timeout_seconds=payload.get("timeout_seconds"),
            env=payload.get("env") or {},
            codex_home_mode=str(payload.get("codex_home_mode") or "inherit"),
            client=payload.get("client") or {},
        )
        if payload.get("request_id"):
            task.request_id = str(payload["request_id"])
        return task


def split_env(env: dict | None) -> tuple[dict, str | None]:
    """Filter request env; CODEX_HOME is handled by the home policy instead."""
    allowed: dict = {}
    codex_home_value: str | None = None
    for raw_key, raw_value in dict(env or {}).items():
        key = str(raw_key)
        if key == "CODEX_HOME":
            codex_home_value = str(raw_value)
            continue
        if key in ENV_ALLOWED_EXACT or key.startswith(ENV_ALLOWED_PREFIX):
            allowed[key] = str(raw_value)
    return allowed, codex_home_value


def build_task(
    argv: list[str],
    *,
    stdin_bytes: bytes | str | None = None,
    timeout: float | int | None = None,
    env: dict | None = None,
    cwd: str | Path | None = None,
    task_type: str = "generic_codex",
    codex_home_mode: str = "inherit",
    request_id: str | None = None,
) -> CodexTask:
    _, _ = split_argv(argv)
    if task_type not in ALLOWED_TASK_TYPES:
        raise CodexUserRunnerRejected(
            "CODEX_USER_RUNNER_TASK_REJECTED", f"unknown task_type={task_type!r}"
        )
    if codex_home_mode not in CODEX_HOME_MODES:
        raise CodexUserRunnerRejected(
            "CODEX_USER_RUNNER_TASK_REJECTED", f"unknown codex_home_mode={codex_home_mode!r}"
        )
    data: bytes | None
    if stdin_bytes is None:
        data = None
    elif isinstance(stdin_bytes, bytes):
        data = stdin_bytes
    else:
        data = str(stdin_bytes).encode("utf-8")
    seconds = None
    if timeout is not None:
        try:
            seconds = int(float(timeout))
        except (TypeError, ValueError) as exc:
            raise CodexUserRunnerRejected(
                "CODEX_USER_RUNNER_TASK_REJECTED", f"invalid timeout={timeout!r}"
            ) from exc
        if seconds <= 0:
            seconds = None
    task = CodexTask(
        argv=[str(x) for x in argv],
        task_type=task_type,
        working_directory=str(Path(cwd).resolve()) if cwd is not None else str(ROOT),
        stdin_base64=base64.b64encode(data).decode("ascii") if data is not None else None,
        timeout_seconds=seconds,
        env=dict(env or {}),
        codex_home_mode=codex_home_mode,
        client={"user": current_identity(), "pid": os.getpid(), "transport": transport_name()},
    )
    if request_id:
        task.request_id = str(request_id)
    return task


# ---------------------------------------------------------------------------
# Runner side
# ---------------------------------------------------------------------------
def runner_input_root() -> Path:
    """Runner-user-owned staging root for Codex `-i` attachments.

    The caller may be SYSTEM while Codex and its vision sidecar run as the
    interactive user. Copy attachments into the runner user's own profile tree
    before launching Codex so the sidecar never dereferences a SYSTEM-only or
    sandbox-incompatible path.
    """
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if os.name == "nt" and local_app_data:
        root = Path(local_app_data) / "StoryOS" / RUNNER_INPUT_DIR_NAME
    else:
        root = Path.home() / ".storyos" / RUNNER_INPUT_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _stage_runner_input_images(args: list[str], workdir: Path, request_id: str) -> tuple[list[str], Path | None, list[dict]]:
    """Mirror `-i/--image` files into runner-user storage and rewrite argv."""
    rewritten = list(args)
    indexes: list[int] = []
    i = 0
    while i < len(rewritten):
        if rewritten[i] in {"-i", "--image"} and i + 1 < len(rewritten):
            indexes.append(i + 1)
            i += 2
            continue
        i += 1
    if not indexes:
        return rewritten, None, []
    staging = Path(tempfile.mkdtemp(prefix=f"{request_id[:12]}-", dir=str(runner_input_root())))
    evidence: list[dict] = []
    try:
        for n, arg_index in enumerate(indexes, start=1):
            raw = Path(str(rewritten[arg_index]))
            source = raw.resolve() if raw.is_absolute() else (workdir / raw).resolve()
            if not source.is_file():
                raise CodexUserRunnerWorkspaceUnavailable(
                    "CODEX_USER_RUNNER_WORKSPACE_UNAVAILABLE",
                    f"Codex input image missing or unreadable: {source}",
                )
            suffix = source.suffix.lower() or ".bin"
            target = staging / f"image-{n:03d}{suffix}"
            shutil.copy2(source, target)
            rewritten[arg_index] = str(target)
            evidence.append({
                "source": str(source),
                "staged": str(target),
                "bytes": target.stat().st_size,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            })
        return rewritten, staging, evidence
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def isolated_home_root() -> Path:
    """Private non-TEMP root for per-task Codex homes owned by the runner user.

    Codex creates executable arg0/PATH helpers below CODEX_HOME. Release builds
    reject a CODEX_HOME below the OS temp root, and recent Windows sandbox/ACL
    behavior can also make ``~/.codex/tmp`` unsuitable for fresh helpers. Keep
    Story OS task homes in a separate user-profile application-data directory:
    outside TEMP, outside the repository, and outside the real ``~/.codex``
    credential/config tree.
    """
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if os.name == "nt" and local_app_data:
        root = Path(local_app_data) / "StoryOS" / RUNNER_TASK_HOME_NAME
    else:
        root = Path.home() / ".storyos" / RUNNER_TASK_HOME_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _seed_isolated_home(target: Path) -> dict:
    """Create a throwaway CODEX_HOME seeded only with what the CLI needs to sign in.

    This keeps the runner's credential inside the interactive user context while
    still isolating per-task ``generated_images`` output.
    """
    source, source_name = codex_home()
    target.mkdir(parents=True, exist_ok=True)
    seeded = []
    for name in ("auth.json", "config.toml"):
        src = source / name
        if src.is_file():
            shutil.copy2(src, target / name)
            seeded.append(name)
    return {"source": source_name, "seeded": seeded, "target": str(target)}


def exported_artifacts_dir(workdir: str | Path) -> Path:
    """Where the runner mirrors provider artifacts for the caller."""
    return Path(workdir) / EXPORT_DIR_NAME


def _thread_ids_from_output(output: bytes) -> list[str]:
    """Extract Codex thread ids from JSONL output without trusting prose."""
    found: list[str] = []
    for raw in (output or b"").decode("utf-8", "replace").splitlines():
        try:
            row = json.loads(raw)
        except Exception:
            continue
        thread_id = str(row.get("thread_id") or "").strip() if isinstance(row, dict) else ""
        if row.get("type") == "thread.started" and thread_id and thread_id not in found:
            found.append(thread_id)
    return found



def _archive_direct_thread_image(request_id: str, output: bytes, child_env: dict) -> dict:
    """Capture *existing* Codex generated_images while its ephemeral home exists.

    A direct subprocess previously persisted rc=0/JSONL but discarded its
    thread-owned generated_images with the disposable CODEX_HOME. This bounded
    capture is performed after process exit and before caller workspace cleanup.
    It never invokes a provider, infers an artifact from mtime, or accepts a
    sibling thread. Missing provenance leaves the paid outcome UNKNOWN.
    """
    try:
        from PIL import Image
        rid = str(request_id or "")
        if not re.fullmatch(r"[0-9a-f]{32}", rid):
            return {}
        events = []
        for line in output.decode("utf-8", "replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        threads = [str(e.get("thread_id") or "") for e in events
                   if e.get("type") == "thread.started"]
        if (len(threads) != 1
                or re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", threads[0]) is None
                or sum(e.get("type") == "turn.completed" for e in events) != 1
                or any(e.get("type") == "turn.failed" for e in events)):
            return {}
        home = Path(str(child_env.get("CODEX_HOME") or
                        (Path.home() / ".codex"))).resolve()
        source_root = (home / "generated_images").resolve()
        thread_dir = source_root / threads[0]
        if (not thread_dir.is_dir() or thread_dir.is_symlink()
                or not thread_dir.resolve().is_relative_to(source_root)):
            return {}
        children = list(thread_dir.iterdir())
        if (len(children) != 1 or not children[0].is_file()
                or children[0].is_symlink()
                or children[0].suffix.lower() != ".png"):
            return {}
        src = children[0]
        with Image.open(src) as im:
            im.verify()
        original_sha = hashlib.sha256(src.read_bytes()).hexdigest()
        target = (task_result_path(rid).parent.parent / "image-artifacts" /
                  rid / threads[0] / src.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, pending = tempfile.mkstemp(prefix=".capture-", suffix=".pending",
                                       dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as stream, src.open("rb") as source:
                shutil.copyfileobj(source, stream)
                stream.flush()
                os.fsync(stream.fileno())
            if hashlib.sha256(Path(pending).read_bytes()).hexdigest() != original_sha:
                return {}
            os.link(pending, target)  # NO-REPLACE: preserve earlier evidence
        finally:
            Path(pending).unlink(missing_ok=True)
        return {
            "thread_ids": threads,
            "generated_artifacts": [threads[0] + "/" + src.name],
            "direct_artifact_archive": "DIRECT_THREAD_SCOPED_CAPTURE",
            "direct_artifact_sha256": original_sha,
            "direct_artifact_bytes": target.stat().st_size,
        }
    except (OSError, ValueError, TypeError, RuntimeError):
        return {}


def _settle_generated_artifacts(
    home: Path,
    workdir: Path,
    *,
    thread_ids: list[str],
    timeout_seconds: float = IMAGE_ARTIFACT_SETTLE_SECONDS,
    poll_seconds: float = IMAGE_ARTIFACT_SETTLE_POLL_SECONDS,
    sleep_fn=time.sleep,
    monotonic_fn=time.monotonic,
) -> tuple[list[str], dict]:
    """Wait briefly for already-generated thread artifacts to reach disk.

    This never invokes Codex or image_generation. It only re-reads the current
    thread's generated_images directory after the Codex process has exited.
    """
    started = monotonic_fn()
    exported = _export_generated_artifacts(home, workdir, thread_ids=thread_ids)
    polls = 1
    if exported or timeout_seconds <= 0:
        return exported, {
            "used": False,
            "polls": polls,
            "waited_seconds": 0.0,
            "timeout_seconds": float(timeout_seconds),
        }
    deadline = started + float(timeout_seconds)
    while monotonic_fn() < deadline:
        sleep_fn(float(poll_seconds))
        polls += 1
        exported = _export_generated_artifacts(home, workdir, thread_ids=thread_ids)
        if exported:
            break
    waited = max(0.0, monotonic_fn() - started)
    return exported, {
        "used": True,
        "polls": polls,
        "waited_seconds": round(waited, 3),
        "timeout_seconds": float(timeout_seconds),
    }


def _export_generated_artifacts(home: Path, workdir: Path, *, thread_ids: list[str] | None = None) -> list[str]:
    """Mirror only this task's provider artifacts into the caller workdir.

    When ``thread_ids`` is supplied, never scan/copy sibling Codex threads. This
    is what lets concurrent image workers share the authenticated real
    CODEX_HOME without stealing each other's generated images.
    """
    source = home / "generated_images"
    if not source.is_dir():
        return []
    roots = [source / tid for tid in thread_ids or []] if thread_ids is not None else [source]
    target = exported_artifacts_dir(workdir)
    exported: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                relative = path.relative_to(source)
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
            except Exception:
                continue
            exported.append(str(relative).replace("\\", "/"))
    return exported


@dataclass
class ExecResult:
    returncode: int
    output: bytes
    remote: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.output.decode("utf-8", "replace")


def _prepare_strict_codex_task(task: CodexTask) -> tuple[CodexTask, dict | None]:
    """Enforce dual-only transport for low-level task callers as well.

    Existing agents also invoke execute_task / execute_codex directly,
    bypassing run_codex. Never mutate their task or issue an automatic fallback.
    """
    source = {**os.environ, **dict(task.env or {})}
    # A task payload cannot opt out when the host mandates strict transport.
    host_policy = str(os.environ.get("STORY_OS_MODEL_TRANSPORT_POLICY") or "").strip().upper()
    task_policy = str(source.get("STORY_OS_MODEL_TRANSPORT_POLICY") or "").strip().upper()
    if host_policy != "DUAL_ONLY" and task_policy != "DUAL_ONLY":
        return task, None
    source["STORY_OS_MODEL_TRANSPORT_POLICY"] = "DUAL_ONLY"
    route = resolve_provider_transport(task.argv, env=source, task_type=task.task_type)
    if route is None:
        return task, None
    if route.get("transport_route") != "native_codex":
        raise CodexUserRunnerRejected("MODEL_TRANSPORT_FORBIDDEN", "strict task must use native Codex")
    return dataclasses.replace(
        task, argv=_insert_codex_args(list(task.argv), route.get("provider_args") or [])
    ), route


def _wininet_native_proxy() -> str | None:
    """Read only the interactive user's enabled local Windows HTTP proxy.

    This configures native Codex network I/O, not a model/provider override.
    Never forward user credentials or accept remote/untrusted proxy endpoints.
    """
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
            raw = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "").strip()
        if not enabled or not raw:
            return None
        if "=" in raw:
            parts = dict(
                part.split("=", 1) for part in raw.split(";")
                if "=" in part
            )
            raw = str(parts.get("https") or parts.get("http") or "").strip()
        if raw.lower().startswith("http://"):
            raw = raw[7:]
        matched = re.fullmatch(r"(?:127\.0\.0\.1|localhost):(\d{2,5})", raw, re.I)
        if not matched or not 1 <= int(matched.group(1)) <= 65535:
            return None
        return "http://" + raw
    except (OSError, ValueError, TypeError):
        return None


def _apply_wininet_proxy_to_codex_env(child_env: dict[str, str]) -> None:
    """Use user-selected local proxy only when Codex has no explicit proxy."""
    if any(child_env.get(key) for key in (
        "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
        "ALL_PROXY", "all_proxy",
    )):
        return
    proxy = _wininet_native_proxy()
    if proxy is not None:
        child_env["HTTPS_PROXY"] = proxy
        child_env["HTTP_PROXY"] = proxy


def execute_task(task: CodexTask) -> ExecResult:
    """Run one declarative Codex task in this (runner) process."""
    task, strict_route = _prepare_strict_codex_task(task)
    if is_non_interactive():
        raise CodexUserRunnerWrongIdentity(
            "CODEX_USER_RUNNER_WRONG_IDENTITY",
            f"runner must not execute as {current_identity()}; user-mode Codex requires an interactive user",
        )
    expected = expected_user()
    if expected and not user_matches(expected, current_identity()):
        raise CodexUserRunnerWrongIdentity(
            "CODEX_USER_RUNNER_WRONG_IDENTITY",
            f"runner is {current_identity()}, expected {expected}",
        )
    caller_codex, caller_args = split_argv(task.argv)
    codex_path, resolution = resolve_codex(caller_codex)
    driver = codex_driver(codex_path)
    workdir = Path(str(task.working_directory or ROOT))
    codex_args, input_staging, input_images = _stage_runner_input_images(caller_args, workdir, task.request_id)
    if not workdir.is_dir():
        raise CodexUserRunnerWorkspaceUnavailable(
            "CODEX_USER_RUNNER_WORKSPACE_UNAVAILABLE", f"working directory missing: {workdir}"
        )
    if not os.access(str(workdir), os.R_OK | os.W_OK | os.X_OK):
        raise CodexUserRunnerWorkspaceUnavailable(
            "CODEX_USER_RUNNER_WORKSPACE_UNAVAILABLE",
            f"runner user {current_identity()} cannot use working directory {workdir}",
        )
    allowed_env, _ignored_home = split_env(task.env)
    child_env = os.environ.copy()
    child_env.setdefault("PYTHONUTF8", "1")
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    child_env.update(allowed_env)
    _apply_wininet_proxy_to_codex_env(child_env)
    home_evidence = {"mode": task.codex_home_mode}
    isolated_home: Path | None = None
    active_home: Path | None = None
    if task.codex_home_mode == "isolated":
        # The throwaway home is seeded with a copy of the interactive user's
        # credential, so it must never be created inside the repository: the
        # repository ACL admits SYSTEM and other local identities.
        isolated_home = Path(tempfile.mkdtemp(prefix="codex-home-", dir=str(isolated_home_root())))
        home_evidence.update(_seed_isolated_home(isolated_home))
        home_evidence["root"] = "runner_user_profile_appdata"
        child_env["CODEX_HOME"] = str(isolated_home)
        active_home = isolated_home
    else:
        resolved_home, source_name = codex_home()
        active_home = resolved_home
        home_evidence.update({"path": str(resolved_home), "source": source_name,
                              "accessible": os.access(str(resolved_home), os.R_OK | os.W_OK)})
        child_env.setdefault("CODEX_HOME", str(resolved_home))
    cap = max_timeout_seconds()
    timeout = min(int(task.timeout_seconds
                      or _role_seconds(DEFAULT_TASK_TIMEOUT_ROLE, DEFAULT_TASK_TIMEOUT_SECONDS)),
                  cap)
    cmd = [*driver_prefix(codex_path, driver), *codex_args]
    started = time.monotonic()
    timed_out = False
    try:
        try:
            cp = subprocess.run(
                cmd,
                input=task.stdin_bytes(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(workdir),
                env=child_env,
                timeout=timeout,
                check=False,
            )
            rc = cp.returncode
            output = cp.stdout or b""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            rc = 124
            output = exc.output or b""
    finally:
        if input_staging is not None:
            shutil.rmtree(input_staging, ignore_errors=True)
    elapsed = round(time.monotonic() - started, 2)
    evidence = {
        "request_id": task.request_id,
        "task_type": task.task_type,
        "user": current_identity(),
        "codex_executable": str(codex_path),
        "codex_resolution": resolution,
        "driver": driver,
        "working_directory": str(workdir),
        "codex_home": home_evidence,
        "timeout_seconds": timeout,
        "returncode": rc,
        "timed_out": timed_out,
        "elapsed_seconds": elapsed,
        "stdin_sha256": hashlib.sha256(task.stdin_bytes()).hexdigest(),
        "stdin_bytes": len(task.stdin_bytes()),
        "output_bytes": len(output),
        "client": task.client,
        "input_images": input_images,
    }
    if strict_route:
        evidence.update({key: strict_route[key] for key in PROVIDER_EVIDENCE_KEYS
                         if key in strict_route})
    if isolated_home is not None:
        evidence["generated_artifacts"] = _export_generated_artifacts(isolated_home, workdir)
        try:
            shutil.rmtree(isolated_home, ignore_errors=True)
        except Exception:
            pass
    elif task.task_type == "image" and active_home is not None:
        thread_ids = _thread_ids_from_output(output)
        evidence["thread_ids"] = thread_ids
        if thread_ids:
            exported, settle = _settle_generated_artifacts(
                active_home, workdir, thread_ids=thread_ids)
        else:
            exported, settle = [], {
                "used": False, "polls": 0, "waited_seconds": 0.0,
                "timeout_seconds": IMAGE_ARTIFACT_SETTLE_SECONDS,
            }
        evidence["generated_artifacts"] = exported
        evidence["artifact_settle"] = settle
    return ExecResult(returncode=124 if timed_out else rc, output=output, remote=evidence)


def _role_seconds(role: str, fallback: int) -> int:
    """Role default from config/storyos.yaml:timeout_policy, else the fallback.

    The bridge never invents a timeout policy: callers resolve their own role
    before calling, and this only supplies a last-resort default.
    """
    try:
        return int(runtime_timeout_policy.seconds(role))
    except Exception:
        return int(fallback)


def max_timeout_seconds() -> int:
    raw = str(os.environ.get(MAX_TIMEOUT_ENV) or "").strip()
    if raw:
        try:
            value = int(float(raw))
            if value > 0:
                return value
        except ValueError:
            pass
    return _role_seconds(DEFAULT_MAX_TIMEOUT_ROLE, DEFAULT_MAX_TIMEOUT_SECONDS)


class RunnerState:
    def __init__(self, host: str, port: int, token: str) -> None:
        self.host = host
        self.port = port
        self.token = token
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.lock = threading.Lock()
        self.counters = {"tasks": 0, "failed": 0, "timeouts": 0, "rejected": 0}
        # request_id -> started_at for tasks this runner is executing right now.
        # A restarted Driver asks this before resubmitting: a request that is
        # still in flight must be waited for, never started a second time.
        self.inflight: dict[str, str] = {}
        self.log_path = runtime_dir() / LOG_NAME
        try:
            codex_path, resolution = resolve_codex()
        except CodexUserRunnerError:
            codex_path, resolution = None, "unresolved"
        self.codex_path = codex_path
        self.codex_resolution = resolution
        self.version = codex_version(codex_path) if codex_path else None
        self.home, self.home_source = codex_home()

    def health(self) -> dict:
        identity = current_identity()
        return {
            "status": "ok" if (self.codex_path and not is_non_interactive(identity)) else "degraded",
            "schema_version": SCHEMA_VERSION,
            "protocol_revision": RUNNER_PROTOCOL_REVISION,
            "transport": "user_runner",
            "user": identity,
            "interactive_user": not is_non_interactive(identity),
            "codex_available": bool(self.codex_path),
            "codex_version": self.version,
            "codex_executable": str(self.codex_path) if self.codex_path else None,
            "codex_resolution": self.codex_resolution,
            "codex_home": str(self.home),
            "codex_home_source": self.home_source,
            "codex_home_accessible": os.access(str(self.home), os.R_OK | os.W_OK),
            # Presence only: health/preflight may prove an authentication context
            # exists without returning or reading credential contents.
            "codex_auth_present": (self.home / "auth.json").is_file(),
            "codex_config_present": (self.home / "config.toml").is_file(),
            "host": self.host,
            "port": self.port,
            "pid": os.getpid(),
            "started_at": self.started_at,
            "max_timeout_seconds": max_timeout_seconds(),
            "allowed_task_types": sorted(ALLOWED_TASK_TYPES),
            "counters": dict(self.counters),
            "inflight_request_ids": sorted(self.inflight),
            "features": [
                "durable_task_results", "inflight_request_ids",
                "append_only_task_results", "atomic_task_result_publish",
            ],
            "secrets_persisted": False,
        }

    def begin_task(self, request_id: str) -> None:
        try:
            previous = task_result_path(request_id)
        except ValueError as exc:
            raise CodexUserRunnerRejected(
                "CODEX_USER_RUNNER_TASK_REJECTED", "invalid request identity"
            ) from exc
        with self.lock:
            if request_id in self.inflight or previous.is_file():
                raise CodexUserRunnerRejected(
                    "CODEX_USER_RUNNER_DUPLICATE_REQUEST_ID",
                    "request is already executing or has durable evidence",
                )
            self.inflight[str(request_id)] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    def end_task(self, request_id: str) -> None:
        with self.lock:
            self.inflight.pop(str(request_id), None)

    def log(self, row: dict) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def persist_result(self, result: ExecResult) -> None:
        """Atomically publish an immutable result; never prune Authority evidence.

        The old 200-file cap silently deleted historical Codex execution
        receipts exactly when production needed them for UNKNOWN recovery.
        Result publication must complete before the HTTP success response.
        A publication error remains ambiguous, never a model SUCCESS receipt.
        """
        request_id = str((result.remote or {}).get("request_id") or "").strip()
        try:
            path = task_result_path(request_id)
        except ValueError as exc:
            raise CodexUserRunnerRejected(
                "CODEX_USER_RUNNER_TASK_REJECTED", "invalid result request identity"
            ) from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        output = result.output or b""
        payload = {
            "schema_version": 1,
            "request_id": request_id,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "returncode": int(result.returncode),
            "output_sha256": hashlib.sha256(output).hexdigest(),
            "output_bytes": len(output),
            "output_base64": base64.b64encode(output).decode("ascii"),
            "evidence": result.remote or {},
        }
        fd, temporary = tempfile.mkstemp(
            prefix=f".{request_id}.", suffix=".pending", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, path)  # atomic NO-REPLACE
        except FileExistsError as exc:
            raise CodexUserRunnerRejected(
                "CODEX_USER_RUNNER_DUPLICATE_REQUEST_ID",
                "existing result must not be overwritten",
            ) from exc
        except OSError as exc:
            raise CodexUserRunnerError(
                "CODEX_USER_RUNNER_DURABLE_RESULT_WRITE_FAILED",
                "result persistence failed; generation outcome must be reconciled",
            ) from exc
        finally:
            Path(temporary).unlink(missing_ok=True)


class _Handler(BaseHTTPRequestHandler):
    server_version = "StoryOSCodexUserRunner/1"
    state: RunnerState

    def log_message(self, fmt, *args):  # noqa: A003 - stdlib signature
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        supplied = str(self.headers.get("X-StoryOS-Codex-Runner-Token") or "")
        return bool(supplied) and secrets.compare_digest(supplied, self.state.token)

    def do_GET(self):  # noqa: N802 - stdlib signature
        if self.path.rstrip("/") != "/v1/health":
            self._send(404, {"ok": False, "code": "CODEX_USER_RUNNER_TASK_REJECTED", "detail": "unknown path"})
            return
        if not self._authorized():
            self.state.counters["rejected"] += 1
            self._send(401, {"ok": False, "code": "CODEX_USER_RUNNER_AUTH_FAILED", "detail": "invalid token"})
            return
        self._send(200, self.state.health())

    def do_POST(self):  # noqa: N802 - stdlib signature
        if self.path.rstrip("/") != "/v1/codex/exec":
            self._send(404, {"ok": False, "code": "CODEX_USER_RUNNER_TASK_REJECTED", "detail": "unknown path"})
            return
        if not self._authorized():
            with self.state.lock:
                self.state.counters["rejected"] += 1
            self.state.log({"event": "auth_failed", "client": self.client_address[0]})
            self._send(401, {"ok": False, "code": "CODEX_USER_RUNNER_AUTH_FAILED", "detail": "invalid token"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._send(400, {"ok": False, "code": "CODEX_USER_RUNNER_TASK_REJECTED", "detail": "bad content length"})
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
            task = CodexTask.from_payload(payload)
            with self.state.lock:
                self.state.counters["tasks"] += 1
            # Marked before execute_task so a caller that dies mid-task leaves a
            # request the next Driver can find still in flight.
            self.state.begin_task(task.request_id)
            try:
                result = execute_task(task)
                # Retain in-flight ownership through durable publication.
                # Never reply SUCCESS before the result is readable on disk.
                self.state.persist_result(result)
            finally:
                self.state.end_task(task.request_id)
        except CodexUserRunnerTimeout as exc:
            with self.state.lock:
                self.state.counters["timeouts"] += 1
            self.state.log({"event": "timeout", "detail": str(exc)})
            self._send(504, {"ok": False, "code": exc.code, "detail": exc.detail})
            return
        except CodexUserRunnerError as exc:
            with self.state.lock:
                self.state.counters["failed"] += 1
            self.state.log({"event": "error", "code": exc.code, "detail": exc.detail})
            self._send(422 if exc.code != "CODEX_USER_RUNNER_AUTH_FAILED" else 401,
                       {"ok": False, "code": exc.code, "detail": exc.detail})
            return
        except Exception as exc:  # never leak a traceback as an opaque os error
            with self.state.lock:
                self.state.counters["failed"] += 1
            self.state.log({"event": "error", "code": "CODEX_EXEC_FAILED", "detail": repr(exc)})
            self._send(500, {"ok": False, "code": "CODEX_EXEC_FAILED", "detail": repr(exc)})
            return

        self.state.log({"event": "task", **result.remote})
        self._send(200, {
            "ok": True,
            "returncode": result.returncode,
            "timed_out": result.remote.get("timed_out", False),
            "output_base64": base64.b64encode(result.output).decode("ascii"),
            "evidence": result.remote,
        })


def write_endpoint(host: str, port: int, token: str) -> dict:
    data = {
        "schema_version": SCHEMA_VERSION,
        "host": host,
        "port": int(port),
        "token": token,
        "pid": os.getpid(),
        "user": current_identity(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": sys.executable,
        "codex_user_runner": str(Path(__file__).resolve()),
    }
    _write_json(endpoint_path(), data)
    token_path().write_text(token + "\n", encoding="utf-8")
    _harden_token_acl()
    return data


def _harden_token_acl() -> None:
    """Best-effort local restriction: owner + SYSTEM + Administrators only.

    The token is a local nonce, never a Codex credential. Windows may refuse a
    non-elevated ACL edit, so failure is non-fatal and the token check stays the
    enforced boundary.
    """
    if os.name != "nt":
        try:
            os.chmod(token_path(), 0o600)
        except OSError:
            pass
        return
    who = str(os.environ.get("USERNAME") or "").strip()
    domain = str(os.environ.get("USERDOMAIN") or "").strip()
    principal = f"{domain}\\{who}" if domain and who else who
    if not principal:
        return
    for args in (
        ["icacls", str(token_path()), "/inheritance:r"],
        ["icacls", str(token_path()), "/grant:r", f"{principal}:(F)"],
        ["icacls", str(token_path()), "/grant", "*S-1-5-18:(R)", "*S-1-5-32-544:(R)"],
    ):
        try:
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=ACL_TIMEOUT_SECONDS, check=False)
        except Exception:
            return


def remove_endpoint(pid: int | None = None) -> None:
    path = endpoint_path()
    if not path.is_file():
        return
    try:
        current = _read_json(path)
    except Exception:
        return
    if pid is not None and int(current.get("pid") or 0) != int(pid):
        return
    try:
        path.unlink()
    except OSError:
        pass


def serve(host: str = "127.0.0.1", port: int = 0, token: str | None = None) -> int:
    # The user-mode bridge does not access MySQL itself. Mark the inherited
    # connection-pool role through the same environment fallback used by
    # mysql_connection_pool.process_role() instead of importing StoryOS's
    # top-level `platform` package here. In an interactive Python launched by
    # PowerShell, stdlib `platform` may already be present in sys.modules; the
    # late package import would then fail before the bridge can publish its
    # loopback endpoint.
    os.environ.setdefault("STORYOS_MYSQL_POOL_ROLE", "runner")
    identity = current_identity()
    if is_non_interactive(identity):
        print(
            "CODEX_USER_RUNNER_WRONG_IDENTITY: refusing to start as "
            f"{identity}; run this in the interactive user session",
            file=sys.stderr,
        )
        return 2
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print(f"CODEX_USER_RUNNER_TASK_REJECTED: loopback binding required, got {host}", file=sys.stderr)
        return 2
    # A direct serve must not overwrite a live/foreign/unverified runner pointer.
    # Only the interactive reconciler may retire a confirmed-dead endpoint.
    if endpoint_path().is_file():
        print("CODEX_USER_RUNNER_ENDPOINT_NOT_RECONCILED", file=sys.stderr)
        return 4
    tmp_root().mkdir(parents=True, exist_ok=True)
    resolved_token = token or secrets.token_urlsafe(32)
    httpd = ThreadingHTTPServer((host, int(port)), _Handler)
    httpd.daemon_threads = True
    actual_port = httpd.server_address[1]
    state = RunnerState(host, actual_port, resolved_token)
    _Handler.state = state
    endpoint = write_endpoint(host, actual_port, resolved_token)
    print(json.dumps({
        "status": "listening",
        "host": host,
        "port": actual_port,
        "user": identity,
        "codex_executable": str(state.codex_path) if state.codex_path else None,
        "codex_version": state.version,
        "codex_home": str(state.home),
        "endpoint": str(endpoint_path()),
        "token_file": str(token_path()),
    }, ensure_ascii=False))
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        remove_endpoint(os.getpid())
        httpd.server_close()
    return 0


# ---------------------------------------------------------------------------
# Client side
# ---------------------------------------------------------------------------
def _post(url: str, token: str, path: str, payload: dict | None, timeout: float) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url.rstrip("/") + path,
        data=data,
        method="POST" if data is not None else "GET",
        headers={"X-StoryOS-Codex-Runner-Token": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {"ok": False, "code": "CODEX_EXEC_FAILED", "detail": f"HTTP {exc.code}"}
    except urllib.error.URLError as exc:
        raise CodexUserRunnerUnavailable(
            "CODEX_USER_RUNNER_UNAVAILABLE",
            f"cannot reach the Codex user runner at {url}: {exc.reason}",
        ) from exc
    except (socket.timeout, TimeoutError) as exc:
        raise CodexUserRunnerTimeout([], timeout, f"local bridge call exceeded {timeout}s") from exc


def runner_health(*, timeout: float = HEALTH_TIMEOUT_SECONDS) -> dict:
    creds = client_credentials()
    status, body = _post(creds["url"], creds["token"], "/v1/health", None, timeout)
    if status == 401:
        raise CodexUserRunnerAuthFailed("CODEX_USER_RUNNER_AUTH_FAILED", "runner rejected the local token")
    if status != 200 or not body.get("user"):
        raise CodexUserRunnerUnavailable(
            "CODEX_USER_RUNNER_UNAVAILABLE", f"runner health returned HTTP {status}: {body}"
        )
    if is_non_interactive(body.get("user")):
        raise CodexUserRunnerWrongIdentity(
            "CODEX_USER_RUNNER_WRONG_IDENTITY", f"runner is running as {body.get('user')}"
        )
    return body


def execute_model_task(task: CodexTask) -> ExecResult:
    """Canonical native-only producer task through direct/interactive bridge.

    This is a feature-branch cutover: producer tasks cannot opt into legacy
    provider fallback. No modification to caller-owned task identity or stdin.
    """
    native_env = dict(task.env or {})
    native_env["STORY_OS_MODEL_TRANSPORT_POLICY"] = "DUAL_ONLY"
    native_task = dataclasses.replace(task, env=native_env)
    return execute_codex(native_task) if bridge_required() else execute_task(native_task)


def execute_codex(task: CodexTask, *, timeout: float | None = None) -> ExecResult:
    """Send one task to the interactive-user runner."""
    task, strict_route = _prepare_strict_codex_task(task)
    creds = client_credentials()
    endpoint = creds.get("endpoint") or read_endpoint(required=False)
    endpoint_user = endpoint.get("user")
    if endpoint_user and is_non_interactive(endpoint_user):
        raise CodexUserRunnerWrongIdentity(
            "CODEX_USER_RUNNER_WRONG_IDENTITY", f"runner endpoint is owned by {endpoint_user}"
        )
    expected = expected_user()
    if expected and endpoint_user and not user_matches(expected, endpoint_user):
        raise CodexUserRunnerWrongIdentity(
            "CODEX_USER_RUNNER_WRONG_IDENTITY", f"runner is {endpoint_user}, expected {expected}"
        )
    effective = int(task.timeout_seconds
                    or _role_seconds(DEFAULT_TASK_TIMEOUT_ROLE, DEFAULT_TASK_TIMEOUT_SECONDS))
    http_timeout = float(timeout if timeout is not None else effective + HTTP_MARGIN_SECONDS)
    status, body = _post(creds["url"], creds["token"], "/v1/codex/exec", task.to_payload(), http_timeout)
    if status == 401:
        raise CodexUserRunnerAuthFailed("CODEX_USER_RUNNER_AUTH_FAILED", "runner rejected the local token")
    if status == 504:
        exc = CodexUserRunnerTimeout(task.argv, effective, str(body.get("detail") or ""))
        exc.remote = {**exc.remote, **dict(body.get("evidence") or {}), "timed_out": True, "returncode": 124}
        raise exc
    if status != 200 or not body.get("ok"):
        code = str(body.get("code") or "CODEX_EXEC_FAILED")
        detail = str(body.get("detail") or f"HTTP {status}")
        raise CodexUserRunnerError(code, detail)
    if body.get("timed_out"):
        exc = CodexUserRunnerTimeout(task.argv, effective, str(body.get("detail") or ""))
        exc.remote = {**exc.remote, **dict(body.get("evidence") or {}), "timed_out": True, "returncode": 124}
        raise exc
    output = base64.b64decode(body.get("output_base64") or "")
    evidence = dict(body.get("evidence") or {})
    if strict_route:
        evidence.update({key: strict_route[key] for key in PROVIDER_EVIDENCE_KEYS
                         if key in strict_route})
    return ExecResult(returncode=int(body.get("returncode") or 0), output=output, remote=evidence)


# ---------------------------------------------------------------------------
# subprocess.run compatible facade used by every Story OS codex call site
# ---------------------------------------------------------------------------
def _coerce_stdin_bytes(value) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    return str(value).encode("utf-8")


def _write_output(target, raw: bytes, *, text: bool | None) -> None:
    try:
        is_text = text
        if is_text is None:
            is_text = not ("b" in str(getattr(target, "mode", "") or ""))
        if is_text:
            target.write(raw.decode("utf-8", "replace"))
        else:
            target.write(raw)
    except TypeError:
        target.write(raw)
    try:
        target.flush()
    except Exception:
        pass


def pin_windows_sandbox(command: list[str]) -> list[str]:
    """Pin the Codex Windows sandbox driver for this host.

    ``[windows] sandbox = "elevated"`` needs a logon type the Codex sandbox
    accounts are not granted here, so the sandbox child process never starts
    and every workspace-write critic fails before it can write. Story OS always
    asks for ``-s workspace-write``, so the adapter pins a driver that can
    actually spawn. Any caller-supplied ``windows.sandbox`` wins, and
    ``STORY_OS_CODEX_WINDOWS_SANDBOX=""`` disables the pin entirely.
    """
    if os.name != "nt":
        return command
    if any("windows.sandbox" in token for token in command):
        return command
    mode = str(os.environ.get(WINDOWS_SANDBOX_ENV, DEFAULT_WINDOWS_SANDBOX)).strip()
    if not mode:
        return command
    for index, token in enumerate(command):
        if Path(str(token)).name.strip().lower() in ALLOWED_CODEX_BASENAMES:
            # Deliberately a TOML *literal* string (single quotes): this argv may
            # travel through `cmd.exe /d /c` (the .cmd/.bat codex shim), and only
            # single quotes survive that layer verbatim. Double quotes get
            # mangled, the override then fails to parse and Codex silently keeps
            # the user's unusable `elevated` setting.
            override = ["-c", f"windows.sandbox='{mode}'"]
            return command[: index + 1] + override + command[index + 1 :]
    return command


def run_model_codex(*args, **kwargs):
    """Canonical native-only CLI facade for model-producing tasks.

    Fail closed on inherited provider overrides: never silently choose
    OpenCodex. Keep caller output/timeout/request_id and Attempt semantics.
    Diagnostic login/catalog commands must continue to use run_codex.
    """
    params = dict(kwargs)
    raw_env = params.get("env")
    strict_env = dict(os.environ if raw_env is None else raw_env)
    strict_env["STORY_OS_MODEL_TRANSPORT_POLICY"] = "DUAL_ONLY"
    params["env"] = strict_env
    return run_codex(*args, **params)


def run_codex(
    argv,
    *,
    input=None,
    stdin_text=None,
    stdout=None,
    stderr=None,
    timeout=None,
    check=False,
    cwd=None,
    text=None,
    encoding=None,
    errors=None,
    env=None,
    task_type="generic_codex",
    codex_home_mode="inherit",
    request_id=None,
):
    """Run one Codex task, directly or through the user-mode runner.

    Direct mode is byte-identical to ``subprocess.run`` for the keyword subset
    Story OS uses. Bridge mode forwards the same declarative task to the
    interactive-user runner and replays its merged output into ``stdout``.
    """
    command = pin_windows_sandbox([str(x) for x in argv])
    provider_route = resolve_provider_transport(command, env=env, task_type=task_type)
    if provider_route:
        command = _insert_codex_args(command, provider_route.get("provider_args") or [])
    route_evidence = {
        key: provider_route.get(key)
        for key in PROVIDER_EVIDENCE_KEYS
        if provider_route and provider_route.get(key) is not None
    }
    # Isolated task homes are owned by the authenticated user Runner. On
    # Windows direct Codex ignores that isolation and may hit arg0 ACL errors.
    use_user_runner = bridge_required() or (os.name == "nt" and codex_home_mode == "isolated")
    if not use_user_runner:
        direct_guard = None
        if request_id:
            prior=task_result_path(str(request_id))
            if stdout is not subprocess.PIPE and not (
                hasattr(stdout,"flush") and isinstance(getattr(stdout,"name",None),(str,os.PathLike))):
                raise CodexUserRunnerRejected("CODEX_USER_RUNNER_DURABLE_OUTPUT_REQUIRED",
                                              "durable direct execution needs PIPE or log-file sink")
            if prior.exists():
                raise CodexUserRunnerRejected("CODEX_USER_RUNNER_DUPLICATE_REQUEST_ID",
                                              "durable direct result already exists")
            prior.parent.mkdir(parents=True,exist_ok=True)
            direct_guard=prior.with_name(prior.name+".dispatching")
            try:
                fd=os.open(str(direct_guard),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                os.close(fd)
            except FileExistsError:
                raise CodexUserRunnerRejected("CODEX_USER_RUNNER_OUTCOME_UNKNOWN",
                                              "prior dispatch requires reconciliation") from None
            if prior.exists():
                # A previous result won a race before this reservation.
                # Leave the guard for explicit reconciliation rather than retry.
                raise CodexUserRunnerRejected("CODEX_USER_RUNNER_DUPLICATE_REQUEST_ID",
                                              "existing durable result must be reconciled")
        started = time.monotonic()
        kwargs = {
            "input": input,
            "stdout": stdout,
            "stderr": stderr,
            "timeout": timeout,
            "check": check,
            "cwd": cwd,
        }
        # Direct mode must be byte-compatible with bridge mode: the Codex CLI
        # rejects non-UTF-8 stdin, and bridge mode already encodes/decodes UTF-8.
        # Without this, a Windows cp936 locale mangles Chinese prompts.
        if text and encoding is None:
            encoding = "utf-8"
        if text and errors is None:
            errors = "replace"
        for key, value in (("text", text), ("encoding", encoding), ("errors", errors)):
            if value is not None:
                kwargs[key] = value
        if env is not None:
            kwargs["env"] = env
        try:
            completed = subprocess.run(command, **kwargs)
        except subprocess.TimeoutExpired as exc:
            exc.remote = {
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "timed_out": True,
                "returncode": 124,
                "task_type": str(task_type),
                "transport": "direct_codex_user_runner",
                **route_evidence,
            }
            raise
        # Capture per-thread provider artifacts before CODEX_HOME is removed.
        # This runs only after a successful native image subprocess and adds
        # provenance, never a Generation Attempt state transition.
        image_capture = {}
        if request_id and task_type == "image" and completed.returncode == 0:
            image_capture = _archive_direct_thread_image(
                str(request_id), _direct_result_output(stdout, completed),
                kwargs.get("env") or os.environ)
        # Preserve a runner-owned receipt for callers that need trustworthy
        # timing. This is measured around the actual Codex process, not host
        # preparation/handshake time.
        completed.remote = {
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "timed_out": False,
            "returncode": int(completed.returncode),
            "task_type": str(task_type),
            "transport": "direct_codex_user_runner",
            **({"request_id":str(request_id)} if request_id else {}),
            **image_capture,
            **route_evidence,
        }
        if request_id:
            _persist_direct_result(str(request_id), completed, stdout, completed.remote)
            if direct_guard is not None:
                direct_guard.unlink(missing_ok=True)
        return completed
    payload = input if input is not None else stdin_text
    # Normalize cmd.exe/python wrappers on the caller side before crossing the
    # loopback bridge. This keeps older already-running user-mode runners from
    # seeing transport-only tokens such as /d or /c as Codex CLI arguments.
    bridge_head, bridge_args = split_argv(command)
    task = build_task(
        [bridge_head, *bridge_args],
        stdin_bytes=_coerce_stdin_bytes(payload),
        timeout=timeout,
        env=env,
        cwd=cwd,
        task_type=task_type,
        codex_home_mode=codex_home_mode,
        request_id=str(request_id) if request_id else None,
    )
    try:
        result = execute_codex(task)
    except Exception as exc:
        if route_evidence:
            prior = getattr(exc, "remote", None)
            exc.remote = {**(prior if isinstance(prior, dict) else {}), **route_evidence}
        raise
    captured = None
    if stdout is None or stdout is subprocess.PIPE:
        captured = result.text if text else result.output
    else:
        _write_output(stdout, result.output, text=text if text is not None else not isinstance(stdout, (bytes, bytearray)))
    completed = subprocess.CompletedProcess(command, result.returncode, captured, None)
    completed.remote = {**dict(result.remote or {}), **route_evidence}
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, command, captured)
    return completed



def _grant_runner_workspace_access(path: Path) -> None:
    """Grant only this disposable workspace to the active interactive runner user.

    The caller can be SYSTEM while Codex runs as the logged-in user. On Windows,
    SYSTEM-created child directories may inherit an ACL that lets Python's
    os.access probe succeed but still makes Codex helper/bootstrap access fail
    with os error 5. Never widen repository or credential-tree permissions here.
    """
    if os.name != "nt" or not bridge_required():
        return
    endpoint = read_endpoint(required=False) or {}
    principal = str(endpoint.get("user") or expected_user() or "").strip()
    if not principal:
        raise CodexUserRunnerWorkspaceUnavailable(
            "CODEX_USER_RUNNER_WORKSPACE_UNAVAILABLE",
            f"cannot determine interactive runner user for shared workspace {path}",
        )
    completed = subprocess.run(
        ["icacls", str(path), "/grant", f"{principal}:(OI)(CI)(M)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise CodexUserRunnerWorkspaceUnavailable(
            "CODEX_USER_RUNNER_WORKSPACE_UNAVAILABLE",
            f"failed to grant runner access to {path}: {completed.stdout[-800:]}",
        )


def workspace_path(prefix="story-os-codex-") -> Path:
    """Temporary workspace usable by both the caller and the runner user.

    Under SYSTEM the OS temp directory is not reliably readable by the
    interactive user, so bridged tasks stage inside the repository runtime
    directory. Only the newly-created disposable child receives an explicit
    runner-user Modify ACE; the caller owns cleanup.
    """
    root = tmp_root() if bridge_required() else Path(tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))
    _grant_runner_workspace_access(path)
    return path


@contextmanager
def workspace(prefix="story-os-codex-"):
    """Context-manager form of workspace_path."""
    path = workspace_path(prefix)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cmd_health(as_json: bool) -> int:
    try:
        body = runner_health()
    except CodexUserRunnerError as exc:
        print(json.dumps({"status": "error", "code": exc.code, "detail": exc.detail}, ensure_ascii=False, indent=2))
        return 2
    if as_json:
        print(json.dumps(body, ensure_ascii=False, indent=2))
    else:
        print(f"status={body.get('status')} user={body.get('user')} codex={body.get('codex_version')} "
              f"home={body.get('codex_home')}")
    return 0


def _cmd_exec(argv: list[str], timeout: int | None, task_type: str) -> int:
    stdin_data = None
    if not sys.stdin.isatty():
        try:
            stdin_data = sys.stdin.buffer.read()
        except Exception:
            stdin_data = None
    try:
        result = run_codex(
            argv,
            input=stdin_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=False,
            task_type=task_type,
        )
    except CodexUserRunnerError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except subprocess.TimeoutExpired as exc:
        print(f"CODEX_USER_RUNNER_TIMEOUT: {exc}", file=sys.stderr)
        return 124
    out = result.stdout or b""
    sys.stdout.buffer.write(out if isinstance(out, bytes) else str(out).encode("utf-8", "replace"))
    sys.stdout.flush()
    return int(result.returncode)


def _cmd_task(request_path: Path) -> int:
    payload = _read_json(Path(request_path))
    task = CodexTask.from_payload(payload)
    try:
        result = execute_codex(task) if bridge_required() else execute_task(task)
    except CodexUserRunnerError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "detail": exc.detail}, ensure_ascii=False, indent=2))
        return 3
    print(json.dumps({"ok": True, "returncode": result.returncode, "evidence": result.remote,
                      "output": result.text[-4000:]}, ensure_ascii=False, indent=2))
    return 0 if result.returncode == 0 else 1


def self_test() -> int:
    import unittest

    # Local probe budgets for the in-module self-test (never a role default).
    probe_budget = 10
    version_budget = 5

    class _T(unittest.TestCase):
        def test_identity(self):
            self.assertFalse(is_non_interactive("RENRP\\yeqian"))
            self.assertTrue(is_non_interactive("NT AUTHORITY\\SYSTEM"))
            self.assertTrue(is_non_interactive("SYSTEM"))
            self.assertTrue(user_matches("RENRP\\yeqian", "yeqian"))

        def test_only_codex_may_execute(self):
            head, args = split_argv(["C:\\x\\codex.exe", "exec", "--json", "-"])
            self.assertTrue(is_codex_basename(head))
            self.assertEqual(args, ["exec", "--json", "-"])
            with self.assertRaises(CodexUserRunnerRejected):
                split_argv(["cmd.exe", "/c", "whoami"])
            with self.assertRaises(CodexUserRunnerRejected):
                split_argv(["powershell.exe", "-Command", "x"])

        def test_cmd_wrapper_unwrapped(self):
            head, args = split_argv(["cmd.exe", "/d", "/c", "C:\\x\\codex.cmd", "exec", "-"])
            self.assertEqual(Path(head).name, "codex.cmd")
            self.assertEqual(args, ["exec", "-"])

        def test_env_filter(self):
            allowed, home = split_env({"CODEX_HOME": "C:\\tmp", "STORY_OS_WORKER_ID": "a",
                                       "PATH": "C:\\evil", "PYTHONUTF8": "1"})
            self.assertEqual(home, "C:\\tmp")
            self.assertNotIn("PATH", allowed)
            self.assertEqual(allowed["STORY_OS_WORKER_ID"], "a")

        def test_timeout_is_technical(self):
            exc = CodexUserRunnerTimeout(["codex"], 5)
            self.assertIsInstance(exc, subprocess.TimeoutExpired)
            self.assertTrue(is_technical(exc))
            self.assertEqual(error_code(exc), "CODEX_USER_RUNNER_TIMEOUT")

        def test_task_roundtrip(self):
            task = build_task(["codex", "exec", "-"], stdin_bytes=b"hi",
                              timeout=probe_budget, task_type="critic", cwd=ROOT)
            restored = CodexTask.from_payload(json.loads(json.dumps(task.to_payload())))
            self.assertEqual(restored.stdin_bytes(), b"hi")
            self.assertEqual(restored.task_type, "critic")

        def test_direct_mode_passthrough(self):
            from unittest import mock

            with mock.patch.dict(os.environ, {TRANSPORT_ENV: "direct"}):
                with mock.patch.object(subprocess, "run", return_value="sentinel") as run:
                    self.assertEqual(
                        run_codex(["codex", "--version"], timeout=version_budget), "sentinel")
                self.assertEqual(run.call_args.kwargs["timeout"], version_budget)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(_T)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    if not result.wasSuccessful():
        return 1
    print("CODEX USER RUNNER SELF-TEST PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Story OS Codex user-mode execution bridge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--token", default=None)
    sub.add_parser("reconcile-endpoint")
    p = sub.add_parser("health")
    p.add_argument("--json", action="store_true")
    sub.add_parser("status")
    p = sub.add_parser("exec")
    p.add_argument("--timeout", type=int, default=None)
    p.add_argument("--task-type", default="generic_codex", choices=sorted(ALLOWED_TASK_TYPES))
    p.add_argument("codex_argv", nargs=argparse.REMAINDER)
    p = sub.add_parser("task")
    p.add_argument("request_json", type=Path)
    sub.add_parser("self-test")
    args = ap.parse_args()
    if args.cmd == "self-test":
        return self_test()
    if args.cmd == "serve":
        return serve(args.host, args.port, args.token)
    if args.cmd == "reconcile-endpoint":
        report = reconcile_dead_endpoint()
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["status"] in {"ENDPOINT_ABSENT", "STALE_ENDPOINT_RECOVERED"} else 4
    if args.cmd == "health":
        return _cmd_health(args.json)
    if args.cmd == "status":
        endpoint = read_endpoint(required=False)
        print(json.dumps(endpoint, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "exec":
        argv = [x for x in args.codex_argv if x != "--"]
        if not argv:
            print("usage: codex_user_runner.py exec [--timeout N] -- codex exec ...", file=sys.stderr)
            return 2
        return _cmd_exec(argv, args.timeout, args.task_type)
    return _cmd_task(args.request_json)


if __name__ == "__main__":
    raise SystemExit(main())

# STORY_OS_V2_7_CODEX_USER_MODE_BRIDGE