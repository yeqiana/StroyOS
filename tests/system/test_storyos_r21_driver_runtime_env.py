"""R21 four small native Windows Driver child config and authority tests.

Pure tests: no Provider, MySQL writes, new Attempts, or Driver dispatch.
"""
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"episodes/_system")]
import runtime_driver as driver
import storage_config
import story_review_attempt_admission as admit
import storyos_codex_managed as managed

def fixture(tmp_path,monkeypatch):
    file=tmp_path/"runtime.env"
    file.write_text("\n".join((
        "STORYOS_MYSQL_HOST=127.0.0.1",
        "STORYOS_MYSQL_PORT=3307",
        "STORYOS_MYSQL_USER=legit",
        "STORYOS_MYSQL_PWD=secret",
        "STORYOS_MYSQL_DB=storyos_canonical",
        "STORYOS_REDIS_HOST=127.0.0.1",
        "STORYOS_REDIS_PORT=6379",
        "STORYOS_REDIS_DB=0",
        "STORYOS_RUNTIME_STORE_MODE=mysql",
        "STORYOS_EPISODE_META_STORE_MODE=mysql",
        "STORYOS_HOT_STATE_MODE=redis",
    ))+"\n",encoding="utf-8")
    monkeypatch.setattr(driver,"RUNTIME_ENV_PATH",file)
    initial={"STORYOS_MYSQL_HOST":"stale-host",
             "STORYOS_MYSQL_PORT":"3306","STORYOS_MYSQL_USER":"wrong",
             "STORYOS_MYSQL_DB":"stale_database",
             "STORYOS_REDIS_HOST":"stale-redis",
             "STORYOS_EPISODE_META_STORE_MODE":"json",
             "STORYOS_HOT_STATE_MODE":"file",
             "OPENAI_BASE_URL":"http://opencodex.invalid"}
    monkeypatch.setattr(driver.os,"environ",initial.copy())
    return file,initial

def native():
    driver._load_child_runtime_environment(
        runtime_store_mode="mysql",episode_meta_store_mode="mysql",
        hot_state_mode="redis",production_mode="CODEX_MANAGED",image_executor="CODEX")

def test_child_native_ignores_inherited_stale_db_and_proxy(tmp_path,monkeypatch):
    file,prior=fixture(tmp_path,monkeypatch)
    native()
    env=driver.os.environ
    assert env["STORYOS_MYSQL_HOST"]=="127.0.0.1"
    assert env["STORYOS_MYSQL_PORT"]=="3307"
    assert env["STORYOS_MYSQL_DB"]=="storyos_canonical"
    assert env["STORYOS_MYSQL_USER"]=="legit"
    assert env["STORYOS_REDIS_HOST"]=="127.0.0.1"
    assert env["STORYOS_EPISODE_META_STORE_MODE"]=="mysql"
    assert env["STORY_OS_PRODUCTION_MODE"]=="CODEX_MANAGED"
    assert env["STORY_OS_IMAGE_EXECUTOR"]=="CODEX"
    assert "OPENAI_BASE_URL" not in env

def test_native_fails_closed_without_local_db_binding(tmp_path,monkeypatch):
    file,prior=fixture(tmp_path,monkeypatch)
    file.unlink()
    with pytest.raises(ValueError):
        native()
    assert driver.os.environ["STORYOS_MYSQL_HOST"]=="stale-host"
    file.write_text("STORYOS_MYSQL_HOST=127.0.0.1\n",encoding="utf-8")
    with pytest.raises(ValueError):
        native()
    assert driver.os.environ["STORYOS_MYSQL_DB"]=="stale_database"

def test_legacy_non_native_maintains_explicit_test_env(tmp_path,monkeypatch):
    file,prior=fixture(tmp_path,monkeypatch)
    driver._load_child_runtime_environment(
        runtime_store_mode="jsonl",episode_meta_store_mode="json",
        hot_state_mode="file")
    assert driver.os.environ["STORYOS_MYSQL_HOST"]=="stale-host"
    assert driver.os.environ["STORYOS_MYSQL_PORT"]=="3306"
    assert driver.os.environ["STORYOS_EPISODE_META_STORE_MODE"]=="json"
    with pytest.raises(ValueError,match="NATIVE_DRIVER_SCOPE_MISMATCH"):
        driver._load_child_runtime_environment(
            runtime_store_mode="mysql",episode_meta_store_mode="mysql",
            hot_state_mode="redis",production_mode="CODEX_MANAGED",
            image_executor="OPEN_CODEX")

def test_native_review_reuse_is_not_image_permission(tmp_path,monkeypatch):
    file,prior=fixture(tmp_path,monkeypatch)
    native()
    info=storage_config.mysql_connection_kwargs()
    assert info["host"]=="127.0.0.1" and info["port"]==3307
    assert info["database"]=="storyos_canonical"
    assert info["password"]=="secret"
    review={"critic_provenance":{
        "attempt":11,"review_scope":"EPISODE_SOURCE_REPAIR_AFTER_A10_DELETE_FRAME_FAIL",
        "review_epoch":10,"epoch_attempt":1,"direct_user_continuation_review":True},
        "summary":{"passed":True}}
    d=admit.decide(dag_attempt=169,official_review=review,
                    request_rows={1:{"status":"AWAITING_PRODUCT_REVIEW"},2:{"status":"FINALIZED"}},
                    candidate_exists={})
    assert d["status"]=="EXISTING_REVIEW_MUST_BE_REVALIDATED"
    assert d["may_dispatch"] is False
    summary=managed.admission_summary(
        stage={"status":"STAGE_ELIGIBLE"},visual={"status":"BLOCKED","reason":"PIXEL_UNVERIFIED"},
        native_ready={"model_entitlement_verified":False},blockers=[])
    assert summary["dag_startable"] is True
    assert summary["image_ready"] is False
    assert summary["production_authorization"] is False
