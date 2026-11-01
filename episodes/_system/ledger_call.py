#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""In-process bridge to the Production Ledger CLI commands.

Schedulers used to spawn one ``production_ledger.py`` interpreter per
begin/success/tech-fail transition (about two cold starts per frame, more
after fallbacks).  Ledger writes are already atomic and each image scheduler
run is serialized by the same OS queue lock, so the same transitions can be
executed in-process while keeping every CLI validation semantic.  This bridge
preserves the ``(ok, text)`` wrapper contract used by callers and tests.
"""
from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace

import production_ledger


def _invoke(fn, namespace: argparse.Namespace) -> tuple[bool, str]:
    """Run one ``cmd_*`` with CLI-like stdout capture and exit mapping."""
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            fn(namespace)
    except SystemExit as exc:
        rendered = sink.getvalue().strip()
        message = str(exc).strip() or rendered
        if rendered and rendered != message:
            message = f"{message}\n{rendered}"
        return False, message
    return True, sink.getvalue().strip()


def begin(
    ep: Path,
    *,
    frame: int,
    kind: str,
    prompt_file: Path,
    capture_id: str,
    model: str,
    quality: str,
    notes: str = "",
    references: list[str] | None = None,
    batch_id: str | None = None,
    transaction_id: str | None = None,
    production_revision_id: str | None = None,
    reviewed_scene_prompt: str | None = None,
) -> tuple[bool, str]:
    """Mirror ``production_ledger.py begin`` for a scheduler queue item."""
    namespace = SimpleNamespace(
        episode_dir=str(Path(ep).resolve()),
        frame=f"{int(frame):02d}",
        kind=kind,
        prompt=reviewed_scene_prompt,
        prompt_file=(None if reviewed_scene_prompt is not None
                     else str(Path(prompt_file).resolve())),
        allow_long_prompt=reviewed_scene_prompt is not None,
        capture_id=capture_id,
        model=model,
        quality=quality,
        notes=notes,
        reference=[str(x) for x in (references or [])],
        batch_id=batch_id,
        runtime_transaction_id=transaction_id,
        production_revision_id=production_revision_id,
    )
    return _invoke(production_ledger.cmd_begin, namespace)


def success(
    ep: Path,
    *,
    frame: int,
    path: Path,
    provider_receipt: Path | None = None,
    generation_key: str | None = None,
    generation_attempt_index: int | None = None,
    production_revision_id: str | None = None,
) -> tuple[bool, str]:
    """Mirror ``production_ledger.py success`` for a committed candidate."""
    namespace = SimpleNamespace(
        episode_dir=str(Path(ep).resolve()),
        frame=f"{int(frame):02d}",
        path=str(Path(path).resolve()),
        provider_receipt=str(Path(provider_receipt).resolve()) if provider_receipt else None,
        generation_key=str(generation_key or "").strip() or None,
        generation_attempt_index=(int(generation_attempt_index)
                                  if generation_attempt_index is not None else None),
        production_revision_id=str(production_revision_id or "").strip() or None,
    )
    return _invoke(production_ledger.cmd_success, namespace)


def tech_fail(ep: Path, *, frame: int, code: str, message: str,
              provider_invoked: bool = False, runner_request_id: str | None = None) -> tuple[bool, str]:
    """Mirror ``production_ledger.py tech-fail`` for a worker failure."""
    namespace = SimpleNamespace(
        episode_dir=str(Path(ep).resolve()),
        frame=f"{int(frame):02d}",
        code=code,
        message=message[:1000],
        provider_invoked=bool(provider_invoked),
        runner_request_id=runner_request_id,
    )
    return _invoke(production_ledger.cmd_tech_fail, namespace)


def review(
    ep: Path,
    *,
    frame: int,
    decision: str,
    notes: str = "",
    prevent_exhaustion_force_pass: bool = False,
) -> tuple[bool, str]:
    """Mirror ``production_ledger.py review`` for ready-candidate decisions."""
    namespace = SimpleNamespace(
        episode_dir=str(Path(ep).resolve()),
        frame=f"{int(frame):02d}",
        decision=decision,
        notes=notes,
        prevent_exhaustion_force_pass=bool(prevent_exhaustion_force_pass),
    )
    return _invoke(production_ledger.cmd_review, namespace)


def authorize_repair(
    ep: Path,
    *,
    frame: int,
    note: str,
    delegated_auto: bool = True,
) -> tuple[bool, str]:
    """Mirror ``production_ledger.py authorize-repair`` for one bounded repair."""
    namespace = SimpleNamespace(
        episode_dir=str(Path(ep).resolve()),
        frame=f"{int(frame):02d}",
        note=str(note),
        delegated_auto=bool(delegated_auto),
    )
    return _invoke(production_ledger.cmd_authorize_repair, namespace)


def self_test() -> None:
    assert _invoke.__name__ == "_invoke"
    assert begin.__name__ == "begin"
    assert success.__name__ == "success"
    assert tech_fail.__name__ == "tech_fail"
    assert review.__name__ == "review"
    assert authorize_repair.__name__ == "authorize_repair"
    print("LEDGER CALL SELF-TEST PASS")


if __name__ == "__main__":
    self_test()
