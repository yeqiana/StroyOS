"""Windows source-file freeze for one-off native Frame01 CAS reconciliation.

Keep read-only OS handles open until the MySQL transaction has committed or
rolled back. FILE_SHARE_READ deliberately denies concurrent write and rename.
This is a local Windows filesystem guard, not distributed storage fencing.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path


class NativeSourceFreezeDenied(RuntimeError):
    """Fail closed if any immutable source cannot be frozen."""


SOURCE_KEYS = (
    "evidence_path", "raw", "candidate", "codex_log",
    "runner_receipt", "source_generated_path",
)


def source_paths(verified: dict) -> tuple[Path, ...]:
    """Select the six provenance inputs already validated by the verifier."""
    paths = []
    for key in SOURCE_KEYS:
        value = verified.get(key)
        if not isinstance(value, Path) or not value.is_absolute() or not value.is_file():
            raise NativeSourceFreezeDenied("NATIVE_RECONCILIATION_SOURCE_FREEZE_INPUT_INVALID")
        paths.append(value.resolve())
    if len(set(paths)) != len(SOURCE_KEYS):
        raise NativeSourceFreezeDenied("NATIVE_RECONCILIATION_SOURCE_FREEZE_DUPLICATE")
    return tuple(sorted(paths, key=lambda p: str(p).casefold()))


def _windows_open_shared_read(path: Path):
    """Open a non-delete-sharing, non-write-sharing Windows file handle."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    kernel.CreateFileW.restype = wintypes.HANDLE
    handle = kernel.CreateFileW(str(path), 0x80000000, 0x00000001, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value or handle is None:
        raise NativeSourceFreezeDenied("NATIVE_RECONCILIATION_SOURCE_FREEZE_OPEN_FAILED")
    return handle


def _windows_close(handle) -> None:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.CloseHandle(handle)


@contextmanager
def freeze_sources(verified: dict):
    """Hold all six source files read-only across SQL COMMIT, or deny mutation.

    On non-Windows hosts fail closed. The existing Queue writer lock is
    independent; it must be acquired before this context manager.
    """
    if os.name != "nt":
        raise NativeSourceFreezeDenied("NATIVE_RECONCILIATION_WINDOWS_FREEZE_REQUIRED")
    paths = source_paths(verified)
    handles = []
    try:
        for path in paths:
            handles.append(_windows_open_shared_read(path))
        yield
    finally:
        for handle in reversed(handles):
            _windows_close(handle)
