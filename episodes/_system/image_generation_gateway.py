#!/usr/bin/env python3
"""Only gateway allowed to cross a real image Provider dispatch boundary."""
from __future__ import annotations

from typing import Callable, Any
import subprocess

import generation_attempt_authority as authority
import global_image_capacity


def _provider_outcome_uncertain(error: BaseException) -> bool:
    """Network/CLI timeout may have reached a paid remote Provider.

    A local exception before handoff cannot carry this uncertainty; callers
    also check whether Provider execution actually started.
    """
    return isinstance(error, (TimeoutError, ConnectionError, subprocess.TimeoutExpired))


def provider_generate(ep, lease: dict | None, fencing_token: int | None,
                      provider: str, call: Callable[[], Any]) -> Any:
    # Enforce the machine cap at the only allowed real Provider dispatch edge,
    # even for callers that bypass the normal image worker pool.
    if not isinstance(lease, dict) or fencing_token is None:
        raise authority.AttemptDenied("GENERATION_ATTEMPT_LEASE_REQUIRED")
    with global_image_capacity.image_permits(1):
        return _provider_generate_with_capacity(ep, lease, fencing_token, provider, call)


def _provider_generate_with_capacity(ep, lease: dict | None, fencing_token: int | None,
                                     provider: str, call: Callable[[], Any]) -> Any:
    """Commit a valid durable Lease before invoking the Provider exactly once."""
    if not isinstance(lease, dict) or fencing_token is None:
        raise authority.AttemptDenied("GENERATION_ATTEMPT_LEASE_REQUIRED")
    committed = authority.commit_dispatch(ep, lease, int(fencing_token), provider=provider)
    lease["_phase"] = "DISPATCH_COMMITTED"
    provider_returned = False
    provider_entered = False
    try:
        # A newer Writer/Attempt fence may have appeared after the irreversible
        # dispatch commit but BEFORE any paid Provider operation.
        if authority.validate_committed_dispatch(ep, committed, int(fencing_token)) is not True:
            raise authority.AttemptDenied("STALE_GENERATION_ATTEMPT_FENCE")
        provider_entered = True
        result = call()
        provider_returned = True
        authority.mark_observed(ep, committed, int(fencing_token))
        return result
    except BaseException as exc:
        try:
            if provider_returned or (provider_entered and _provider_outcome_uncertain(exc)):
                # A successful but unrecorded response OR a network/CLI timeout
                # might have consumed a paid generation. Never refund/retry it.
                reason = ("PROVIDER_RECEIPT_PERSISTENCE_FAILED" if provider_returned
                          else "PROVIDER_OUTCOME_UNCERTAIN")
                authority.mark_outcome_unknown(ep, committed, int(fencing_token), reason)
            else:
                authority.fail_after_dispatch(ep, committed, int(fencing_token), type(exc).__name__)
        except Exception:
            # The durable dispatch-commit already consumed this slot. A failure
            # to record the terminal classification must never refund it.
            pass
        lease["_phase"] = "TERMINAL"
        raise


def provider_generate_many(ep, leases: list[dict] | None, provider: str,
                           call: Callable[[], Any]) -> Any:
    if not isinstance(leases, list) or not leases or any(not isinstance(x, dict) for x in leases):
        raise authority.AttemptDenied("GENERATION_ATTEMPT_LEASE_REQUIRED")
    keys = {(x.get("episode_id"), x.get("logical_asset_key")) for x in leases}
    if len(keys) != len(leases):
        raise authority.AttemptDenied("GENERATION_ATTEMPT_DUPLICATE_ASSET_IN_BATCH")
    with global_image_capacity.image_permits(len(leases)):
        return _provider_generate_many_with_capacity(ep, leases, provider, call)


