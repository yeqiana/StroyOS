#!/usr/bin/env python3
"""Durable single-inflight authority for real image generation dispatches."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import logical_asset_identity
import runtime_timeout_policy
import storage_config
from platform.repository.mysql.mysql_connection import MySqlConnection
from platform.repository.mysql.schema_v2 import DATABASE_NAME

MAX_REAL_IMAGE_GENERATION_ATTEMPTS_PER_ASSET = 2
DEFAULT_LEASE_SECONDS = 120
TERMINAL = {"SUCCEEDED", "FAILED_AFTER_DISPATCH", "OUTCOME_UNKNOWN"}
_CONNECTION_FACTORY = MySqlConnection


class AttemptDenied(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def _connect():
    return _CONNECTION_FACTORY(**storage_config.mysql_connection_kwargs({"database": DATABASE_NAME}))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime | None = None) -> str:
    return (value or _utcnow()).replace(tzinfo=timezone.utc).isoformat(timespec="microseconds")


def _episode_id(ep: str | Path) -> str:
    return logical_asset_identity.episode_id(ep)


def frame_key(ep: str | Path, frame: str | int) -> str:
    return logical_asset_identity.frame_asset_key(ep, frame)


def stable_generation_key(episode_id: str, logical_asset_key: str, attempt_index: int) -> str:
    digest = hashlib.sha256(f"{episode_id}\x1f{logical_asset_key}".encode("utf-8")).hexdigest()[:48]
    return f"ga1-{digest}-a{int(attempt_index)}"


def _telemetry(ep, event_type: str, lease: dict | None = None, **attrs) -> None:
    try:
        import runtime_observability

        lease = lease or {}
        runtime_observability.safe_record_runtime_event(
            Path(ep), event_type,
            episode_id=_episode_id(ep),
            logical_asset_key=attrs.get("logical_asset_key") or lease.get("logical_asset_key"),
            attempt_index=lease.get("attempt_index"),
            generation_key=lease.get("generation_key"),
            fencing_token=lease.get("fencing_token"),
            lease_token_hash=lease.get("lease_token_hash"),
            model_role=(attrs.get("generation_context") or {}).get("model_role"),
            payload_model=(attrs.get("generation_context") or {}).get("payload_model"),
            model_policy_sha256=(attrs.get("generation_context") or {}).get("model_policy_sha256"),
            status=attrs.get("status"), failure_class=attrs.get("failure_class"),
            attempt_consumed=attrs.get("attempt_consumed"),
            source="generation_attempt_authority",
        )
    except Exception:
        # MySQL remains the only dispatch authority; diagnostics are best effort.
        return


def _context(row: dict) -> dict:
    try:
        value = row.get("CONTEXT")
        return json.loads(value) if isinstance(value, str) else dict(value or {})
    except Exception:
        return {}


def _row(connection, episode_id: str, key: str) -> dict | None:
    return connection.query_one(
        "SELECT EPISODE_ID, LOGICAL_ASSET_KEY, ATTEMPTS_CONSUMED, ACTIVE_ATTEMPT_INDEX, FENCING_COUNTER "
        "FROM TB_GENERATION_ASSET_STATE WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s FOR UPDATE",
        (episode_id, key),
    )


def _ensure_state(connection, episode_id: str, key: str, legacy_consumed: int = 0) -> dict:
    connection.execute(
        "INSERT IGNORE INTO TB_GENERATION_ASSET_STATE (EPISODE_ID, LOGICAL_ASSET_KEY, ATTEMPTS_CONSUMED) VALUES (%s,%s,%s)",
        (episode_id, key, max(0, min(255, int(legacy_consumed)))),
    )
    row = _row(connection, episode_id, key)
    if not row:
        raise RuntimeError("GENERATION_ATTEMPT_STATE_UNAVAILABLE")
    return row


def _previous_attempt_denial(connection, episode_id: str, key: str,
                             attempts_consumed: int) -> str | None:
    """Refuse a new dispatch while the latest consumed attempt is unresolved.

    Scheduler and Driver preflights are useful UX gates, but this final check
    belongs beside the MySQL reservation mutex so direct callers cannot turn an
    expired DISPATCH_COMMITTED attempt into a second provider call.  A terminal
    receipt reconciliation must first move UNKNOWN to a verified terminal
    result; this helper never edits attempt history or grants retry authority.
    """
    index = int(attempts_consumed or 0)
    if index <= 0:
        return None
    row = connection.query_one(
        "SELECT STATUS FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s "
        "AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s FOR UPDATE",
        (episode_id, key, index),
    )
    if not row:
        return "GENERATION_ATTEMPT_PREVIOUS_HISTORY_MISSING"
    status = str(row.get("STATUS") or "")
    if status == "OUTCOME_UNKNOWN":
        return "GENERATION_ATTEMPT_OUTCOME_UNKNOWN_RECONCILIATION_REQUIRED"
    if status not in {"SUCCEEDED", "FAILED_AFTER_DISPATCH"}:
        return "GENERATION_ATTEMPT_PREVIOUS_STATUS_UNRECONCILED"
    return None


def _expire_active(connection, episode_id: str, key: str, state: dict, ep: Path) -> dict:
    index = state.get("ACTIVE_ATTEMPT_INDEX")
    if index is None:
        return state
    row = connection.query_one(
        "SELECT * FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s FOR UPDATE",
        (episode_id, key, int(index)),
    )
    if not row:
        connection.execute(
            "UPDATE TB_GENERATION_ASSET_STATE SET ACTIVE_ATTEMPT_INDEX=NULL WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s",
            (episode_id, key),
        )
        state["ACTIVE_ATTEMPT_INDEX"] = None
        return state
    now = _utcnow()
    expiry = row.get("LEASE_EXPIRES_AT")
    if expiry and expiry > now:
        raise AttemptDenied("GENERATION_ATTEMPT_ALREADY_ACTIVE", f"attempt={index}")
    status = str(row.get("STATUS") or "")
    if status == "RESERVED":
        connection.execute(
            "UPDATE TB_GENERATION_ATTEMPT SET STATUS='RELEASED_PRE_DISPATCH', TERMINAL_AT=%s, FAILURE_CLASS='LEASE_EXPIRED_PRE_DISPATCH' "
            "WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s AND STATUS='RESERVED'",
            (now, episode_id, key, int(index)),
        )
        _telemetry(ep, "ATTEMPT_RELEASED_PRE_DISPATCH",
                   {"episode_id": episode_id, "logical_asset_key": key, "attempt_index": int(index),
                    "generation_key": row.get("GENERATION_KEY"), "fencing_token": row.get("FENCING_TOKEN"),
                    "lease_token_hash": row.get("LEASE_TOKEN")}, generation_context=_context(row), failure_class="LEASE_EXPIRED_PRE_DISPATCH", attempt_consumed=False)
    elif status == "DISPATCH_COMMITTED":
        connection.execute(
            "UPDATE TB_GENERATION_ATTEMPT SET STATUS='OUTCOME_UNKNOWN', TERMINAL_AT=%s, FAILURE_CLASS='LEASE_EXPIRED_POST_DISPATCH' "
            "WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s AND STATUS='DISPATCH_COMMITTED'",
            (now, episode_id, key, int(index)),
        )
        _telemetry(ep, "ATTEMPT_OUTCOME_UNKNOWN",
                   {"episode_id": episode_id, "logical_asset_key": key, "attempt_index": int(index),
                    "generation_key": row.get("GENERATION_KEY"), "fencing_token": row.get("FENCING_TOKEN"),
                    "lease_token_hash": row.get("LEASE_TOKEN")}, generation_context=_context(row), failure_class="LEASE_EXPIRED_POST_DISPATCH", status="OUTCOME_UNKNOWN", attempt_consumed=True)
    connection.execute(
        "UPDATE TB_GENERATION_ASSET_STATE SET ACTIVE_ATTEMPT_INDEX=NULL WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s",
        (episode_id, key),
    )
    state["ACTIVE_ATTEMPT_INDEX"] = None
    return state


def _reserve_impl(ep: str | Path, logical_asset_key: str, generation_context: dict | None = None, *, lease_seconds: int = DEFAULT_LEASE_SECONDS, legacy_consumed: int = 0) -> dict:
    """Atomically reserve the next hard-capped attempt and one active lease."""
    ep = Path(ep).resolve()
    key = str(logical_asset_key or "").strip()
    if not key or not key.startswith(_episode_id(ep) + "/"):
        raise ValueError("logical_asset_key must be hierarchical under this Episode")
    if int(lease_seconds) < 1:
        raise ValueError("lease_seconds must be positive")
    episode_id = _episode_id(ep)
    context = dict(generation_context or {})
    _telemetry(ep, "ATTEMPT_REQUESTED", generation_context=context, logical_asset_key=key)
    token = secrets.token_hex(32)
    now = _utcnow()
    expires = now + timedelta(seconds=int(lease_seconds))
    connection = _connect()
    try:
        # Create the mutex row in autocommit mode so two first writers do not
        # deadlock while each holds an INSERT-IGNORE duplicate-key lock.
        connection.execute(
            "INSERT IGNORE INTO TB_GENERATION_ASSET_STATE (EPISODE_ID, LOGICAL_ASSET_KEY, ATTEMPTS_CONSUMED) VALUES (%s,%s,%s)",
            (episode_id, key, max(0, min(255, int(legacy_consumed)))),
        )
        if int(legacy_consumed) > 0:
            connection.execute(
                "UPDATE TB_GENERATION_ASSET_STATE SET ATTEMPTS_CONSUMED=GREATEST(ATTEMPTS_CONSUMED,%s) WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s",
                (max(0, min(255, int(legacy_consumed))), episode_id, key),
            )
        with connection.transaction():
            state = _row(connection, episode_id, key)
            if not state:
                raise RuntimeError("GENERATION_ATTEMPT_STATE_UNAVAILABLE")
            try:
                import production_revision_authority
                production_revision_authority.validate_dispatch_binding(connection, episode_id, context, key)
            except production_revision_authority.ProductionRevisionDenied as exc:
                raise AttemptDenied(str(exc)) from exc
            state = _expire_active(connection, episode_id, key, state, ep)
            consumed = int(state.get("ATTEMPTS_CONSUMED") or 0)
            # Defer denial until after the transaction commits. In particular,
            # _expire_active() may have just persisted DISPATCH_COMMITTED ->
            # OUTCOME_UNKNOWN; rolling that back would erase the evidence while
            # still returning a blocked dispatch.
            # Legacy consumed quota may predate individual Attempt history rows.
            # A hard cap denies without falsely reporting missing history.
            budget_denial = consumed >= MAX_REAL_IMAGE_GENERATION_ATTEMPTS_PER_ASSET
            history_denial = (None if budget_denial else
                              _previous_attempt_denial(connection, episode_id, key, consumed))
            if history_denial:
                lease = None
            elif budget_denial:
                lease = None
            else:
                index = consumed + 1
                fencing = int(state.get("FENCING_COUNTER") or 0) + 1
                generation_key = stable_generation_key(episode_id, key, index)
                old = connection.query_one(
                    "SELECT STATUS FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s FOR UPDATE",
                    (episode_id, key, index),
                )
                if old and str(old.get("STATUS")) not in {"RELEASED_PRE_DISPATCH"}:
                    raise AttemptDenied("GENERATION_ATTEMPT_ALREADY_ACTIVE", f"generation_key={generation_key}")
                digest = hashlib.sha256(token.encode("ascii")).hexdigest()
                payload = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if old:
                    connection.execute(
                        "UPDATE TB_GENERATION_ATTEMPT SET GENERATION_KEY=%s, LEASE_TOKEN=%s, FENCING_TOKEN=%s, STATUS='RESERVED', "
                        "REQUESTED_AT=%s, RESERVED_AT=%s, LEASE_EXPIRES_AT=%s, DISPATCH_COMMITTED_AT=NULL, GENERATION_OBSERVED_AT=NULL, "
                        "TERMINAL_AT=NULL, MODEL_ROLE=%s, MODEL_POLICY_SHA256=%s, CONTROLLER_MODEL=%s, PAYLOAD_MODEL=%s, PAYLOAD_QUALITY=%s, "
                        "PROVIDER=%s, FAILURE_CLASS=NULL, RESULT_REF=NULL, CONTEXT=%s "
                        "WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s",
                        (generation_key, digest, fencing, now, now, expires, context.get("model_role"), context.get("model_policy_sha256"),
                         context.get("controller_model"), context.get("payload_model"), context.get("payload_quality"), context.get("provider"),
                         payload, episode_id, key, index),
                    )
                else:
                    connection.execute(
                        "INSERT INTO TB_GENERATION_ATTEMPT (EPISODE_ID, LOGICAL_ASSET_KEY, ATTEMPT_INDEX, GENERATION_KEY, LEASE_TOKEN, FENCING_TOKEN, "
                        "STATUS, REQUESTED_AT, RESERVED_AT, LEASE_EXPIRES_AT, MODEL_ROLE, MODEL_POLICY_SHA256, CONTROLLER_MODEL, PAYLOAD_MODEL, "
                        "PAYLOAD_QUALITY, PROVIDER, CONTEXT) VALUES (%s,%s,%s,%s,%s,%s,'RESERVED',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (episode_id, key, index, generation_key, digest, fencing, now, now, expires, context.get("model_role"),
                         context.get("model_policy_sha256"), context.get("controller_model"), context.get("payload_model"),
                         context.get("payload_quality"), context.get("provider"), payload),
                    )
                connection.execute(
                    "UPDATE TB_GENERATION_ASSET_STATE SET ACTIVE_ATTEMPT_INDEX=%s,FENCING_COUNTER=%s WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s",
                    (index, fencing, episode_id, key),
                )
                lease = {"episode_id": episode_id, "logical_asset_key": key, "attempt_index": index,
                         "generation_key": generation_key, "lease_token": token, "lease_token_hash": digest,
                         "fencing_token": fencing, "lease_expires_at": _iso(expires), "generation_context": context}
        if history_denial:
            raise AttemptDenied(history_denial)
        if budget_denial:
            raise AttemptDenied("GENERATION_ATTEMPT_BUDGET_EXHAUSTED", f"consumed={consumed}")
        _telemetry(ep, "ATTEMPT_RESERVED", lease, attempt_consumed=False)
        return lease
    except AttemptDenied as exc:
        event = "ATTEMPT_DENIED_BUDGET" if exc.code == "GENERATION_ATTEMPT_BUDGET_EXHAUSTED" else (
            "ATTEMPT_DENIED_ACTIVE" if exc.code == "GENERATION_ATTEMPT_ALREADY_ACTIVE" else "ATTEMPT_DENIED_STALE_FENCE")
        _telemetry(ep, event, generation_context=context, logical_asset_key=key, status=exc.code)
        raise
    finally:
        connection.close()


def reserve(ep: str | Path, logical_asset_key: str, generation_context: dict | None = None, *,
            lease_seconds: int = DEFAULT_LEASE_SECONDS, legacy_consumed: int = 0) -> dict:
    """Reserve an image attempt, serializing Phase5A retirement with reserve.

    Ordinary Episodes retain the database-only authority contract. A marked
    Phase5A canary additionally shares its validation-epoch file lock with the
    retirement operation, so no reserve can race past a retirement decision.
    """
    episode = Path(ep).resolve()
    marker = episode / "meta" / "phase5a-canary.json"
    if marker.is_file():
        import phase5a_collaborative_canary
        from runtime_atomic_store import FileLock

        with FileLock(
            phase5a_collaborative_canary.validation_epoch_lock_target(episode),
            timeout=runtime_timeout_policy.seconds("authority_lock"), stale_seconds=3600,
        ):
            phase5a_collaborative_canary.assert_validation_epoch_dispatch_eligible(episode)
            return _reserve_impl(
                episode, logical_asset_key, generation_context,
                lease_seconds=lease_seconds, legacy_consumed=legacy_consumed,
            )
    return _reserve_impl(
        episode, logical_asset_key, generation_context,
        lease_seconds=lease_seconds, legacy_consumed=legacy_consumed,
    )


def _locked_lease(connection, lease: dict, fencing_token: int) -> tuple[dict, dict]:
    episode_id, key, index = str(lease["episode_id"]), str(lease["logical_asset_key"]), int(lease["attempt_index"])
    state = _row(connection, episode_id, key)
    try:
        import production_revision_authority
        production_revision_authority.validate_dispatch_binding(
            connection, episode_id, dict(lease.get("generation_context") or {}), key)
    except production_revision_authority.ProductionRevisionDenied as exc:
        raise AttemptDenied(str(exc)) from exc
    row = connection.query_one(
        "SELECT * FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s FOR UPDATE",
        (episode_id, key, index),
    )
    if not row or not state or int(row.get("FENCING_TOKEN") or 0) != int(fencing_token) or int(state.get("FENCING_COUNTER") or 0) != int(fencing_token) or str(row.get("LEASE_TOKEN")) != str(lease.get("lease_token_hash")) or int(state.get("ACTIVE_ATTEMPT_INDEX") or 0) != index:
        raise AttemptDenied("STALE_GENERATION_ATTEMPT_FENCE")
    return state, row


def commit_dispatch(ep: str | Path, lease: dict, fencing_token: int, *, provider: str | None = None) -> dict:
    """Irreversibly consume this slot at the exact provider dispatch boundary."""
    connection = _connect()
    now = _utcnow()
    try:
        with connection.transaction():
            state, row = _locked_lease(connection, lease, fencing_token)
            if row.get("STATUS") != "RESERVED" or row.get("LEASE_EXPIRES_AT") <= now:
                raise AttemptDenied("STALE_GENERATION_ATTEMPT_FENCE")
            connection.execute(
                "UPDATE TB_GENERATION_ATTEMPT SET STATUS='DISPATCH_COMMITTED',DISPATCH_COMMITTED_AT=%s,PROVIDER=COALESCE(%s,PROVIDER) "
                "WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s AND STATUS='RESERVED'",
                (now, provider, lease["episode_id"], lease["logical_asset_key"], lease["attempt_index"]),
            )
            updated = connection.execute(
                "UPDATE TB_GENERATION_ASSET_STATE SET ATTEMPTS_CONSUMED=ATTEMPTS_CONSUMED+1 WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPTS_CONSUMED < 2",
                (lease["episode_id"], lease["logical_asset_key"]),
            )
            if updated != 1:
                raise AttemptDenied("GENERATION_ATTEMPT_BUDGET_EXHAUSTED")
        _telemetry(ep, "WORKER_DISPATCH_COMMITTED", lease, generation_context=lease.get("generation_context"), attempt_consumed=True)
        return {**lease, "status": "DISPATCH_COMMITTED", "attempt_consumed": True, "provider": provider}
    except AttemptDenied as exc:
        _telemetry(ep, "ATTEMPT_DENIED_STALE_FENCE", lease, status=exc.code, failure_class=exc.code)
        raise
    finally:
        connection.close()


def commit_dispatch_many(ep: str | Path, leases: list[dict], *, provider: str | None = None) -> list[dict]:
    """Atomically commit every asset in one native batch, or commit none."""
    if not leases or len({(x.get("episode_id"), x.get("logical_asset_key")) for x in leases}) != len(leases):
        raise AttemptDenied("GENERATION_ATTEMPT_LEASE_REQUIRED")
    connection = _connect()
    committed = []
    try:
        with connection.transaction():
            for lease in sorted(leases, key=lambda x: (str(x.get("episode_id")), str(x.get("logical_asset_key")))):
                fence = int(lease.get("fencing_token") or 0)
                _state, row = _locked_lease(connection, lease, fence)
                if row.get("STATUS") != "RESERVED" or row.get("LEASE_EXPIRES_AT") <= _utcnow():
                    raise AttemptDenied("STALE_GENERATION_ATTEMPT_FENCE")
            for lease in leases:
                connection.execute(
                    "UPDATE TB_GENERATION_ATTEMPT SET STATUS='DISPATCH_COMMITTED',DISPATCH_COMMITTED_AT=%s,PROVIDER=COALESCE(%s,PROVIDER) WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s AND STATUS='RESERVED'",
                    (_utcnow(), provider, lease["episode_id"], lease["logical_asset_key"], lease["attempt_index"]),
                )
                updated = connection.execute(
                    "UPDATE TB_GENERATION_ASSET_STATE SET ATTEMPTS_CONSUMED=ATTEMPTS_CONSUMED+1 WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPTS_CONSUMED < 2",
                    (lease["episode_id"], lease["logical_asset_key"]),
                )
                if updated != 1:
                    raise AttemptDenied("GENERATION_ATTEMPT_BUDGET_EXHAUSTED")
                committed.append({**lease, "status": "DISPATCH_COMMITTED", "attempt_consumed": True, "provider": provider})
        for lease in committed:
            _telemetry(ep, "WORKER_DISPATCH_COMMITTED", lease, generation_context=lease.get("generation_context"), attempt_consumed=True)
        return committed
    except AttemptDenied as exc:
        for lease in leases:
            _telemetry(ep, "ATTEMPT_DENIED_STALE_FENCE", lease, status=exc.code, failure_class=exc.code)
        raise
    finally:
        connection.close()


def validate_committed_dispatch(ep: str | Path, lease: dict, fencing_token: int) -> bool:
    """Read-only final fence check immediately before the paid Provider call.

    The attempt has already been irreversibly committed; a newer owner might
    fence it before the actual native image dispatch. In that case NEVER call
    the Provider, and never refund/release the consumed attempt.
    """
    connection = _connect()
    try:
        with connection.transaction():
            _state, row = _locked_lease(connection, lease, int(fencing_token))
            if row.get("STATUS") != "DISPATCH_COMMITTED":
                raise AttemptDenied("STALE_GENERATION_ATTEMPT_FENCE")
        return True
    finally:
        connection.close()


def validate_committed_dispatch_many(ep: str | Path, leases: list[dict]) -> bool:
    """Check every committed image from one native batch under one DB transaction."""
    if not isinstance(leases, list) or not leases:
        raise AttemptDenied("GENERATION_ATTEMPT_LEASE_REQUIRED")
    if len({(x.get("episode_id"), x.get("logical_asset_key")) for x in leases
            if isinstance(x, dict)}) != len(leases):
        raise AttemptDenied("GENERATION_ATTEMPT_DUPLICATE_ASSET_IN_BATCH")
    connection = _connect()
    try:
        with connection.transaction():
            for lease in sorted(leases, key=lambda x: (
                    str(x.get("episode_id")), str(x.get("logical_asset_key")))):
                _state, row = _locked_lease(connection, lease, int(lease["fencing_token"]))
                if row.get("STATUS") != "DISPATCH_COMMITTED":
                    raise AttemptDenied("STALE_GENERATION_ATTEMPT_FENCE")
        return True
    finally:
        connection.close()


def release_pre_dispatch(ep: str | Path, lease: dict, fencing_token: int, reason: str = "") -> dict:
    connection = _connect()
    try:
        with connection.transaction():
            _state, row = _locked_lease(connection, lease, fencing_token)
            if row.get("STATUS") != "RESERVED":
                raise AttemptDenied("GENERATION_ATTEMPT_ALREADY_COMMITTED")
            connection.execute(
                "UPDATE TB_GENERATION_ATTEMPT SET STATUS='RELEASED_PRE_DISPATCH',TERMINAL_AT=%s,FAILURE_CLASS=%s "
                "WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s",
                (_utcnow(), str(reason or "PRE_DISPATCH_FAILURE")[:64], lease["episode_id"], lease["logical_asset_key"], lease["attempt_index"]),
            )
            connection.execute(
                "UPDATE TB_GENERATION_ASSET_STATE SET ACTIVE_ATTEMPT_INDEX=NULL WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s",
                (lease["episode_id"], lease["logical_asset_key"]),
            )
        _telemetry(ep, "ATTEMPT_RELEASED_PRE_DISPATCH", lease, failure_class=reason, attempt_consumed=False)
        return {**lease, "status": "RELEASED_PRE_DISPATCH", "attempt_consumed": False}
    finally:
        connection.close()


def _terminal(ep: str | Path, lease: dict, fencing_token: int, status: str, *, failure_class: str | None = None, result_ref: str | None = None) -> dict:
    if status not in TERMINAL:
        raise ValueError(f"invalid terminal status: {status}")
    connection = _connect()
    try:
        with connection.transaction():
            _state = _row(connection, str(lease["episode_id"]), str(lease["logical_asset_key"]))
            existing = connection.query_one(
                "SELECT STATUS,LEASE_TOKEN,FENCING_TOKEN FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s FOR UPDATE",
                (lease["episode_id"], lease["logical_asset_key"], lease["attempt_index"]),
            )
            if (existing and str(existing.get("STATUS")) == status
                    and int(existing.get("FENCING_TOKEN") or 0) == int(fencing_token)
                    and str(existing.get("LEASE_TOKEN")) == str(lease.get("lease_token_hash"))):
                return {**lease, "status": status, "attempt_consumed": True, "idempotent": True}
            _state, row = _locked_lease(connection, lease, fencing_token)
            if row.get("STATUS") != "DISPATCH_COMMITTED":
                if row.get("STATUS") == status:
                    return {**lease, "status": status, "attempt_consumed": True, "idempotent": True}
                raise AttemptDenied("GENERATION_ATTEMPT_NOT_DISPATCHED")
            connection.execute(
                "UPDATE TB_GENERATION_ATTEMPT SET STATUS=%s,TERMINAL_AT=%s,FAILURE_CLASS=%s,RESULT_REF=%s "
                "WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s AND STATUS='DISPATCH_COMMITTED'",
                (status, _utcnow(), failure_class, result_ref, lease["episode_id"], lease["logical_asset_key"], lease["attempt_index"]),
            )
            connection.execute(
                "UPDATE TB_GENERATION_ASSET_STATE SET ACTIVE_ATTEMPT_INDEX=NULL WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s",
                (lease["episode_id"], lease["logical_asset_key"]),
            )
        event = {"SUCCEEDED": "ATTEMPT_SUCCEEDED", "FAILED_AFTER_DISPATCH": "ATTEMPT_FAILED_AFTER_DISPATCH", "OUTCOME_UNKNOWN": "ATTEMPT_OUTCOME_UNKNOWN"}[status]
        _telemetry(ep, event, lease, failure_class=failure_class, status=status, attempt_consumed=True)
        return {**lease, "status": status, "attempt_consumed": True}
    finally:
        connection.close()


def mark_observed(ep: str | Path, lease: dict, fencing_token: int) -> dict:
    connection = _connect()
    try:
        with connection.transaction():
            _state, row = _locked_lease(connection, lease, fencing_token)
            if row.get("STATUS") != "DISPATCH_COMMITTED":
                raise AttemptDenied("GENERATION_ATTEMPT_NOT_DISPATCHED")
            connection.execute(
                "UPDATE TB_GENERATION_ATTEMPT SET GENERATION_OBSERVED_AT=%s WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s",
                (_utcnow(), lease["episode_id"], lease["logical_asset_key"], lease["attempt_index"]),
            )
        _telemetry(ep, "IMAGE_GENERATION_OBSERVED", lease, status="OBSERVED")
        return {**lease, "status": "DISPATCH_COMMITTED", "observed": True}
    finally:
        connection.close()


def succeed(ep, lease, fencing_token, *, result_ref: str | None = None) -> dict:
    return _terminal(ep, lease, fencing_token, "SUCCEEDED", result_ref=result_ref)


def fail_after_dispatch(ep, lease, fencing_token, failure_class: str) -> dict:
    return _terminal(ep, lease, fencing_token, "FAILED_AFTER_DISPATCH", failure_class=failure_class)


def mark_outcome_unknown(ep, lease, fencing_token, failure_class: str = "OUTCOME_UNKNOWN") -> dict:
    return _terminal(ep, lease, fencing_token, "OUTCOME_UNKNOWN", failure_class=failure_class)


def complete_external_generation(ep: str | Path, logical_asset_key: str, generation_key: str, *, result_ref: str | None = None) -> dict:
    """Close a host-dispatched attempt by its persisted idempotency key."""
    connection = _connect()
    try:
        with connection.transaction():
            state = _row(connection, _episode_id(ep), str(logical_asset_key))
            row = connection.query_one(
                "SELECT * FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND GENERATION_KEY=%s FOR UPDATE",
                (_episode_id(ep), str(logical_asset_key), str(generation_key)),
            )
            if not row:
                raise AttemptDenied("GENERATION_ATTEMPT_NOT_FOUND")
            if row.get("STATUS") == "SUCCEEDED":
                return {"generation_key": generation_key, "status": "SUCCEEDED", "attempt_consumed": True, "idempotent": True}
            if (not state or row.get("STATUS") != "DISPATCH_COMMITTED"
                    or int(state.get("FENCING_COUNTER") or 0) != int(row.get("FENCING_TOKEN") or 0)
                    or int(state.get("ACTIVE_ATTEMPT_INDEX") or 0) != int(row.get("ATTEMPT_INDEX") or 0)):
                raise AttemptDenied("STALE_GENERATION_ATTEMPT_FENCE")
            connection.execute(
                "UPDATE TB_GENERATION_ATTEMPT SET STATUS='SUCCEEDED',TERMINAL_AT=%s,RESULT_REF=%s WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s AND STATUS='DISPATCH_COMMITTED'",
                (_utcnow(), result_ref, _episode_id(ep), str(logical_asset_key), int(row["ATTEMPT_INDEX"])),
            )
            connection.execute(
                "UPDATE TB_GENERATION_ASSET_STATE SET ACTIVE_ATTEMPT_INDEX=NULL WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s",
                (_episode_id(ep), str(logical_asset_key)),
            )
        lease = {"episode_id": _episode_id(ep), "logical_asset_key": str(logical_asset_key),
                 "attempt_index": int(row["ATTEMPT_INDEX"]), "generation_key": str(generation_key),
                 "fencing_token": int(row["FENCING_TOKEN"]), "lease_token_hash": row.get("LEASE_TOKEN"),
                 "generation_context": {"model_role": row.get("MODEL_ROLE"), "payload_model": row.get("PAYLOAD_MODEL"),
                                        "model_policy_sha256": row.get("MODEL_POLICY_SHA256")}}
        _telemetry(ep, "ATTEMPT_SUCCEEDED", lease, status="SUCCEEDED")
        return {**lease, "status": "SUCCEEDED", "attempt_consumed": True}
    finally:
        connection.close()


def load_asset_state(ep: str | Path, logical_asset_key: str) -> dict:
    connection = _connect()
    try:
        row = connection.query_one(
            "SELECT * FROM TB_GENERATION_ASSET_STATE WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s",
            (_episode_id(ep), str(logical_asset_key)),
        ) or {"ATTEMPTS_CONSUMED": 0, "ACTIVE_ATTEMPT_INDEX": None, "FENCING_COUNTER": 0}
        return {"episode_id": _episode_id(ep), "logical_asset_key": str(logical_asset_key),
                "attempts_consumed": int(row.get("ATTEMPTS_CONSUMED") or 0),
                "active_attempt_index": row.get("ACTIVE_ATTEMPT_INDEX"),
                "fencing_counter": int(row.get("FENCING_COUNTER") or 0),
                "remaining_attempts": max(0, MAX_REAL_IMAGE_GENERATION_ATTEMPTS_PER_ASSET - int(row.get("ATTEMPTS_CONSUMED") or 0))}
    finally:
        connection.close()


def load_attempt(ep: str | Path, logical_asset_key: str, attempt_index: int) -> dict | None:
    connection = _connect()
    try:
        row = connection.query_one(
            "SELECT * FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s "
            "AND ATTEMPT_INDEX=%s",
            (_episode_id(ep), str(logical_asset_key), int(attempt_index)),
        )
        if not row:
            return None
        return {
            "episode_id": row.get("EPISODE_ID"),
            "logical_asset_key": row.get("LOGICAL_ASSET_KEY"),
            "attempt_index": int(row.get("ATTEMPT_INDEX") or 0),
            "generation_key": row.get("GENERATION_KEY"),
            "status": row.get("STATUS"),
            "dispatch_committed_at": row.get("DISPATCH_COMMITTED_AT"),
            "generation_observed_at": row.get("GENERATION_OBSERVED_AT"),
            "terminal_at": row.get("TERMINAL_AT"),
            "failure_class": row.get("FAILURE_CLASS"),
            "result_ref": row.get("RESULT_REF"),
            "provider": row.get("PROVIDER"),
            "payload_model": row.get("PAYLOAD_MODEL"),
            "payload_quality": row.get("PAYLOAD_QUALITY"),
        }
    finally:
        connection.close()


def remaining(ep: str | Path, logical_asset_key: str) -> int:
    return int(load_asset_state(ep, logical_asset_key)["remaining_attempts"])


def episode_hard_generation_cap(logical_asset_keys: list[str] | tuple[str, ...] | set[str]) -> int:
    """Return an audit-only aggregate ceiling; per-asset rows remain authoritative."""
    keys = {str(key or "").strip() for key in logical_asset_keys}
    if "" in keys:
        raise ValueError("logical asset keys must be non-empty")
    return len(keys) * MAX_REAL_IMAGE_GENERATION_ATTEMPTS_PER_ASSET


def semantic_attempt_consumed(ep: str | Path, logical_asset_key: str, semantic_key: str) -> bool:
    connection = _connect()
    try:
        row = connection.query_one(
            "SELECT ATTEMPT_INDEX FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s "
            "AND JSON_UNQUOTE(JSON_EXTRACT(CONTEXT,'$.semantic_key'))=%s "
            "AND STATUS IN ('DISPATCH_COMMITTED','SUCCEEDED','FAILED_AFTER_DISPATCH','OUTCOME_UNKNOWN') LIMIT 1",
            (_episode_id(ep), str(logical_asset_key), str(semantic_key).lower()),
        )
        return bool(row)
    finally:
        connection.close()
