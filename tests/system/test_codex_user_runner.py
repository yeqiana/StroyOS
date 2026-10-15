#!/usr/bin/env python3
"""Story OS V2.7 Codex user-mode execution bridge tests.

Covers the SYSTEM workspace host -> Codex user-mode runner -> codex exec path:
identity refusal, health, unavailable/dead runner, token auth, fixed codex
executable, arbitrary-executable rejection, timeout, non-zero rc
classification, the critic-lane call chain, and credential containment.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SYSTEM_DIR = ROOT / "episodes/_system"
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import codex_critic_runner
import codex_user_runner as bridge
import critic_runtime_v211
import runtime_failure_classifier

BACKSLASH = chr(92)
SYSTEM_ID = "NT AUTHORITY" + BACKSLASH + "SYSTEM"
RUNNER_USER = "RENRP" + BACKSLASH + "yeqian"
CODEX_VERSION = "codex-cli 0.153.4"

def test_native_runner_inherits_local_windows_proxy_only_for_child():
    with mock.patch.object(bridge, "_wininet_native_proxy",
                           return_value="http://127.0.0.1:7897"):
        env = {"PYTHONUTF8": "1"}
        bridge._apply_wininet_proxy_to_codex_env(env)
        assert env["HTTPS_PROXY"] == "http://127.0.0.1:7897"
        assert env["HTTP_PROXY"] == "http://127.0.0.1:7897"


def test_native_runner_does_not_override_explicit_proxy_or_invent_one():
    with mock.patch.object(bridge, "_wininet_native_proxy",
                           return_value="http://127.0.0.1:7897") as probe:
        env = {"HTTPS_PROXY": "http://existing.example:7777"}
        bridge._apply_wininet_proxy_to_codex_env(env)
        assert env["HTTPS_PROXY"] == "http://existing.example:7777"
        assert "HTTP_PROXY" not in env
        probe.assert_not_called()
    with mock.patch.object(bridge, "_wininet_native_proxy", return_value=None):
        env = {}
        bridge._apply_wininet_proxy_to_codex_env(env)
        assert env == {}


def test_isolated_worktree_reads_only_own_repository_runner_endpoint(tmp_path):
    import codex_user_runner as runner
    import pathlib
    root = tmp_path / "repo"
    isolated = root / ".worktrees" / "integration"
    isolated.mkdir(parents=True)
    shared_dir = root / "runtime" / "codex-user-runner"
    shared_dir.mkdir(parents=True)
    shared = shared_dir / "endpoint.json"
    shared.write_text('{"pid":123,"port":9999,"host":"127.0.0.1"}', encoding="utf-8")
    worktree_gitdir = root / ".git" / "worktrees" / "integration"
    worktree_gitdir.mkdir(parents=True)
    (isolated / ".git").write_text(
        "gitdir: " + str(worktree_gitdir), encoding="utf-8")
    with mock.patch.object(runner, "ROOT", isolated):
        assert runner.endpoint_path().resolve() == shared.resolve()


def test_worktree_rejects_endpoint_from_unrelated_repository(tmp_path):
    import codex_user_runner as runner
    root = tmp_path / "repo"
    worktree = root / "other" / "integration"
    worktree.mkdir(parents=True)
    other_git = root / ".git" / "worktrees" / "integration"
    other_git.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: " + str(other_git), encoding="utf-8")
    shared = root / "runtime" / "codex-user-runner" / "endpoint.json"
    shared.parent.mkdir(parents=True)
    shared.write_text('{"pid":123}', encoding="utf-8")
    with mock.patch.object(runner, "ROOT", worktree):
        assert runner.endpoint_path() == worktree / "runtime" / "codex-user-runner" / "endpoint.json"


def test_mocked_runner_runtime_stays_isolated_from_live_runner(tmp_path):
    import codex_user_runner as runner
    with mock.patch.object(runner, "runtime_dir", return_value=tmp_path):
        assert runner.endpoint_path() == tmp_path / "endpoint.json"



class FakeCompleted:
    """Minimal subprocess.CompletedProcess stand-in."""

    def __init__(self, returncode=0, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = None


class InProcessRunner:
    """Port-0 equivalent of `codex_user_runner.py serve`, isolated to a temp dir.

    Everything the client reads (endpoint file, token file, log, tmp root) is
    redirected into the test temp directory, so the developer runner that is
    already registered in the real runtime directory is never disturbed.
    """

    def __init__(self, tmp: Path, codex: Path, token: str = "test-local-nonce"):
        self.tmp = Path(tmp)
        self.codex = Path(codex)
        self.token = token
        self.runtime = self.tmp / "runtime"
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.fake_home = self.tmp / "runner-codex-home"
        self.fake_home.mkdir(parents=True, exist_ok=True)
        (self.fake_home / "auth.json").write_text("{}", encoding="utf-8")
        (self.fake_home / "config.toml").write_text('model = "stub"\n', encoding="utf-8")
        self.stack = contextlib.ExitStack()
        self.httpd = None
        self.thread = None
        self.home_read_threads: list[int] = []

    def _codex_home(self, *args, **kwargs):
        self.home_read_threads.append(threading.get_ident())
        return self.fake_home, "USERPROFILE"

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d" % int(self.httpd.server_address[1])

    def __enter__(self):
        client_thread = threading.get_ident()
        def fake_identity():
            # The test process models the SYSTEM client on its main thread and
            # the interactive user runner on HTTP worker threads. Do not let the
            # account that launched pytest decide this contract implicitly.
            return SYSTEM_ID if threading.get_ident() == client_thread else RUNNER_USER
        self.stack.enter_context(
            mock.patch.object(bridge, "runtime_dir", return_value=self.runtime))
        self.stack.enter_context(
            mock.patch.object(bridge, "current_identity", side_effect=fake_identity))
        self.stack.enter_context(
            mock.patch.object(bridge, "resolve_codex", return_value=(self.codex, "test_runner_resolved")))
        self.stack.enter_context(
            mock.patch.object(bridge, "codex_version", return_value=CODEX_VERSION))
        self.stack.enter_context(
            mock.patch.object(bridge, "codex_home", side_effect=self._codex_home))
        httpd = bridge.ThreadingHTTPServer(("127.0.0.1", 0), bridge._Handler)
        httpd.daemon_threads = True
        state = bridge.RunnerState("127.0.0.1", httpd.server_address[1], self.token)
        previous = getattr(bridge._Handler, "state", None)
        bridge._Handler.state = state
        self.stack.callback(setattr, bridge._Handler, "state", previous)
        # Endpoint metadata belongs to the runner, not the SYSTEM client thread.
        with mock.patch.object(bridge, "current_identity", return_value=RUNNER_USER):
            bridge.write_endpoint("127.0.0.1", httpd.server_address[1], self.token)
        self.httpd = httpd
        self.thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self.thread.start()
        self.stack.callback(httpd.server_close)
        self.stack.callback(httpd.shutdown)
        return self

    def __exit__(self, *exc_info):
        return self.stack.__exit__(*exc_info)


class CodexUserRunnerBridgeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="codex-user-runner-test-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.codex_stub = self.tmp / "codex.exe"
        self.codex_stub.write_text("stub", encoding="utf-8")

    @contextlib.contextmanager
    def transport(self, mode: str):
        with mock.patch.dict(os.environ, {"STORY_OS_CODEX_TRANSPORT": mode}, clear=False):
            yield

    def stub_codex(self):
        return mock.patch.object(
            bridge, "resolve_codex", return_value=(self.codex_stub, "test_stub"))

    # ------------------------------------------------------------------
    # Case 1: a non-interactive identity must refuse to serve
    # ------------------------------------------------------------------
    def test_case1_non_interactive_identity_is_refused(self):
        with mock.patch.object(bridge, "current_identity", return_value=SYSTEM_ID), \
                mock.patch.object(bridge, "runtime_dir", return_value=self.tmp / "runtime"):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = bridge.serve(port=0)
            self.assertEqual(rc, 2)
            self.assertIn("CODEX_USER_RUNNER_WRONG_IDENTITY", stderr.getvalue())
            self.assertTrue(bridge.is_non_interactive(SYSTEM_ID))
            task = bridge.CodexTask(argv=["codex", "exec", "--json", "-"])
            with self.assertRaises(bridge.CodexUserRunnerWrongIdentity) as ctx:
                bridge.execute_task(task)
        self.assertEqual(bridge.error_code(ctx.exception),
                         "CODEX_USER_RUNNER_WRONG_IDENTITY")
        self.assertTrue(bridge.is_technical(ctx.exception))
        self.assertEqual(bridge.account_name(SYSTEM_ID), "SYSTEM")
        self.assertFalse(bridge.is_non_interactive(RUNNER_USER))

    def test_case1b_loopback_binding_is_enforced(self):
        with mock.patch.object(bridge, "current_identity", return_value=RUNNER_USER), \
                mock.patch.object(bridge, "runtime_dir", return_value=self.tmp / "runtime"):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = bridge.serve(host="0.0.0.0", port=0)
            self.assertEqual(rc, 2)
            self.assertIn("loopback", stderr.getvalue())

    # ------------------------------------------------------------------
    # Case 2: runner health describes a real interactive user
    # ------------------------------------------------------------------
    def test_case2_health_reports_interactive_user_and_codex(self):
        with self.transport("user_runner"), InProcessRunner(self.tmp, self.codex_stub) as runner:
            health = bridge.runner_health()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["user"], RUNNER_USER)
        self.assertFalse(bridge.is_non_interactive(health["user"]))
        self.assertTrue(health["interactive_user"])
        self.assertTrue(health["codex_available"])
        self.assertEqual(health["codex_version"], CODEX_VERSION)
        self.assertEqual(health["codex_executable"], str(self.codex_stub))
        self.assertTrue(health["codex_home_accessible"])
        self.assertTrue(health["codex_auth_present"])
        self.assertTrue(health["codex_config_present"])
        self.assertEqual(health["transport"], "user_runner")
        self.assertFalse(health["secrets_persisted"])
        self.assertNotIn(runner.token, json.dumps(health, ensure_ascii=False))

    # ------------------------------------------------------------------
    # Case 3: no runner / dead runner is a technical unavailability
    # ------------------------------------------------------------------
    def test_case3_missing_or_dead_runner_is_unavailable(self):
        empty = self.tmp / "empty-runtime"
        empty.mkdir(parents=True, exist_ok=True)
        with self.transport("user_runner"), \
                mock.patch.object(bridge, "runtime_dir", return_value=empty):
            with self.assertRaises(bridge.CodexUserRunnerUnavailable) as ctx:
                bridge.runner_health()
            self.assertEqual(bridge.error_code(ctx.exception),
                             "CODEX_USER_RUNNER_UNAVAILABLE")
            self.assertTrue(bridge.is_technical(ctx.exception))
            with self.assertRaises(bridge.CodexUserRunnerUnavailable):
                bridge.run_codex(["codex", "exec", "--json", "-"], input=b"ping")

        dead = self.tmp / "dead-runtime"
        dead.mkdir(parents=True, exist_ok=True)
        (dead / bridge.ENDPOINT_NAME).write_text(json.dumps({
            "schema_version": 1, "host": "127.0.0.1", "port": 1,
            "token": "stale", "pid": 999999, "user": RUNNER_USER,
        }), encoding="utf-8")
        with self.transport("user_runner"), \
                mock.patch.object(bridge, "runtime_dir", return_value=dead):
            with self.assertRaises(bridge.CodexUserRunnerUnavailable) as ctx2:
                bridge.runner_health()
        self.assertEqual(bridge.error_code(ctx2.exception),
                         "CODEX_USER_RUNNER_UNAVAILABLE")
        self.assertIn("not running", str(ctx2.exception))

    # ------------------------------------------------------------------
    # Case 4: the local nonce is the only accepted credential
    # ------------------------------------------------------------------
    def test_case4_wrong_token_is_auth_failed(self):
        with self.transport("user_runner"), InProcessRunner(self.tmp, self.codex_stub) as runner:
            wrong = {"STORY_OS_CODEX_RUNNER_URL": runner.url,
                     "STORY_OS_CODEX_RUNNER_TOKEN": "wrong-nonce"}
            right = {"STORY_OS_CODEX_RUNNER_URL": runner.url,
                     "STORY_OS_CODEX_RUNNER_TOKEN": runner.token}
            with mock.patch.dict(os.environ, wrong, clear=False):
                with self.assertRaises(bridge.CodexUserRunnerAuthFailed) as ctx:
                    bridge.runner_health()
                with self.assertRaises(bridge.CodexUserRunnerAuthFailed):
                    bridge.execute_codex(bridge.build_task(
                        ["codex", "exec", "--json", "-"], stdin_bytes=b"x",
                        cwd=ROOT, task_type="critic"))
            with mock.patch.dict(os.environ, right, clear=False):
                self.assertEqual(bridge.runner_health()["user"], RUNNER_USER)
        self.assertEqual(bridge.error_code(ctx.exception),
                         "CODEX_USER_RUNNER_AUTH_FAILED")
        self.assertTrue(bridge.is_technical(ctx.exception))

    # ------------------------------------------------------------------
    # Case 5: the runner executes Codex and nothing else
    # ------------------------------------------------------------------
    def test_case5_executable_is_always_codex(self):
        evil = self.tmp / "payload.exe"
        evil.write_text("stub", encoding="utf-8")
        with mock.patch.object(bridge, "_codex_candidates", return_value=[self.codex_stub]):
            self.assertEqual(bridge.resolve_codex(str(evil)),
                             (self.codex_stub.resolve(), "runner_resolved"))
            self.assertEqual(bridge.resolve_codex(str(self.codex_stub)),
                             (self.codex_stub.resolve(), "caller_nominated_codex"))
        self.assertTrue(bridge.is_codex_basename("codex.cmd"))
        self.assertFalse(bridge.is_codex_basename(str(evil)))

        task = bridge.CodexTask(argv=[str(evil), "exec", "--json", "-"],
                                working_directory=str(ROOT))
        with self.stub_codex(), \
                mock.patch.object(bridge, "current_identity", return_value=RUNNER_USER), \
                mock.patch.object(bridge.subprocess, "run",
                                  return_value=FakeCompleted(0, b"ok")) as run:
            with self.assertRaises(bridge.CodexUserRunnerRejected) as ctx:
                bridge.execute_task(task)
        self.assertEqual(bridge.error_code(ctx.exception),
                         "CODEX_USER_RUNNER_TASK_REJECTED")
        run.assert_not_called()

        cmd_task = bridge.CodexTask(argv=["cmd.exe", "/c", "calc.exe"],
                                   working_directory=str(ROOT))
        with self.stub_codex(), \
                mock.patch.object(bridge, "current_identity", return_value=RUNNER_USER), \
                mock.patch.object(bridge.subprocess, "run",
                                  return_value=FakeCompleted(0, b"ok")) as run2:
            with self.assertRaises(bridge.CodexUserRunnerRejected) as ctx:
                bridge.execute_task(cmd_task)
        self.assertEqual(bridge.error_code(ctx.exception),
                         "CODEX_USER_RUNNER_TASK_REJECTED")
        run2.assert_not_called()

    # ------------------------------------------------------------------
    # Case 6: arbitrary executables / task types / home modes are rejected
    # ------------------------------------------------------------------
    def test_case6_arbitrary_executables_are_rejected(self):
        rejected = [
            ["cmd.exe", "/c", "echo", "pwned"],
            ["cmd.exe"],
            ["powershell.exe", "-Command", "whoami"],
            ["python.exe", "evil.py"],
            ["/bin/sh", "-c", "id"],
            [],
        ]
        for argv in rejected:
            with self.assertRaises(bridge.CodexUserRunnerRejected) as ctx:
                bridge.build_task(argv, stdin_bytes=b"x", cwd=ROOT)
            self.assertEqual(bridge.error_code(ctx.exception),
                             "CODEX_USER_RUNNER_TASK_REJECTED", msg=str(argv))
        head, rest = bridge.split_argv(
            ["cmd.exe", "/d", "/c", "codex.cmd", "exec", "--json"])
        self.assertEqual(head, "codex.cmd")
        self.assertEqual(rest, ["exec", "--json"])
        with self.assertRaises(bridge.CodexUserRunnerRejected):
            bridge.build_task(["codex", "exec"], task_type="shell", cwd=ROOT)
        with self.assertRaises(bridge.CodexUserRunnerRejected):
            bridge.build_task(["codex", "exec"], codex_home_mode="system", cwd=ROOT)
        payload = bridge.build_task(
            ["codex", "exec", "--json", "-"], stdin_bytes=b"x", cwd=ROOT).to_payload()
        for forbidden in ("executable", "shell", "command", "cmd"):
            self.assertNotIn(forbidden, payload)

    # ------------------------------------------------------------------
    # Case 7: timeouts surface as a technical runner code
    # ------------------------------------------------------------------
    def test_case7_timeout_is_a_technical_runner_code(self):
        task = bridge.CodexTask(argv=["codex", "exec", "--json", "-"],
                               timeout_seconds=1, working_directory=str(ROOT))
        with self.stub_codex(), \
                mock.patch.object(bridge, "current_identity", return_value=RUNNER_USER), \
                mock.patch.object(bridge.subprocess, "run",
                                  side_effect=subprocess.TimeoutExpired("codex", 1)):
            result = bridge.execute_task(task)
        self.assertEqual(result.returncode, 124)
        self.assertTrue(result.remote["timed_out"])

        with self.transport("user_runner"), InProcessRunner(self.tmp, self.codex_stub):
            with mock.patch.object(bridge.subprocess, "run",
                                   side_effect=subprocess.TimeoutExpired("codex", 1)):
                with self.assertRaises(bridge.CodexUserRunnerTimeout) as ctx:
                    bridge.execute_codex(bridge.build_task(
                        ["codex", "exec", "--json", "-"], stdin_bytes=b"x",
                        cwd=ROOT, timeout=1, task_type="critic"))
        self.assertEqual(bridge.error_code(ctx.exception),
                         "CODEX_USER_RUNNER_TIMEOUT")
        self.assertTrue(bridge.is_technical(ctx.exception))
        self.assertIsInstance(ctx.exception, subprocess.TimeoutExpired)

    # ------------------------------------------------------------------
    # Case 8: a non-zero Codex rc is technical, never content
    # ------------------------------------------------------------------
    def test_case8_nonzero_codex_exit_is_technical_not_content(self):
        decision = runtime_failure_classifier.classify(
            1, "CODEX_EXEC_FAILED: codex exited 1")
        self.assertEqual(decision.category, "TECH_FAILED")
        self.assertTrue(decision.retryable)
        self.assertNotEqual(decision.category, "CONTENT_FAILED")
        content = runtime_failure_classifier.classify(1, "visual identity drift")
        self.assertEqual(content.category, "CONTENT_FAILED")
        self.assertFalse(content.retryable)
        self.assertEqual(
            critic_runtime_v211.classify_issue_codes(["CODEX_EXEC_FAILED"]),
            ["CODEX_EXEC_FAILED"])
        self.assertEqual(
            critic_runtime_v211.classify_issue_codes(["CODEX_USER_RUNNER_UNAVAILABLE"]),
            ["CODEX_USER_RUNNER_UNAVAILABLE"])
        self.assertEqual(
            critic_runtime_v211.classify_issue_codes(["VISUAL_IDENTITY_DRIFT"]), [])
        self.assertTrue(bridge.is_technical(bridge.CodexExecFailed(
            "CODEX_EXEC_FAILED", "rc=1")))

        log = self.tmp / "attempt-1.jsonl"
        with self.transport("user_runner"), InProcessRunner(self.tmp, self.codex_stub):
            with mock.patch.object(bridge.subprocess, "run",
                                   return_value=FakeCompleted(1, b"boom")):
                with log.open("w", encoding="utf-8", newline="\n") as handle:
                    completed = bridge.run_codex(
                        ["codex", "exec", "--json", "-"], input=b"x",
                        stdout=handle, stderr=subprocess.STDOUT, timeout=30,
                        check=False, task_type="critic")
                self.assertEqual(completed.returncode, 1)
                self.assertIn("boom", log.read_text(encoding="utf-8"))
                with self.assertRaises(subprocess.CalledProcessError):
                    with log.open("w", encoding="utf-8", newline="\n") as handle:
                        bridge.run_codex(
                            ["codex", "exec", "--json", "-"], input=b"x",
                            stdout=handle, timeout=30, check=True, task_type="critic")

    # ------------------------------------------------------------------
    # Case 9: the critic lane routes SYSTEM -> bridge -> Codex
    # ------------------------------------------------------------------
    def test_case9_critic_lane_routes_through_the_user_runner(self):
        episode = self.tmp / "episode"
        episode.mkdir(parents=True, exist_ok=True)
        log = episode / "meta" / "attempt-1.jsonl"
        bridged = bridge.ExecResult(
            returncode=0, output=b"{\"passed\": true}\n",
            remote={"user": RUNNER_USER, "transport": "user_runner"})
        # Explicit bridge routing is portable; auto detects Windows SYSTEM only.
        with self.transport("user_runner"), \
                mock.patch.object(bridge, "current_identity", return_value=SYSTEM_ID), \
                mock.patch.object(bridge, "execute_codex", return_value=bridged) as exec_mock, \
                mock.patch.object(bridge.subprocess, "run") as subprocess_mock:
            self.assertTrue(bridge.bridge_required())
            self.assertEqual(bridge.transport_name(), "user_runner")
            result = codex_critic_runner.launch(
                "critic prompt", codex=Path("codex.exe"), root=episode,
                timeout=60, log_path=log)
        self.assertEqual(result.returncode, 0)
        self.assertIn("passed", result.log_text)
        subprocess_mock.assert_not_called()
        self.assertEqual(exec_mock.call_count, 1)
        task = exec_mock.call_args[0][0]
        self.assertEqual(task.task_type, "critic")
        self.assertEqual(task.client["user"], SYSTEM_ID)
        self.assertEqual(task.client["transport"], "user_runner")
        self.assertTrue(bridge.is_codex_basename(task.argv[0]))
        self.assertEqual(task.stdin_bytes(), b"critic prompt")

    # ------------------------------------------------------------------
    # Case 10: credentials never leave the interactive user context
    # ------------------------------------------------------------------
    def test_case10_client_never_reads_the_user_codex_home(self):
        main_thread = threading.get_ident()
        with self.transport("user_runner"), \
                InProcessRunner(self.tmp, self.codex_stub) as runner:
            runner.home_read_threads.clear()
            with mock.patch.object(bridge.subprocess, "run",
                                   return_value=FakeCompleted(0, b"ok")):
                completed = bridge.run_codex(
                    ["codex", "exec", "--json", "-"], input=b"ping",
                    timeout=30, task_type="critic")
            self.assertEqual(completed.returncode, 0)
            self.assertTrue(runner.home_read_threads)
            self.assertTrue(
                all(tid != main_thread for tid in runner.home_read_threads),
                "the bridge client must not read the interactive user Codex home; "
                "only the runner thread may")

        env = {"CODEX_HOME": str(self.tmp / "user-home"), "PATH": "C:/evil"}
        payload = bridge.build_task(
            ["codex", "exec", "--json", "-"], stdin_bytes=b"ping",
            env=env, cwd=ROOT).to_payload()
        allowed, home_value = bridge.split_env(payload["env"])
        self.assertEqual(home_value, env["CODEX_HOME"])
        self.assertEqual(allowed, {})
        self.assertNotIn("CODEX_HOME", allowed)
        self.assertNotIn("PATH", allowed)
        blob = json.dumps(payload)
        self.assertNotIn("auth.json", blob)
        self.assertNotIn("token", blob)
        profile = os.environ.get("USERPROFILE") or ""
        if profile:
            self.assertNotIn(profile, blob)

    def test_case10b_isolated_home_stays_out_of_the_repository(self):
        user_home = self.tmp / "real-user-codex-home"
        user_home.mkdir(parents=True, exist_ok=True)
        (user_home / "auth.json").write_text(chr(123) + chr(125), encoding="utf-8")
        (user_home / "config.toml").write_text("model = \"stub\"", encoding="utf-8")
        user_app_data = self.tmp / "user-local-appdata"
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["home"] = kwargs["env"].get("CODEX_HOME")
            return FakeCompleted(0, b"ok")

        with self.stub_codex(), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": str(user_app_data)}, clear=False), \
                mock.patch.object(bridge, "current_identity", return_value=RUNNER_USER), \
                mock.patch.object(bridge, "codex_home",
                                  return_value=(user_home, "USERPROFILE")), \
                mock.patch.object(bridge.subprocess, "run", side_effect=fake_run):
            result = bridge.execute_task(bridge.build_task(
                ["codex", "exec", "--json", "-"], stdin_bytes=b"x",
                cwd=ROOT, codex_home_mode="isolated", task_type="image"))
        home = Path(seen["home"])
        self.assertNotEqual(home, user_home)
        expected_home_root = (
            user_app_data / "StoryOS" / bridge.RUNNER_TASK_HOME_NAME
            if os.name == "nt" else Path.home() / ".storyos" / bridge.RUNNER_TASK_HOME_NAME
        )
        self.assertTrue(home.is_relative_to(expected_home_root))
        self.assertFalse(home.is_relative_to(ROOT))
        self.assertFalse(home.is_relative_to(bridge.runtime_dir()))
        self.assertFalse(home.exists(), "the throwaway credential copy must be removed")
        self.assertEqual(result.remote["codex_home"]["seeded"],
                         ["auth.json", "config.toml"])
        self.assertEqual(result.remote["codex_home"]["root"],
                         "runner_user_profile_appdata")

    def test_case10c_isolated_home_exports_provider_artifacts(self):
        user_home = self.tmp / "user-codex-home"
        artifact = user_home / "generated_images" / "thread-1" / "out.png"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"png-bytes")
        workdir = self.tmp / "shared-workdir"
        workdir.mkdir(parents=True, exist_ok=True)
        exported = bridge._export_generated_artifacts(user_home, workdir)
        self.assertEqual(exported, ["thread-1/out.png"])
        staged = bridge.exported_artifacts_dir(workdir)
        self.assertEqual(staged, workdir / bridge.EXPORT_DIR_NAME)
        self.assertEqual((staged / "thread-1" / "out.png").read_bytes(), b"png-bytes")

    def test_case10d_settle_wait_recovers_late_thread_artifact_without_redispatch(self):
        user_home = self.tmp / "settle-user-home"
        workdir = self.tmp / "settle-workdir"
        workdir.mkdir(parents=True, exist_ok=True)
        calls = {"count": 0}
        clock = {"value": 0.0}

        def fake_export(_home, _workdir, *, thread_ids=None):
            calls["count"] += 1
            return [] if calls["count"] < 3 else ["thread-current/out.png"]

        def fake_sleep(seconds):
            clock["value"] += seconds

        def fake_monotonic():
            return clock["value"]

        with mock.patch.object(bridge, "_export_generated_artifacts", side_effect=fake_export):
            exported, settle = bridge._settle_generated_artifacts(
                user_home, workdir, thread_ids=["thread-current"],
                timeout_seconds=1.0, poll_seconds=0.1,
                sleep_fn=fake_sleep, monotonic_fn=fake_monotonic,
            )
        self.assertEqual(exported, ["thread-current/out.png"])
        self.assertTrue(settle["used"])
        self.assertEqual(settle["polls"], 3)
        self.assertGreaterEqual(settle["waited_seconds"], 0.2)

    def test_case10d_settle_wait_times_out_without_provider_redispatch(self):
        clock = {"value": 0.0}

        def fake_sleep(seconds):
            clock["value"] += seconds

        def fake_monotonic():
            return clock["value"]

        with mock.patch.object(bridge, "_export_generated_artifacts", return_value=[]) as export:
            exported, settle = bridge._settle_generated_artifacts(
                self.tmp, self.tmp, thread_ids=["thread-empty"],
                timeout_seconds=0.25, poll_seconds=0.1,
                sleep_fn=fake_sleep, monotonic_fn=fake_monotonic,
            )
        self.assertEqual(exported, [])
        self.assertTrue(settle["used"])
        self.assertGreaterEqual(settle["waited_seconds"], 0.25)
        self.assertGreaterEqual(export.call_count, 2)

    def test_case10d_inherited_home_exports_only_current_image_thread(self):
        user_home = self.tmp / "shared-user-codex-home"
        current = user_home / "generated_images" / "thread-current" / "out.png"
        sibling = user_home / "generated_images" / "thread-sibling" / "other.png"
        current.parent.mkdir(parents=True, exist_ok=True)
        sibling.parent.mkdir(parents=True, exist_ok=True)
        current.write_bytes(b"current")
        sibling.write_bytes(b"sibling")
        workdir = self.tmp / "thread-scoped-workdir"
        workdir.mkdir(parents=True, exist_ok=True)
        output = (json.dumps({"type": "thread.started", "thread_id": "thread-current"}) + "\n").encode()
        thread_ids = bridge._thread_ids_from_output(output)
        exported = bridge._export_generated_artifacts(user_home, workdir, thread_ids=thread_ids)
        self.assertEqual(thread_ids, ["thread-current"])
        self.assertEqual(exported, ["thread-current/out.png"])
        staged = bridge.exported_artifacts_dir(workdir)
        self.assertEqual((staged / "thread-current" / "out.png").read_bytes(), b"current")
        self.assertFalse((staged / "thread-sibling" / "other.png").exists())

    # ------------------------------------------------------------------
    # Native-only provider routing is independent from user-runner bridge.
    # ------------------------------------------------------------------
    def test_default_model_route_native_without_probe(self):
        with mock.patch.dict(os.environ, {"OPENAI_BASE_URL": ""}, clear=False), \
                mock.patch.object(bridge.socket, "create_connection") as probe:
            route = bridge.resolve_provider_transport(["codex", "exec", "--json", "-"])
        probe.assert_not_called()
        self.assertEqual(route["transport_route"], "native_codex")
        self.assertEqual(route["transport_route_reason"], "native_only_policy")
        self.assertEqual(route["transport_base_url"], bridge.NATIVE_CODEX_BASE_URL)

    def test_image_route_native_without_proxy_probe(self):
        with mock.patch.dict(os.environ, {"OPENAI_BASE_URL": ""}, clear=False), \
                mock.patch.object(bridge.socket, "create_connection") as probe:
            route = bridge.resolve_provider_transport(
                ["codex", "exec", "--json", "-"], task_type="image")
        probe.assert_not_called()
        self.assertEqual(route["transport_route"], "native_codex")

    def test_legacy_opencodex_env_forbidden_in_default_mode(self):
        with mock.patch.dict(os.environ, {"OPENAI_BASE_URL": "http://127.0.0.1:10100/v1"}):
            with self.assertRaisesRegex(bridge.CodexUserRunnerRejected, "MODEL_TRANSPORT_FORBIDDEN"):
                bridge.resolve_provider_transport(["codex", "exec", "--json", "-"])

    def test_custom_provider_config_forbidden_without_opt_in(self):
        command = [
            "codex", "-c", 'model_provider="custom"',
            "-c", 'model_providers.custom.base_url="http://provider.invalid/v1"',
            "exec", "--json", "-",
        ]
        with self.assertRaisesRegex(bridge.CodexUserRunnerRejected, "MODEL_TRANSPORT_FORBIDDEN"):
            bridge.resolve_provider_transport(command, env={})

    def test_explicit_native_pins_official_provider(self):
        route = bridge.resolve_provider_transport([
            "codex", "-c", f'openai_base_url="{bridge.NATIVE_CODEX_BASE_URL}"',
            "exec", "--json", "-"], env={})
        self.assertEqual(route["transport_route"], "native_codex")
        self.assertEqual(route["transport_route_reason"], "native_only_explicit_native")
        self.assertTrue(any("model_provider" in x for x in route["provider_args"]))

    def test_run_codex_persists_native_route_evidence(self):
        with self.transport("direct"), \
                mock.patch.dict(os.environ, {"OPENAI_BASE_URL": ""}, clear=False), \
                mock.patch.object(bridge.subprocess, "run", return_value=FakeCompleted(0, b"ok")) as run:
            completed = bridge.run_codex(["codex", "exec", "--json", "-"], input=b"x")
        self.assertEqual(completed.remote["transport_route"], "native_codex")
        self.assertEqual(completed.remote["transport_route_reason"], "native_only_policy")
        self.assertEqual(completed.remote["transport_base_url"], bridge.NATIVE_CODEX_BASE_URL)
        self.assertTrue(any(bridge.NATIVE_CODEX_BASE_URL in x for x in run.call_args.args[0]))

    # ------------------------------------------------------------------
    # Direct transport keeps plain subprocess semantics
    # ------------------------------------------------------------------
    def test_direct_transport_matches_subprocess(self):
        with self.transport("direct"), \
                mock.patch.object(bridge.subprocess, "run",
                                  return_value=FakeCompleted(0, b"direct")) as run:
            self.assertFalse(bridge.bridge_required())
            self.assertEqual(bridge.transport_name(), "direct")
            completed = bridge.run_codex(
                ["codex", "exec"], input=b"x", stdout=subprocess.PIPE, text=True)
        # Direct mode returns the very object subprocess.run produced.
        self.assertIs(completed.stdout, run.return_value.stdout)
        self.assertTrue(run.call_args.kwargs["text"])
        self.assertIsNone(run.call_args.kwargs["timeout"])
        command = run.call_args.args[0]
        self.assertEqual(command[0], "codex")
        self.assertIn("exec", command)
        self.assertEqual(command[-1], "exec")
        if os.name == "nt":
            self.assertIn("windows.sandbox='unelevated'", command)


if __name__ == "__main__":
    unittest.main()
