#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compile stable per-frame generation prompt packages as derived cache."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json
from pathlib import Path
import frame_contract
import frame_capture_feasibility
import image_model_policy
import story_json
import runtime_workspace
import storage_config
import prompt_package_persistence

REL=Path("meta/runtime/prompt-packages")
def now(): return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
def h(data): return hashlib.sha256(data).hexdigest()
def compile_frame(ep,frame,prompt_file,write=True):
    prompt_file=Path(prompt_file).resolve()
    scene=prompt_file.read_text(encoding="utf-8-sig").strip()
    if not scene:
        raise ValueError(f"frame {int(frame):02d} prompt empty")
    contract=frame_contract.compile_frame(ep,int(frame),write_cache=write)
    frame_capture_feasibility.require_feasible(contract)
    rel=REL/f"{int(frame):02d}.json"
    previous=prompt_package_persistence.load_latest(ep,frame) or {}
    scene_sha=h(scene.encode("utf-8"))
    if (previous.get("scene_prompt_sha256")==scene_sha
            and previous.get("frame_contract_sha256")
            and previous["frame_contract_sha256"]!=contract["contract_sha256"]):
        # Old SHA can differ solely because the canonical Frame Contract filled
        # previously empty machine-only projection fields. Preserve the proven
        # identical authored scene without silently accepting semantic changes.
        # The existing versioned SHA authority must positively prove equivalence;
        # missing/unverified versions and real content drift remain blocked.
        if not frame_contract.equivalent_to_current(
                ep, int(frame), previous["frame_contract_sha256"], current=contract):
            raise ValueError("PROMPT_SOURCE_DRIFT: unchanged scene prompt belongs to an older non-equivalent Frame Contract; rebuild scene from current storyboard before generation")
    model=image_model_policy.for_episode(ep)
    material={
      "schema_version":1,"frame":f"{int(frame):02d}","scene_prompt":scene,
      "scene_prompt_sha256":scene_sha,
      "storyboard_source":contract.get("storyboard_frame") or {},
      "frame_contract_sha256":contract["contract_sha256"],
      "frame_prompt_contract":contract.get("prompt_contract", ""),
      "image_model":model,
      "source_prompt":str(prompt_file),
    }
    if isinstance(contract.get("m00_adjacent_state_delta"),dict):
        # Derived from the locked JSON storyboard; explicit opt-in only.
        material["m00_adjacent_state_delta"] = contract["m00_adjacent_state_delta"]["delta"]
        material["m00_adjacent_state_delta_sha256"] = contract["m00_adjacent_state_delta"]["delta_sha256"]
    raw=json.dumps(material,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    data={**material,"package_sha256":h(raw),"compiled_at":now()}
    if write:
        mode=storage_config.episode_meta_store_config()["mode"]
        if mode != "mysql":
            runtime_workspace.write_json(ep,rel,data)
        prompt_package_persistence.persist(ep,data)
    return data
def self_test():
    assert REL.as_posix()=="meta/runtime/prompt-packages"
    print("PROMPT PACKAGE SELF-TEST PASS")
def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("compile"); p.add_argument("episode_dir"); p.add_argument("--frame",type=int,required=True); p.add_argument("--prompt-file",required=True)
    sub.add_parser("self-test"); a=ap.parse_args()
    if a.cmd=="self-test": self_test(); return 0
    ep=Path(a.episode_dir).resolve()
    print(json.dumps(compile_frame(ep,a.frame,a.prompt_file),ensure_ascii=False,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
