"""R13 slot2: immutable attempt lookup does not quietly use latest PASS."""
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import review_record_persistence as db

def test_historical_attempt_specific_fencing_and_single_closed_connection(tmp_path,monkeypatch):
    rows=[{"attempt_no":3,"payload":{"critic_provenance":{"attempt":3},
                                      "summary":{"passed":False}}},
          {"attempt_no":4,"payload":{"critic_provenance":{"attempt":4},
                                      "summary":{"passed":True}}}]
    closed=[]
    class Conn:
        def close(self):closed.append(True)
    class Repo:
        def list_attempts(self,episode_id,review_type):return rows
    monkeypatch.setattr(db,"_mode",lambda:"mysql")
    monkeypatch.setattr(db,"_repository",lambda:(Conn(),Repo()))
    monkeypatch.setattr(db.episode_identity,"storage_episode_id",lambda ep:"episode")
    row=db.load_attempt(tmp_path,"STORY_SEMANTIC",3)
    assert row["summary"]["passed"] is False
    assert row["critic_provenance"]["attempt"]==3
    assert closed==[True]

def test_missing_historical_attempt_is_not_latest_review(tmp_path,monkeypatch):
    class Conn:
        def close(self):pass
    class Repo:
        def list_attempts(self,episode_id,review_type):
            return [{"attempt_no":2,"payload":{"summary":{"passed":True}}}]
    monkeypatch.setattr(db,"_mode",lambda:"mysql")
    monkeypatch.setattr(db,"_repository",lambda:(Conn(),Repo()))
    assert db.load_attempt(tmp_path,"STORY_SEMANTIC",5) is None

def test_zero_attempt_refuses_without_database(monkeypatch,tmp_path):
    monkeypatch.setattr(db,"_mode",lambda:"mysql")
    monkeypatch.setattr(db,"_repository",lambda: (_ for _ in ()).throw(AssertionError("query")))
    with pytest.raises(ValueError,match="attempt_no"):
        db.load_attempt(tmp_path,"STORY_SEMANTIC",0)
