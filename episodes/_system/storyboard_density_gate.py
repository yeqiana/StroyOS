#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Storyboard information-density / delete-frame gate.

This is structured Story Critic evidence, not a new Episode stage.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import story_json

REL=Path("meta/storyboard-density-review.json")
NECESSITY=("causal_loss","evidence_loss","suspense_loss","spatial_orientation_loss","emotional_state_change_loss")
PROGRESS={"NEW_EVIDENCE","NEW_CAUSALITY","NEW_INFORMATION","NEW_SPACE","NEW_CHARACTER_STATE",
          "ANOMALY_ESCALATION","REVERSAL","PAYOFF","BRIDGE"}
STRONG=PROGRESS-{"BRIDGE"}

def read_json(p):
    return story_json.read_json(p)
def write_json(p,d):
    story_json.write_json(p, d)
def frame_count(ep):
    d=read_json(Path(ep)/"meta/release-manifest.json")
    return int(((d.get("release") or {}).get("body_frame_count")) or 0)

def prepare(ep, force=False):
    ep=Path(ep).resolve(); target=ep/REL
    if target.is_file() and not force:return read_json(target)
    total=frame_count(ep)
    if total<=0: raise ValueError("release.body_frame_count missing")
    rows=[]
    for n in range(1,total+1):
        rows.append({"frame":f"{n:02d}",
          "necessity":{k:False for k in NECESSITY},
          "progress_type":"BRIDGE",
          "same_visual_as_previous":False,
          "new_verifiable_information":False,
          "note":""})
    d={"schema_version":1,"status":"DRAFT","frame_count":total,
       "rules":{"delete_frame_test":True,"max_frames_without_strong_progress":5,
                "max_repeated_visual_without_new_information":2},
       "frames":rows}
    write_json(target,d);return d

def validate(ep, require_locked=True):
    ep=Path(ep).resolve();p=ep/REL
    if not p.is_file():return ["meta/storyboard-density-review.json missing"]
    d=read_json(p);e=[];total=frame_count(ep)
    if total<=0:e.append("release.body_frame_count missing or invalid")
    if d.get("schema_version")!=1:e.append("density schema_version must be 1")
    if require_locked and d.get("status")!="LOCKED":e.append("storyboard density review must be LOCKED")
    rows=d.get("frames") or []
    if len(rows)!=total:e.append(f"density frame count mismatch {len(rows)} != {total}")
    seen=set(); bridge_run=0; repeated_run=0
    normalized=[]
    for row in rows:
        try:n=int(row.get("frame"))
        except Exception:
            e.append("density frame id invalid");continue
        if n in seen:e.append(f"density duplicate frame {n:02d}")
        seen.add(n); normalized.append((n,row))
        nec=row.get("necessity") or {}
        if not any(nec.get(k) is True for k in NECESSITY):
            e.append(f"REDUNDANT_FRAME:{n:02d}:delete test has no demonstrated loss")
        pt=str(row.get("progress_type") or "")
        if pt not in PROGRESS:e.append(f"frame {n:02d} invalid progress_type {pt!r}")
        bridge_run = bridge_run+1 if pt=="BRIDGE" else 0
        if bridge_run>2:e.append(f"frame {n:02d} has >2 consecutive BRIDGE frames")
        same=row.get("same_visual_as_previous") is True
        new=row.get("new_verifiable_information") is True
        repeated_run = repeated_run+1 if same and not new else 0
        if repeated_run>2:e.append(f"frame {n:02d} repeats visual/action without new information >2")
    normalized.sort()
    for i in range(0,max(0,len(normalized)-4)):
        window=normalized[i:i+5]
        if not any(str(r.get("progress_type")) in STRONG for _,r in window):
            e.append(f"NO_STRONG_PROGRESS_WINDOW:{window[0][0]:02d}-{window[-1][0]:02d}")
    return e

def self_test():
    assert "BRIDGE" in PROGRESS and "BRIDGE" not in STRONG
    print("STORYBOARD DENSITY GATE SELF-TEST PASS")

def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("prepare");p.add_argument("episode_dir");p.add_argument("--force",action="store_true")
    p=sub.add_parser("validate");p.add_argument("episode_dir");p.add_argument("--allow-draft",action="store_true")
    p=sub.add_parser("show");p.add_argument("episode_dir")
    sub.add_parser("self-test");a=ap.parse_args()
    if a.cmd=="self-test":self_test();return 0
    ep=Path(a.episode_dir).resolve()
    if a.cmd=="prepare":print(json.dumps(prepare(ep,a.force),ensure_ascii=False,indent=2));return 0
    if a.cmd=="validate":
        e=validate(ep,not a.allow_draft)
        if e:[print("FAIL:",x) for x in e];return 2
        print("STORYBOARD DENSITY VERIFIED");return 0
    p=ep/REL;print(p.read_text(encoding="utf-8-sig") if p.is_file() else "{}");return 0
if __name__=="__main__":raise SystemExit(main())
