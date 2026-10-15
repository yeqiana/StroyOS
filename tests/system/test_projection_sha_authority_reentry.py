"""Visual Lock re-entry must preserve old real review SHA across projection-only fills."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import frame_contract as contract
import frame_contract_persistence as persistence

EP = ROOT / "episodes/00_独立篇/13_失物归还的那扇门"


def snapshots():
    old = {"hash_material": {
        "story_sha256": "story-bound",
        "frame": "01",
        "character_contract": {"P01": "black hair"},
        "frame_directive": {"action": "normal commute"},
        "authenticity_card": {"photographer": None, "capture": {"id": None}},
        "continuity": {"anchors": {"protagonist": None}},
    }}
    new = copy.deepcopy(old)
    new["hash_material"]["authenticity_card"]["photographer"] = "P01"
    new["hash_material"]["authenticity_card"]["capture"]["id"] = "phone"
    new["hash_material"]["continuity"]["anchors"]["protagonist"] = "P01"
    for doc in (old, new):
        doc["contract_sha256"] = contract.sha256_json(doc["hash_material"])
    return old, new


def test_projection_fill_is_proven_not_guessed(monkeypatch):
    old, new = snapshots()
    calls = []
    def load(_ep, frame, sha):
        calls.append((frame, sha))
        return old if sha == old["contract_sha256"] else None
    monkeypatch.setattr(persistence, "load_sha_bound_version", load)
    assert contract.equivalent_to_current(
        EP, 1, old["contract_sha256"], current=new)
    assert calls == [(1, old["contract_sha256"])]
    assert not contract.equivalent_to_current(
        EP, 1, "9"*64, current=new)


def test_real_semantic_changes_never_inherit_visual_pass(monkeypatch):
    old, new = snapshots()
    monkeypatch.setattr(persistence, "load_sha_bound_version",
                        lambda *_: old)
    for mutation in (
        lambda data: data["character_contract"].update(P01="different face"),
        lambda data: data["frame_directive"].update(action="different story"),
        lambda data: data.update(story_sha256="different storyboard"),
        lambda data: data.update(frame="02"),
    ):
        altered = copy.deepcopy(new)
        mutation(altered["hash_material"])
        altered["contract_sha256"] = contract.sha256_json(altered["hash_material"])
        assert not contract.equivalent_to_current(
            EP, 1, old["contract_sha256"], current=altered)


def test_version_lookup_requires_verified_document(monkeypatch):
    import json
    class Connection:
        def query_one(self, sql, params):
            assert "FRAME_NO=%s AND SHA256=%s" in sql
            return {"SHA256": "b"*64, "PAYLOAD": json.dumps({
                "document": {"rel": "contracts/frame.json", "sha256": "0"*64}})}
    monkeypatch.setattr(persistence.storage_config, "episode_meta_store_config",
                        lambda: {"mode": "mysql"})
    monkeypatch.setattr(persistence.storage_config, "mysql_connection_kwargs",
                        lambda *_: {})
    monkeypatch.setattr(persistence.mysql_connection_cache, "shared_connection",
                        lambda _: Connection())
    monkeypatch.setattr(persistence, "_episode_id", lambda _: "episode")
    monkeypatch.setattr(persistence.runtime_workspace, "read_json",
                        lambda *args,**kwargs: {"hash_material": {"frame":"01"},
                            "contract_sha256":"b"*64})
    assert persistence.load_sha_bound_version(EP,1,"b"*64) is None
