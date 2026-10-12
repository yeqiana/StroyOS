"""R35 hermetic authority-evidence and actual HTTP contract. No production DB."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from platform.api.controllers import RuntimeAuthorityApiController
from platform.api.http_server import PlatformApiDispatcher, build_http_server
from platform.operations.runtime_authority_evidence import (
    AUTHORITATIVE_SOURCES, EVIDENCE_DOMAINS, RuntimeAuthorityEvidenceService,
)
from scripts.storyos_local_readonly_api import ReadOnlyLocalDispatcher


EPISODE = "LOCAL_ep-1"


class StatusReader:
    def __init__(self, source="local_workspace_episode_state_file", ref=EPISODE, error=None):
        self.source, self.ref, self.error = source, ref, error
        self.calls = []

    def get_episode_status(self, ref):
        self.calls.append(ref)
        if self.error:
            raise self.error
        if ref != EPISODE:
            return None
        return {"episode_ref": self.ref, "state_source": self.source, "execution_status": "UNKNOWN"}


def reader_row(name, **overrides):
    result = {
        "episode_ref": EPISODE,
        "source": AUTHORITATIVE_SOURCES[name],
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "verified": True,
        "read_only": True,
    }
    return {**result, **overrides}


def test_local_file_mode_never_invokes_authorized_production_readers():
    calls = []
    service = RuntimeAuthorityEvidenceService(
        StatusReader(), permit_authority_reads=True,
        authorized_readers={name: lambda ep, n=name: calls.append((n, ep))
                            for name in EVIDENCE_DOMAINS},
    )
    payload = service.get_episode_authority(EPISODE)
    assert payload["episode_ref"] == EPISODE
    assert payload["scope"] == "LOCAL_READ_ONLY_EVIDENCE"
    assert payload["global_image_capacity_policy"] == 5
    assert payload["production_authorization"] is False
    assert payload["can_start"] is False and payload["can_retry"] is False
    assert payload["model_calls"] == 0
    assert calls == []
    assert set(payload["evidence"]) == set(EVIDENCE_DOMAINS)
    assert all(item["status"] == "UNAVAILABLE" and
               item["reason"] == "LOCAL_STAGE_ONLY" for item in payload["evidence"].values())


def test_no_explicit_authorization_blocks_all_reader_invocations():
    calls = []
    service = RuntimeAuthorityEvidenceService(
        StatusReader("runtime_authoritative"),
        authorized_readers={"task": lambda ep: calls.append(ep)},
    )
    result = service.get_episode_authority(EPISODE)
    assert result["scope"] == "AUTHORITY_NOT_CONFIGURED"
    assert result["evidence"]["task"]["reason"] == "AUTHORITY_READER_NOT_CONFIGURED"
    assert calls == []


def test_authorized_readers_show_only_identity_scoped_allowlisted_evidence():
    observers = {
        "task": lambda ep: reader_row("task", task_count=4, dsn="super-private"),
        "attempt": lambda ep: reader_row("attempt", attempt_count=2, unresolved=True,
                                         lease_secret="private-token"),
        "worker": lambda ep: reader_row("worker", heartbeat_verified=True, worker_id="private-worker"),
        "writer": lambda ep: reader_row("writer", owner_fence_verified=True, owner_token="secret"),
        "capacity": lambda ep: reader_row("capacity", observed_busy=3, observed_available=2),
    }
    result = RuntimeAuthorityEvidenceService(
        StatusReader("runtime_authoritative"),
        authorized_readers=observers, permit_authority_reads=True,
    ).get_episode_authority(EPISODE)
    assert result["scope"] == "AUTHORIZED_READ_ONLY"
    assert result["evidence"]["task"]["task_count"] == 4
    assert result["evidence"]["attempt"]["attempt_count"] == 2
    assert result["evidence"]["attempt"]["unresolved"] is True
    assert result["evidence"]["worker"]["heartbeat_verified"] is True
    assert result["evidence"]["writer"]["owner_fence_verified"] is True
    assert result["evidence"]["capacity"]["status"] == "ADVISORY_ONLY"
    assert result["evidence"]["capacity"]["observed_busy"] == 3
    assert result["evidence"]["capacity"]["observed_available"] == 2
    assert result["production_authorization"] is False
    assert not any(s in str(result) for s in ("super-private", "private-token", "private-worker", "secret"))


@pytest.mark.parametrize("change,expected", [
    ({"episode_ref": "LOCAL_foreign"}, "AUTHORITY_RECORD_IDENTITY_MISMATCH"),
    ({"source": "test_or_unknown_source"}, "AUTHORITY_SOURCE_UNVERIFIED"),
    ({"verified": False}, "AUTHORITY_PROOF_INCOMPLETE"),
    ({"read_only": False}, "AUTHORITY_PROOF_INCOMPLETE"),
    ({"observed_at": "2026-01-01T00:00:00Z"}, "AUTHORITY_OBSERVATION_STALE"),
    ({"observed_at": "2026-10-10T00:00:00"}, "AUTHORITY_OBSERVATION_TIME_INVALID"),
    ({"observed_at": "malformed"}, "AUTHORITY_OBSERVATION_TIME_INVALID"),
])
def test_incorrect_or_stale_claims_fail_closed(change, expected):
    item = RuntimeAuthorityEvidenceService(
        StatusReader("runtime_authoritative"),
        permit_authority_reads=True,
        authorized_readers={"task": lambda ep: reader_row("task", **change)},
    ).get_episode_authority(EPISODE)["evidence"]["task"]
    assert item["status"] == "UNAVAILABLE"
    assert item["reason"] == expected
    assert "LOCAL_foreign" not in str(item)


def test_inspector_errors_sanitize_backend_secrets():
    result = RuntimeAuthorityEvidenceService(
        StatusReader("runtime_authoritative"),
        permit_authority_reads=True,
        authorized_readers={"task": lambda ep: (_ for _ in ()).throw(ConnectionError("mysql DSN secret"))},
    ).get_episode_authority(EPISODE)
    assert result["evidence"]["task"]["reason"] == "AUTHORITY_READER_FAILED"
    assert result["evidence"]["task"]["error_type"] == "ConnectionError"
    assert "secret" not in str(result)


def test_unknown_and_cross_episode_status_never_call_authority_readers():
    reader_calls = []
    bad = RuntimeAuthorityEvidenceService(
        StatusReader(source="runtime_authoritative", ref="LOCAL_foreign"),
        authorized_readers={"task": lambda ep: reader_calls.append(ep)},
        permit_authority_reads=True,
    )
    with pytest.raises(ValueError, match="RUNTIME_AUTHORITY_EPISODE_IDENTITY_MISMATCH"):
        bad.get_episode_authority(EPISODE)
    assert reader_calls == []
    assert bad.get_episode_authority("LOCAL_missing") is None


def test_invalid_episode_rejected_before_status_lookup():
    status = StatusReader()
    service = RuntimeAuthorityEvidenceService(status)
    with pytest.raises(ValueError):
        service.get_episode_authority(" ")
    with pytest.raises(ValueError):
        service.get_episode_authority("x" * 257)
    assert status.calls == []


def test_invalid_reader_domain_fails_at_composition_time():
    with pytest.raises(ValueError, match="UNKNOWN_RUNTIME_EVIDENCE_READER"):
        RuntimeAuthorityEvidenceService(StatusReader(), authorized_readers={"provider-write": lambda _: None})


def test_capacity_snapshot_is_never_dispatch_authorization():
    reader = lambda ep: reader_row("capacity", observed_busy=3, observed_available=0)
    payload = RuntimeAuthorityEvidenceService(
        StatusReader("runtime_authoritative"),
        permit_authority_reads=True,
        authorized_readers={"capacity": reader},
    ).get_episode_authority(EPISODE)
    capacity = payload["evidence"]["capacity"]
    assert capacity["status"] == "ADVISORY_ONLY"
    assert "observed_available" not in capacity  # contradictory snapshot omitted
    assert payload["can_start"] is False
    assert payload["production_authorization"] is False


def test_http_protocol_and_local_whitelist_deny_mutations():
    service = RuntimeAuthorityEvidenceService(StatusReader())
    controller = RuntimeAuthorityApiController(service)
    dispatcher = ReadOnlyLocalDispatcher({"RuntimeAuthorityApiController": controller})
    server = build_http_server({"RuntimeAuthorityApiController": controller}, host="127.0.0.1", port=0)
    server.dispatcher = dispatcher
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/v1/runtime/authority?episode=" + EPISODE, timeout=5) as response:
            payload = json.loads(response.read().decode())
            assert response.status == 200
            assert payload["code"] == "OK"
            assert payload["data"]["scope"] == "LOCAL_READ_ONLY_EVIDENCE"
            assert payload["data"]["production_authorization"] is False
        with pytest.raises(HTTPError) as denied:
            urlopen(Request(base + "/api/v1/runtime/authority?episode=" + EPISODE,
                            data=b"{}", method="POST", headers={"Content-Type":"application/json"}), timeout=5)
        assert denied.value.code == 403
        with pytest.raises(HTTPError) as denied:
            urlopen(base + "/api/v1/runtime/authority?episode=LOCAL_missing", timeout=5)
        assert denied.value.code == 404
        with pytest.raises(HTTPError) as denied:
            urlopen(base + "/api/v1/agents", timeout=5)
        assert denied.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)



def test_default_composition_requires_explicit_authority_service():
    from platform.api.default_app import build_default_controllers
    from platform.operations.experience_store import ExperienceStore

    reader=StatusReader()
    kwargs={
        "agent_service":object(),
        "experience_store":ExperienceStore(),
        "runtime_event_service":object(),
        "runtime_status_service":reader,
        "record_stores":object(),
    }
    plain=build_default_controllers(**kwargs)
    assert "RuntimeAuthorityApiController" not in plain
    code,body=PlatformApiDispatcher(plain).dispatch(
        "GET","/api/v1/runtime/authority?episode="+EPISODE)
    assert code==503
    assert body["code"]=="CAPABILITY_NOT_CONFIGURED"

    composed=build_default_controllers(
        **kwargs,runtime_authority_service=RuntimeAuthorityEvidenceService(reader)
    )
    assert "RuntimeAuthorityApiController" in composed
    code,body=PlatformApiDispatcher(composed).dispatch(
        "GET","/api/v1/runtime/authority?episode="+EPISODE)
    assert code==200
    assert body["data"]["episode_ref"]==EPISODE
    assert body["data"]["production_authorization"] is False


def test_http_backend_error_masks_secret_and_does_not_grant_success():
    service = RuntimeAuthorityEvidenceService(
        StatusReader(error=ConnectionError("private-dsn-password")))
    dispatcher = PlatformApiDispatcher({
        "RuntimeAuthorityApiController": RuntimeAuthorityApiController(service),
    })
    status, payload = dispatcher.dispatch("GET", "/api/v1/runtime/authority?episode=" + EPISODE)
    assert status != 200
    assert payload["code"] == "AUTHORITY_STATUS_UNAVAILABLE"
    assert "private-dsn" not in str(payload)
