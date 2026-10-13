"""R16 refuses accidental write exposure through the local readonly console."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def test_local_readonly_api_does_not_dispatch_mutation():
    source=(ROOT/"scripts/storyos_local_readonly_api.py").read_text(encoding="utf-8")
    assert "do_GET" in source
    assert 'method.upper() != "GET"' in source
    assert "class ReadOnlyLocalDispatcher" in source
    assert "def do_POST" not in source
    assert "onOpen" not in source


def test_r16_backup_cannot_obtain_runtime_writer_or_provider_permissions():
    source=(ROOT/"web-console/src/api/localDraftBackup.ts").read_text(encoding="utf-8")
    assert "browser_local_only" in source
    assert "reviewDraftRestore" in source
    for forbidden in ("fetch(", "axios(", "executeProvider", "dispatchGeneration", "mysql.", "redis."):
        assert forbidden not in source
