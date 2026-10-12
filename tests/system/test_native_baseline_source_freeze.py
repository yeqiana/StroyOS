"""Windows-only interprocess source immutability checks; never touch production."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SYSTEM = Path(__file__).resolve().parents[2] / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import native_baseline_source_freeze as freeze


@pytest.fixture
def sources(tmp_path):
    files = {}
    for key in freeze.SOURCE_KEYS:
        path = tmp_path / f"{key}.bin"
        path.write_bytes(key.encode("utf-8"))
        files[key] = path.resolve()
    return files


def test_source_freeze_requires_every_existing_distinct_file(sources):
    assert len(freeze.source_paths(sources)) == 6
    missing = dict(sources)
    missing.pop("runner_receipt")
    with pytest.raises(freeze.NativeSourceFreezeDenied, match="INPUT_INVALID"):
        freeze.source_paths(missing)
    duplicate = dict(sources)
    duplicate["raw"] = duplicate["candidate"]
    with pytest.raises(freeze.NativeSourceFreezeDenied, match="DUPLICATE"):
        freeze.source_paths(duplicate)


@pytest.mark.skipif(os.name == "nt", reason="Windows path covered by actual OS tests")
def test_non_windows_source_freeze_fails_closed(sources):
    with pytest.raises(freeze.NativeSourceFreezeDenied, match="WINDOWS_FREEZE_REQUIRED"):
        with freeze.freeze_sources(sources):
            pytest.fail("no source freeze allowed without Windows")


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows file sharing")
def test_windows_source_freeze_denies_cross_process_overwrite_and_replace(sources, tmp_path):
    target = sources["raw"]
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"other")
    before = target.read_bytes()
    overwrite = "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'changed')"
    replace = "import os,sys; os.replace(sys.argv[2],sys.argv[1])"
    with freeze.freeze_sources(sources):
        child = subprocess.run([sys.executable, "-c", overwrite, str(target)],
                               capture_output=True, text=True, timeout=15)
        assert child.returncode != 0
        child = subprocess.run([sys.executable, "-c", replace,
                                str(target), str(replacement)],
                               capture_output=True, text=True, timeout=15)
        assert child.returncode != 0
        assert target.read_bytes() == before
        assert replacement.read_bytes() == b"other"
    child = subprocess.run([sys.executable, "-c", overwrite, str(target)],
                           capture_output=True, text=True, timeout=15)
    assert child.returncode == 0
    assert target.read_bytes() == b"changed"


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows file sharing")
def test_windows_partial_freeze_acquisition_releases_prior_handles(sources, monkeypatch):
    real_open = freeze._windows_open_shared_read
    opened = []
    def fail_on_third(path):
        if len(opened) == 2:
            raise freeze.NativeSourceFreezeDenied("NATIVE_RECONCILIATION_SOURCE_FREEZE_OPEN_FAILED")
        handle = real_open(path)
        opened.append(handle)
        return handle
    monkeypatch.setattr(freeze, "_windows_open_shared_read", fail_on_third)
    with pytest.raises(freeze.NativeSourceFreezeDenied, match="OPEN_FAILED"):
        with freeze.freeze_sources(sources):
            pytest.fail("partial freeze must not be admitted")
    # The first two handles were released even though the third open failed.
    for path in freeze.source_paths(sources)[:2]:
        path.write_bytes(b"released")
