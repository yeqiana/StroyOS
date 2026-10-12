"""Single-machine published runtime boundary: no R38 distributed imports.

This is a contract guard for the opt-in slim integration candidate, not an
assertion about the historical R38 archive or the rest of the repo history.
"""
from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[2]
FORBIDDEN={
    "redis_writer_delegation","mysql_writer_epoch_witness",
    "writer_worker_test_transport","provider_consumer_contract",
    "durable_provider_consumer","redis_global_image_capacity",
    "test_image_capacity_session",
}
TARGETS=[
    ROOT/"episodes"/"_system"/"runtime_driver.py",
    ROOT/"episodes"/"_system"/"image_generation_gateway.py",
    ROOT/"episodes"/"_system"/"generation_attempt_authority.py",
    ROOT/"episodes"/"_system"/"image_worker_pool.py",
    ROOT/"episodes"/"_system"/"batch_image_worker.py",
    ROOT/"episodes"/"_system"/"codex_subscription_image.py",
]


def test_canonical_production_edges_do_not_import_distributed_experiments():
    for path in TARGETS:
        tree=ast.parse(path.read_text(encoding="utf-8-sig"),filename=str(path))
        found=set()
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                found.update(x.name.rsplit(".",1)[-1] for x in node.names)
            elif isinstance(node,ast.ImportFrom) and node.module:
                found.add(node.module.rsplit(".",1)[-1])
        assert not (FORBIDDEN & found),(path,FORBIDDEN & found)


def test_single_node_still_enforces_one_driver_and_five_os_slots():
    from sys import path as search_path
    sysfolder=str(ROOT/"episodes"/"_system")
    if sysfolder not in search_path:
        search_path.insert(0,sysfolder)
    import runner_state_store
    import global_image_capacity
    import persistent_runner_daemon
    assert runner_state_store.LOCK_REL==Path("meta/runtime-runner.lock")
    assert global_image_capacity.CAPACITY==5
    assert callable(persistent_runner_daemon.run)
    assert callable(global_image_capacity.image_permits)


def test_distributed_experiment_modules_not_shipped_in_slim_baseline():
    forbidden_files=[
        ROOT/"platform"/"state"/(name+".py") for name in FORBIDDEN
    ]
    forbidden_files.append(ROOT/"episodes"/"_system"/"writer_worker_test_transport.py")
    assert not [str(p) for p in forbidden_files if p.exists()]
