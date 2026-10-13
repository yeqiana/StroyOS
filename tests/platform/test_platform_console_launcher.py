from pathlib import Path

from scripts.platform_console_launcher import build_children


def test_console_children_use_loopback_and_built_vite(tmp_path: Path):
    children = build_children(python_exe="C:/Python/python.exe", node_exe="C:/Node/node.exe", run_root=tmp_path)
    assert [child.name for child in children] == ["platform-api", "web-console"]
    assert children[0].command[-4:] == ("--host", "127.0.0.1", "--port", "8080")
    assert "preview" in children[1].command
    assert children[1].command[-5:] == ("--host", "127.0.0.1", "--port", "3100", "--strictPort")
    assert children[0].log_path == tmp_path / "platform-api.log"
    # Same contract in the main checkout and disposable Git worktrees.
    root = Path(__file__).resolve().parents[2]
    assert children[0].cwd.resolve() == root
    assert children[1].cwd.resolve() == root / "web-console"
