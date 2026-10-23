"""Bounded deterministic Prompt Authoring for user-supplied locked stories.

Never substitutes model judgment: frozen storyboard + verified Frame Contracts
are the source. The image-generation prompt package includes full contract.
"""
from __future__ import annotations
from pathlib import Path

import frame_contract
import preproduction_handoff
import production_prompt_materializer
import prompt_package
import runtime_atomic_store
import runtime_request
import story_json

AUDIT_REL=Path("meta/runtime/locked-story-prompt-authoring.json")


def applicable(ep: Path) -> bool:
    request=runtime_request.authority_for_episode(Path(ep).resolve()) or {}
    story_input=request.get("story_input") if isinstance(request,dict) else None
    return (isinstance(story_input,dict)
            and story_input.get("mode")=="locked_story"
            and story_input.get("allow_structure_rewrite") is False)


def run(ep: Path) -> dict:
    ep=Path(ep).resolve()
    if not applicable(ep):
        raise RuntimeError("deterministic Prompt Authoring only accepts non-rewrite locked user story")
    errors=frame_contract.verify_all(ep)
    if errors:
        raise RuntimeError("frame contracts invalid: "+"; ".join(errors[:8]))
    errors=preproduction_handoff.verify(ep)
    if errors:
        raise RuntimeError("preproduction handoff invalid: "+"; ".join(errors[:8]))
    total=frame_contract.frame_count(ep)
    # The verified Frame Contracts and the locked storyboard own the count.
    # Historical 25-frame pilots must not block a valid 48-frame episode.
    beats=production_prompt_materializer.locked_table_beats(ep,expected_count=total)
    output=production_prompt_materializer.ensure(ep,require_locked_table=True)
    rows=[]
    for frame in range(1,total+1):
        scene=beats[frame]
        path=ep/production_prompt_materializer.PROMPT_DIR/f"{frame:02d}.txt"
        text=path.read_text(encoding="utf-8-sig").strip()
        # A leftover nonempty model prompt is only admissible if still grounded
        # in this exact storyboard frame; never quietly reuse generic text.
        if scene[:min(len(scene),20)] not in text:
            raise RuntimeError(f"frame {frame:02d} prompt not grounded in locked storyboard")
        contract=frame_contract.compile_frame(ep,frame,write_cache=False)
        package=prompt_package.compile_frame(ep,frame,path,write=True)
        if package.get("frame_contract_sha256")!=contract["contract_sha256"]:
            raise RuntimeError(f"frame {frame:02d} prompt package contract SHA drift")
        rows.append({
            "frame":f"{frame:02d}",
            "prompt_file":production_prompt_materializer.PROMPT_DIR.joinpath(f"{frame:02d}.txt").as_posix(),
            "frame_contract_sha256":contract["contract_sha256"],
            "scene_prompt_sha256":package["scene_prompt_sha256"],
            "package_sha256":package["package_sha256"],
        })
    _story, storyboard=frame_contract.artifact_paths(ep)
    audit={
        "schema_version":1,
        "mode":"LOCKED_STORY_DETERMINISTIC_PROMPT_AUTHORING",
        "model_execution_dispatched":False,
        "status":"PASS",
        "not_episode_stage":True,
        "storyboard_sha256":frame_contract.sha256_file(storyboard),
        "frame_count":total,
        "created_count":len(output["created"]),
        "reused_count":len(output["reused"]),
        "frame_packages":rows,
    }
    runtime_atomic_store.atomic_write_json(ep/AUDIT_REL,audit)
    return audit