def _provider_generate_many_with_capacity(ep, leases: list[dict] | None, provider: str,
                                          call: Callable[[], Any]) -> Any:
    """Guard one native batch dispatch with one valid lease per Logical Asset."""
    if not isinstance(leases, list) or not leases or any(not isinstance(x, dict) for x in leases):
        raise authority.AttemptDenied("GENERATION_ATTEMPT_LEASE_REQUIRED")
    keys = {(x.get("episode_id"), x.get("logical_asset_key")) for x in leases}
    if len(keys) != len(leases):
        raise authority.AttemptDenied("GENERATION_ATTEMPT_DUPLICATE_ASSET_IN_BATCH")
    committed = []
    provider_returned = False
    provider_entered = False
    observed_count = 0
    try:
        committed = authority.commit_dispatch_many(ep, leases, provider=provider)
        expected = {(x["episode_id"], x["logical_asset_key"]) for x in leases}
        actual = {(x.get("episode_id"), x.get("logical_asset_key")) for x in committed}
        if len(committed) != len(leases) or actual != expected:
            raise authority.AttemptDenied("GENERATION_ATTEMPT_BATCH_COMMIT_INCOMPLETE")
        for lease in leases:
            lease["_phase"] = "DISPATCH_COMMITTED"
        if authority.validate_committed_dispatch_many(ep, committed) is not True:
            raise authority.AttemptDenied("STALE_GENERATION_ATTEMPT_FENCE")
        provider_entered = True
        result = call()
        provider_returned = True
        for lease in committed:
            authority.mark_observed(ep, lease, lease["fencing_token"])
            observed_count += 1
        return result
    except BaseException as exc:
        # Persisted receipts must stay SUCCEEDED; only the unobserved tail
        # can become UNKNOWN. Failed Provider itself has no observed frames.
        remaining = committed[observed_count:] if provider_returned else committed
        for lease in remaining:
            try:
                if provider_returned or (provider_entered and _provider_outcome_uncertain(exc)):
                    reason = ("BATCH_PROVIDER_RECEIPT_PERSISTENCE_FAILED" if provider_returned
                              else "BATCH_PROVIDER_OUTCOME_UNCERTAIN")
                    authority.mark_outcome_unknown(ep, lease, lease["fencing_token"], reason)
                else:
                    authority.fail_after_dispatch(ep, lease, lease["fencing_token"], type(exc).__name__)
            except Exception:
                pass
            lease["_phase"] = "TERMINAL"
        if committed:
            for lease in leases:
                lease["_phase"] = "TERMINAL"
        raise


def recover_existing_raw(*, receipt: dict, generation_key: str) -> dict:
    """Validate the caller supplied an existing Provider receipt; no new Lease."""
    if not isinstance(receipt, dict) or not receipt or not generation_key:
        raise ValueError("EXISTING_GENERATION_EVIDENCE_REQUIRED")
    return {"source": "EXISTING_PROVIDER_RAW", "generation_key": str(generation_key), "receipt": dict(receipt)}


def adopt_user_asset(ep, *, asset_ref: str, logical_asset_key: str) -> dict:
    """Record user supplied pixels as adoption evidence, never as a generation."""
    if not str(asset_ref or "").strip() or not str(logical_asset_key or "").strip():
        raise ValueError("USER_ASSET_ADOPTION_EVIDENCE_REQUIRED")
    from pathlib import Path
    import logical_asset_identity
    ep = Path(ep).resolve()
    key = str(logical_asset_key).strip()
    episode_id = logical_asset_identity.episode_id(ep)
    if not key.startswith(episode_id + "/"):
        raise ValueError("USER_ASSET_ADOPTION_EPISODE_MISMATCH")
    import runtime_observability
    runtime_observability.safe_record_runtime_event(
        ep, "USER_ASSET_ADOPTED", episode_id=episode_id, logical_asset_key=key,
        source="USER_SUPPLIED", evidence_ref=str(asset_ref), attempt_consumed=False,
    )
    return {"source": "USER_SUPPLIED", "asset_ref": str(asset_ref), "logical_asset_key": key,
            "attempt_consumed": False}
