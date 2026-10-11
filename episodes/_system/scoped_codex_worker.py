#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, base64, binascii, datetime, hashlib, json, os, re, shutil, subprocess, sys, time, uuid
import codex_user_runner  # STORY_OS_V2_7_CODEX_USER_MODE_BRIDGE
import execution_capsule
import character_contract
import character_visual_contract
import world_identity_contract  # STORY_OS_V221_WORLD_IDENTITY
import character_appearance_anchor  # STORY_OS_V221_CHARACTER_CONTINUITY
import inflight_codex_task  # STORY_OS_V262_INFLIGHT_ATTACH
import resource_library
import intro_policy
import directing_quality
import episode_performance
import storyos_config
import runtime_router
import product_runtime_adapter
import runtime_timeout_policy
import runtime_request
import runtime_memory_advice
import episode_state_persistence
import model_policy
import runtime_observability
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def _model_event(ep,event_type,step,binding,*,worker_id=None,generation_key=None,duration_ms=None,status=None,source="scoped_codex_worker",run_id=None,trace_id=None,call_id=None,requested_model=None,effective_model_source=None,started_at=None,finished_at=None,receipt_path=None,logical_asset_key=None,queue_name=None,wait_ms=None):
    try:
        from logical_asset_identity import episode_id
        runtime_observability.safe_record_runtime_event(
            ep,event_type,episode_id=episode_id(ep),
            run_id=run_id,trace_id=trace_id,call_id=call_id,
            logical_asset_key=logical_asset_key,queue_name=queue_name,wait_ms=wait_ms,
            step=step,model_role=binding.get("role") or SCOPED_MODEL_ROLES.get(step),
            profile=binding.get("profile"),effective_model=binding.get("model"),
            requested_model=requested_model or binding.get("model"),
            effective_model_source=effective_model_source,
            reasoning_effort=binding.get("reasoning_effort"),
            model_policy_version=binding.get("policy_version"),model_policy_sha256=binding.get("model_policy_sha256"),
            provider="codex_subscription",runner="codex exec",worker_id=worker_id,
            generation_key=generation_key,duration_ms=duration_ms,status=status,source=source,
            started_at=started_at,finished_at=finished_at,evidence_ref=receipt_path)
    except Exception:
        return

# The step's previous Codex task produced no usable result inside its own
# deadline. Technical, retryable: nothing about the content failed.
ATTACH_TIMEOUT_RC=26
ATTACH_POLL_SECONDS=5.0

# P0-D real fault injection (2026-09-15) proved that CREATIVE_STORY cannot use
# the rendered prompt as its attach identity: prompt() intentionally prepares
# character/resource/directing helper files before compiling the capsule, so a
# restarted Driver sees different prompt bytes even though the user's question
# did not change.  Keep this list to inputs that exist *before* CREATIVE_STORY and
# are not owned by that step.  Step outputs such as story-gates, concept rows,
# character-contract, resource-selection and directing-quality are deliberately
# absent.
CREATIVE_STORY_ATTACH_ROOT_INPUTS=(
    "config/storyos.yaml",
    "config/profiles/account_creative/default.json",
    "config/profiles/world_identity/default.json",
    "standards/directing_grammar_v1.json",
    "standards/character-pools.json",
    "standards/entry-motivation-pools.json",
    "standards/scene-pools.json",
    "standards/forbidden-character-roles.json",
    "story_os_manifest.json",
    "reports/account-learning-index.json",
)


def _sha_file(path:Path)->str|None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    except OSError:
        return None


def attach_source_sha256(ep:Path,step:str)->str:
    """Stable authority projection used only to decide whether an old task attaches.

    The exact submitted stdin is still pinned independently by the runner result's
    ``stdin_sha256``.  This projection answers the different question: "is the
    business input still the same after the Driver restarted?"  Returning an empty
    string keeps the older exact-prompt/fail-closed identity for steps that do not
    yet have an audited projection.
    """
    ep=Path(ep)
    if step=="CREATIVE_STORY":
        request=runtime_request.authority_for_episode(ep)
        if not request:
            return ""
        state=episode_state_persistence.load(ep) or {}
        material={
            "identity_schema_version":2,
            "step":step,
            "current_state":state.get("current_state"),
            "creative_request":runtime_request.preimage_authority_projection(request),
            "directive_sha256":hashlib.sha256(STEP_DIRECTIVES[step].strip().encode("utf-8")).hexdigest(),
            "root_authority":{rel:_sha_file(ROOT/rel) for rel in CREATIVE_STORY_ATTACH_ROOT_INPUTS},
        }
        raw=json.dumps(material,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
    return ""

def runtime_index_block(step):
    try:
        config=storyos_config.load_config()
        data=storyos_config.load_index()
        return json.dumps({
            "rules":{
                "read_index_first":storyos_config.get_path(config,"runtime.read_index_first"),
                "recursive_repository_scan_default":storyos_config.get_path(config,"runtime.recursive_repository_scan_default"),
            },
            "required_read":((data.get("stage_read_sets") or {}).get(step) or []),
            "entrypoints":data.get("entrypoints") or {},
        },ensure_ascii=False,indent=2)
    except Exception:return "{}"

STEP_DIRECTIVES={
"CREATIVE_STORY":"""
TARGET: reach STORYBOARD_LOCKED and stop there.
- honor the Runtime Request authority supplied by the owner API/capsule; do not assume an Episode JSON file exists.
- BEFORE concept/story work, consume Execution Capsule character_contract as the authoritative Character/Entry/Scene input, or use `python episodes/_system/character_contract.py show "<episode>" --with-sha`. In mysql mode a legacy meta/character-contract.json file may be absent; do not invent an empty contract or write the JSON instead of the Authority.
- Story OS 2.2.1 World Identity: read the effective default/override through `python episodes/_system/world_identity_contract.py show "<episode>"`. Default is Mainland China + ordinary Chinese young adults. Do not randomly introduce foreign characters/architecture/cultural context. If the Story explicitly specifies another country/culture, author meta/world-identity.json as an explicit override instead of fighting the default.
- default protagonists are ordinary young people from the 2004-2010 or modern-2020s pools; first-person POV still requires a stable character anchor.
- default 4-5 person groups must keep stable member IDs, ages, genders and clothing anchors.
- prefer life-like entry motives: travel, return home, friends hangout, games/drinking, challenge, abandoned place, outdoor trip, casual work, research/expedition, accidental detour.
- NEVER replace the protagonist with a repair worker, electrician, police officer, journalist, investigator, professional ghost hunter or another occupational tool invented to solve the anomaly.
- casual work / research / expedition may explain why the young people arrived, but professional skill must not become the shortcut that solves the anomaly.
- BEFORE STORYBOARD_LOCKED, save the actual final Story within this Episode, recheck its character/entry/ordinary-day logic with anomalies removed, and only attest PASS when grounded in the saved final text.
- Read current contract and exact authority_sha256 with `python episodes/_system/character_contract.py show "<episode>" --with-sha`. Do not depend on meta/character-contract.json in mysql mode.
- Author meta/character-story-review.json with schema_version=1, expected_contract_sha256 from the show command, story_path (relative to Episode and pointing to the actual saved final Story markdown), story_sha256 (SHA256 of that exact file), and no_anomaly_test with pass=true, ordinary_day_plan and a specific review_reason of at least 20 characters. If the final Story genuinely changes cast, entry or scene, include the full reviewed proposed_contract preserving its origin metadata. No empty or fabricated evidence.
- Use `python episodes/_system/character_contract.py review-lock "<episode>" --review meta/character-story-review.json` to submit reviewed Story evidence through canonical Episode Contract storage; the Episode single-writer rule still applies. Then run `python episodes/_system/character_contract.py validate "<episode>" --require-locked`. Never update a legacy JSON as a stand-in for MySQL Authority, never execute ad hoc SQL, never skip the review gate.
- Reuse already-successful Codex model receipts and existing final Story on recovery; if only the contract attestation is missing, complete that deterministic review/commit without calling the paid Story authoring model again.
- auto_create: author the complete story yourself via recent5/account evidence -> 8-12 concepts -> Concept Ambition -> image-first propagation -> Story/Storyboard.
- user_seed: preserve core intent but strengthen/rewrite mechanism, logic, escalation, climax and ending; never mechanically split the seed.
- core_constraints: preserve every hard constraint.
- locked_story: only logic/polish repairs.
- run Story critics/verifiers and honest delegated approval evidence.
- Directing Quality: author and LOCK meta/voice-contract.json; author and LOCK meta/storyboard-density-review.json; run voice_contract.py validate and storyboard_density_gate.py validate. Every frame must pass the delete-frame test and 5-frame progress window.
- Opening Social Anchor: for multi-person travel / return-home / outing stories, strongly prefer Frame 01-02 to show the group in realistic selfie perspective: either vehicle/departure/transit selfie or destination/scenic check-in selfie. Use at least 2 visible people (prefer 3-4), establish relationship/clothing anchors, keep capture casual and imperfect rather than commercial/staged, and keep anomaly absent or only micro-background. Author+LOCK meta/opening-social-anchor.json and run opening_social_anchor.py validate. Solo or structurally incompatible stories may set applicable=false only with a concrete exception_reason.
- Camera-Friendly Ordinary Cast + Anti-Likeness: author+LOCK meta/character-visual-contract.json as IDENTITY SPEC only. Set each locked member face_identity.identity_spec_locked=true; preproduction_only must NOT claim a pixel/image master. Primary leads should be moderately-above-average but believable real young adults; female lead defaults slim/proportionate/natural unless Story requires another build. Keep natural skin texture/asymmetry and explicit original haircut anchors. Real-person references may guide age vibe, attractiveness range, realism, capture style and clothing direction ONLY; never copy exact face geometry, feature combination, personal markers or exact hairstyle. Run character_visual_contract.py validate.
- After Character Visual Contract is LOCKED, build+verify `meta/runtime/contracts/character-appearance-anchor.json` with character_appearance_anchor.py. This is a derived textual identity anchor; it does not replace the later Visual Lock pixel master.
- Account Creative Profile: read config/profiles/account_creative/default.json before concept selection. Treat it as the account's default subject/style memory: ordinary young-adult reality cracks, old-device mysteries, travel/return-home anomalies, mountain mockumentary, folk/archive rules and world-scale anomalies; M00 reality-first visual identity remains default. It guides candidate generation but never overrides an explicit Runtime Request or recent-5 anti-homogeneity evidence.
- Capture Setup + Directing Grammar + Anomaly Logic + Human Response: author+LOCK meta/shot-progression-review.json schema_version=3 for new/unlocked episodes and run shot_progression_gate.py validate. Read standards/directing_grammar_v1.json. Every frame must declare shot_scale + globally unique scene_position_id; the episode needs at least one wide/extreme-wide and one close/detail, at least three shot scales overall, and the same exact capture position may not be reused. Translate at least two suitable classic-cinema shot-structure techniques into diegetic casual capture; never recreate an exact film frame. Every frame declares practical lighting source/contrast/suspense function; no invented cinematic key/rim light. Suspense/strange stories must hide at least one meaningful anomaly through a physically valid mirror, water/glass/wet reflection, fog/mist, light-shadow boundary, screen reflection, foreground occlusion, doorway/window or silhouette before/alongside direct reveal. Same capture setup max 2 consecutive; every 5-frame window needs >=3 setup signatures; anomaly escalation must gain spatial/causal contradiction, human consequence or reversal rather than only more/bigger lights; after confirmation people must progress from observing into verify/discuss/move/act/fail/adapt; Frame 10 must open new evidence/question rather than recap. For every human-present frame, author restrained emotion state/intensity 0..4/causal trigger/response_sync plus interaction type/actor/target/action/meaningful. intensity>=2 needs a real trigger. Multi-person reactions should normally be asynchronous or shared-but-unsynchronized, never theatrical synchronized screaming. For multi-person stories, each run of 5 human-present frames needs at least one meaningful interaction, but interactions must not dominate the whole story. Opening Frame 01/02 social anchor needs at least one natural interaction (selfie, someone talking, adjusting seatbelt/bag/hat, showing a phone, etc.). Wardrobe may participate in causal actions such as pulling a shell zipper, holding a hat in wind, adjusting a backpack or handing a wet jacket.
- advance only to STORYBOARD_LOCKED.
DO NOT create Environment/Impact Contract, Visual Lock images, Batch, subtitles or Release.
""",
"PREIMAGE_COMPILE":"""
TARGET: keep STORYBOARD_LOCKED and finish every non-image asset required for a clean image handoff.
- Story/Storyboard/Character Contract are already locked authority. DO NOT rewrite them.
- resolve shared Resource Library references into meta/resource-selection.json.
- create/verify Environment + Impact Contract and all frame directives.
- compile/verify all Resolved Frame Contracts.
- Before Frame Contract compile, run `python episodes/_system/production_readiness_v221.py "<episode>" --stage preimage` for V2.2.1+ Episodes. World Identity + Character Appearance Anchor must PASS; never weaken the default merely to make generation easier.
- Directing Quality: before Frame Contract compile, author+LOCK meta/capture-event-contract.json and meta/world-state.json. Every frame must explain why it is captured now; sensitive identity/recorder state changes need a story_event. Run capture_event_contract.py validate and world_state.py validate.
- Temporal Continuity: after world-state is authored, author+LOCK meta/temporal-continuity.json bound to world-state SHA. Track elapsed minutes/daypart/weather/precipitation/ambient light. Night↔day or major weather/light jumps require explicit elapsed time + transition_reason. Run temporal_continuity_gate.py validate.
- Scene-Aware Wardrobe: then author+LOCK meta/wardrobe-contract.json bound to temporal continuity. Clothing must follow altitude/temperature/weather/daypart/activity. Sichuan-Tibet/high-altitude cool-cold outdoor defaults shell/fleece/warm trousers/hat; low-altitude warm, vehicle, lodging or county-town scenes may use attractive camisoles/skirts/light layers. Cold outdoor skirt requires thick/thermal tights + warm outer layer; cold high-altitude camisole without warm outer layer is FAIL. Every look_id change needs a believable change_reason. Run wardrobe_contract.py validate.
- STORY_OS_V211_PERF_FINAL_R2: when authoring frame directives, keep `escalation_from` as narrative continuity only. Add `generation_depends_on` only when the current image literally requires a prior generated pixel asset; otherwise use an empty list.
- author concise per-frame production prompt source files required by the existing image scheduler / prompt-package compiler.
- resolve intro policy and allow provisional text-only release drafts.
- DO NOT invoke image_generation, DO NOT create Visual Lock images, DO NOT advance the Episode stage.
Stop only when environment/frame contracts are machine-verifiable and image production can start without story work.
""",
"PROMPT_AUTHORING": """
TARGET: author and validate production prompts, then stop before any image dispatch.
- Story, Storyboard, Character Contract, Environment/Impact Contract and Resolved Frame Contracts are frozen inputs. Do not rewrite them.
- Author or repair concise per-frame production prompt source files from the frozen Frame Contracts; preserve continuity and capture realism.
- Use the existing prompt package compiler/validator and report unresolved contract conflicts instead of inventing missing authority.
- Do NOT call image_generation, do NOT dispatch or repair images, and do NOT advance the Episode stage.
""",
"VISUAL_LOCK":"""
TARGET: reach VISUAL_CALIBRATED and stop there.
- create/verify Environment + Impact Contract.
- compile/verify Resolved Frame Contracts.
- Directing Quality: before Frame Contract compile, author+LOCK meta/capture-event-contract.json and meta/world-state.json. Every frame must explain why it is captured now; sensitive identity/recorder state changes need a story_event. Run capture_event_contract.py validate and world_state.py validate.
- Temporal Continuity: after world-state is authored, author+LOCK meta/temporal-continuity.json bound to world-state SHA. Track elapsed minutes/daypart/weather/precipitation/ambient light. Night↔day or major weather/light jumps require explicit elapsed time + transition_reason. Run temporal_continuity_gate.py validate.
- Scene-Aware Wardrobe: then author+LOCK meta/wardrobe-contract.json bound to temporal continuity. Clothing must follow altitude/temperature/weather/daypart/activity. Sichuan-Tibet/high-altitude cool-cold outdoor defaults shell/fleece/warm trousers/hat; low-altitude warm, vehicle, lodging or county-town scenes may use attractive camisoles/skirts/light layers. Cold outdoor skirt requires thick/thermal tights + warm outer layer; cold high-altitude camisole without warm outer layer is FAIL. Every look_id change needs a believable change_reason. Run wardrobe_contract.py validate.
- use exactly four current V2.1 Visual Lock admissions: ordinary_baseline, worst_capture_condition, first_major_anomaly, high_impact_admission.
- For multi-person travel/return-home/outing stories, the Visual Lock planner machine-prioritizes the valid Frame 01/02 selfie declared by meta/opening-social-anchor.json as ordinary_baseline, with legacy ordinary-frame fallback only when no valid anchor exists.
- execute Visual Lock as a REAL 1+3 barrier: import the four admissions, run the scheduler once so ONLY ordinary_baseline can generate, then inspect that actual baseline image before any other admission is allowed to start.
- After baseline generation, run visual_lock_baseline_gate.py prepare-review. Inspect actual pixels and honestly fill meta/visual-lock-baseline-review.json: all required checks plus normalized primary-character face_boxes. Run visual_lock_baseline_gate.py approve. A PASS creates a PROVISIONAL SHA-bound character pixel master and deterministic individual crops; a FAIL must repair/review baseline and MUST NOT release the parallel three.
- Re-run the scheduler only after baseline approval. The scheduler re-arbitrates references at execution time, and worst_capture_condition / first_major_anomaly / high_impact_admission may then run in parallel with the approved PROVISIONAL baseline identity reference.
- After all four admissions exist, run the normal bind/critic/final Visual Lock review. FOUR-admission PASS promotes the same baseline image from PROVISIONAL to LOCKED pixel master. Real-person style references never become identity masters.
- STORY_OS_V211_PERF_RECOVERY: if the unified critic reports technical infrastructure failure (for example INPUT_IMAGES_UNAVAILABLE / Windows sandbox 1385 / critic return code 11), DO NOT convert that into content failure, DO NOT loop content repairs, and DO NOT mutate candidate decisions to failed. Stop this bounded step promptly and preserve meta/visual-critic-runtime.json; the parent DAG may run bounded speculative production.
- generate/review/repair only those admissions as required.
- use image model policy from Runtime Request authority; the default comes from config/storyos.yaml.
- record honest delegated visual approval only after evidence passes.
- advance only to VISUAL_CALIBRATED.
DO NOT run full Batch or release.
""",
"PRODUCTION":"""
TARGET: reach PRODUCTION_PASSED and stop there.
- author concise per-frame prompts for remaining frames.
- STORY_OS_V211_PERF_FINAL_R2: `escalation_from` is narrative-only and MUST NOT serialize image generation. Use `generation_depends_on` only for a true pixel prerequisite (image edit, required prior generated asset, or an explicit locked visual state that cannot be represented by contracts); default it to empty.
- import/run bounded image scheduler, max 3 image jobs. Reference arbitration remains max 2 refs: use locked identity only on character frames, then choose prop/location/capture_style by frame function; individual derived crop is preferred for an explicit single-character subject.
- reuse clean SHA-bound PASS evidence.
- technical failures are retryable and do not consume content repair.
- Fast Scout is triage only; run final incremental semantic review/audit.
- repair only failed dirty frames.
- If Execution Capsule effective_execution_mode=repair_only: override the normal target; process ONLY Repair Queue / dirty / failed frames, never generate untouched originals, never rewrite Story/Storyboard, and do not require state advancement when unrelated originals are still pending.
- advance only to PRODUCTION_PASSED.
DO NOT do subtitles or Release.
""",
"RELEASE":"""
TARGET: reach PUBLISH_READY and stop there.
- resolve meta/intro-policy.json before final copy. The intro opening must use one of the four approved reference families but be naturally rewritten for the actual Story; never mechanically substitute XXX.
- generate exactly one title as an internal candidate only. Title is not required for PUBLISH_READY and is not included in final delivery by default.
- create/audit captions and publish copy/assets from PASS production frames.
- Subtitle placement: inspect each approved base before rendering and author meta/subtitle-layout.json. Prefer the LEFT-MIDDLE safe zone (roughly 42%-62% image height, x=72) and move away only when faces, anomaly evidence, hands/actions, props, native text or causal clues occupy that zone; every outside-zone override needs a concrete safe_zone_override_reason. Never place text over key information.
- Caption writing: first-person conversational immediate-record language, short and eye-catching without clickbait boilerplate; one function per frame; canonical renderer still caps at two lines (stricter than the requested three).
- Use meta/voice-contract.json as narrator authority. Run text_audit.py, then write meta/subtitle-voice-review.json bound to Voice Contract SHA and caption source SHA. continuous-three-frame, read-aloud, delete-subtitle, knowledge-boundary and clue-payoff tests must all PASS.
- complete release/compliance checks.
- build+verify Final Candidate Snapshot. When character master evidence exists, Snapshot must lock master metadata, master image, crop manifest and every derived crop SHA.
- record honest delegated release approval.
- transition only to PUBLISH_READY.
- ZIP is a delivery adapter, not CODEX completion.
DO NOT mark PUBLISHED or fabricate metrics.
"""}

# PREIMAGE protocol split: each invocation is forbidden from writing authority.
# The parent single-writer commit validates the returned candidate separately.
STEP_DIRECTIVES.update({
"PREIMAGE_CHARACTER_FINALIZE": """TARGET: produce only the CHARACTER_FINALIZE Candidate declared by the execution capsule/request. Read the locked Story and Character Seed Contract. Validate final identity, wardrobe baseline, POV and textual appearance anchor. Do not rewrite Story or create pixel masters. Write only the declared candidate JSON; never modify shared authority, episode-state or gates.""",
"PREIMAGE_ENVIRONMENT": """TARGET: produce only the ENVIRONMENT_PREPARE Candidate declared by the execution capsule/request. Cover physical environment, weather, impact and environment frame directives. The candidate must satisfy the Phase-3 Environment Contract before commit: whenever a segment condition implies a different daypart (morning/midday/afternoon/dusk/night), that segment must carry a matching time_of_day instead of inheriting an incompatible baseline. For EVERY frame, frame_mode=normal_record REQUIRES impact_level 0 or 1, never 2 or higher; frame 16 is the ordinary physical act of a camera strap snapping and a companion needing support, so normal_record impact_level must be at most 1. Use anomaly_reveal only for genuinely observable anomalies with matching evidence and impact 1..2. Provide directives for every frame and keep condition/time_of_day physically consistent. Do not change Character, Story, World or other visual authority. Write only the declared candidate JSON; never modify shared authority, episode-state or gates.""",
"PREIMAGE_WORLD": """TARGET: produce only the WORLD_PREPARE Candidate declared by the execution capsule/request. Cover world identity/state, capture-event physical continuity, temporal continuity and wardrobe constraints. The complete canonical frozen World obligations embedded as HOST_FROZEN_WORLD must be copied into their matching Candidate payload scopes at identical nested paths and with no missing keys or altered values; derived notes may be added only without altering any frozen value. Do not rewrite Story or generate images. Write only the declared candidate JSON; never modify shared authority, episode-state or gates.""",
"PREIMAGE_VISUAL_NARRATIVE": """TARGET: produce only the VISUAL_NARRATIVE_PREPARE Candidate declared by the execution capsule/request. Cover visual narrative core, shot progression, capture grammar and anomaly progression. Do not own environment physics or character identity. Write only the declared candidate JSON; never modify shared authority, episode-state or gates.""",
})

SCOPED_MODEL_ROLES={
    "CREATIVE_STORY":"story.authoring",
    "PREIMAGE_COMPILE":"preimage.frame_contract",
    "PROMPT_AUTHORING":"prompt.production",
    "PREIMAGE_ENVIRONMENT":"preimage.world_prepare",
    "PREIMAGE_WORLD":"preimage.world_prepare",
    "PREIMAGE_CHARACTER_FINALIZE":"preimage.character_finalize",
    "PREIMAGE_VISUAL_NARRATIVE":"preimage.visual_narrative",
    "VISUAL_LOCK":"vision.visual_lock",
    "PRODUCTION":"image.controller",
    "RELEASE":"release",
}

def resolved_model(step, ep):
    role=SCOPED_MODEL_ROLES.get(step)
    if not role:
        raise ValueError(f"no Model Policy role configured for scoped step: {step}")
    result=model_policy.resolve(role,episode=ep)
    model=str(result.get("model") or "").strip()
    effort=str(result.get("reasoning_effort") or "").strip().lower()
    if not model or not effort or not result.get("model_policy_sha256"):
        raise ValueError(f"Model Policy did not resolve a complete binding for {role}")
    return result

def codex_exec_command(codex, binding, image_paths=(), sandbox="workspace-write"):
    args=prefix(codex)+["exec","--skip-git-repo-check","--ephemeral",
                          "-m",str(binding["model"]),
                          "-c",f'model_reasoning_effort="{binding["reasoning_effort"]}"',
                          "-s",str(sandbox),"-C",str(ROOT),"--json"]
    for image in image_paths or ():
        args.extend(["--image",str(Path(image).resolve())])
    return args+["-"]


def execute_model_call(ep, step, binding, prompt_text, *, codex_raw=None, timeout=None,
                       run_id=None, trace_id=None, logical_asset_key=None, image_paths=(),
                       call_id=None, output_handle=None, sandbox="workspace-write",
                       receipt_fields=None, persist_output_stream=False,
                       runner_request_id=None):
    """Run one real scoped Codex model call and persist its policy-bound receipt."""
    ep=Path(ep).resolve()
    call_id=call_id or uuid.uuid4().hex
    worker_id=uuid.uuid4().hex
    run_id=run_id or "canary_"+uuid.uuid4().hex
    trace_id=trace_id or "ST_"+uuid.uuid4().hex[:16]
    started_at=runtime_observability.now()
    started=time.monotonic()
    status="FAILED"
    cmd=[]
    execution_started=False
    runner_diagnostics={}
    try:
        codex=resolve_codex(codex_raw)
        cmd=codex_exec_command(codex,binding,image_paths=image_paths,sandbox=sandbox)
        _model_event(ep,"WORKER_DISPATCH_STARTED",step,binding,worker_id=worker_id,
                     generation_key=call_id,status="started",run_id=run_id,trace_id=trace_id,
                     logical_asset_key=logical_asset_key)
        _model_event(ep,"WORKER_DISPATCH_COMMITTED",step,binding,worker_id=worker_id,
                     generation_key=call_id,status="committed",run_id=run_id,trace_id=trace_id,
                     logical_asset_key=logical_asset_key,wait_ms=0.0)
        # ``subprocess.run`` in direct mode requires a real file descriptor for
        # stdout; ``io.StringIO`` has no ``fileno`` and fails before Codex starts.
        # Capture the exact controller preflight response through PIPE in both
        # direct and bridged modes, then copy it into the caller's in-memory
        # stream for sentinel validation. Other scoped work keeps its existing
        # streaming/discard behavior.
        capture_preflight_output = step == "EXACT_CONTROLLER_CAPABILITY_PREFLIGHT"
        capture_output_stream = capture_preflight_output or bool(runner_request_id) or (
            persist_output_stream and output_handle is not None
        )
        sink = subprocess.PIPE if capture_output_stream else (output_handle or subprocess.DEVNULL)
        execution_started=True
        cp=codex_user_runner.run_model_codex(cmd,input=prompt_text,text=True,encoding="utf-8",
            stdout=sink,stderr=subprocess.STDOUT,timeout=timeout,check=False,
            task_type="scoped_step",request_id=runner_request_id)
        rc=int(cp.returncode)
        if capture_output_stream:
            captured = getattr(cp, "stdout", None)
            if isinstance(captured, bytes):
                captured = captured.decode("utf-8", "replace")
            if output_handle is not None and captured:
                output_handle.write(str(captured))
                output_handle.flush()
        if capture_preflight_output:
            runner_diagnostics=_safe_runner_diagnostics(getattr(cp,"remote",None))
        status="SUCCESS" if rc==0 else "FAILED"
    except subprocess.TimeoutExpired as exc:
        if not execution_started:
            raise
        if step == "EXACT_CONTROLLER_CAPABILITY_PREFLIGHT":
            runner_diagnostics=_safe_runner_diagnostics(getattr(exc,"remote",None))
        rc=124
        status="TIMEOUT"
    except Exception:
        if not execution_started:
            raise
        rc=1
        status="FAILED"
    finished_at=runtime_observability.now()
    duration_ms=round((time.monotonic()-started)*1000,3)
    receipt={
        "receipt_schema_version":1,
        "episode_id":__import__("logical_asset_identity").episode_id(ep),
        "run_id":run_id,"trace_id":trace_id,"step":step,"call_id":call_id,
        "model_role":binding.get("role") or SCOPED_MODEL_ROLES.get(step),
        "profile":binding.get("profile"),"requested_model":binding.get("model"),
        "effective_model":binding.get("model"),
        "reasoning_effort":binding.get("reasoning_effort"),
        "model_policy_version":binding.get("policy_version"),
        "model_policy_sha256":binding.get("model_policy_sha256"),
        "provider":"codex_subscription","runner":"codex exec",
        "started_at":started_at,"finished_at":finished_at,"duration_ms":duration_ms,
        "status":status,"model_binding_source":"EPISODE_BOUND_MODEL_POLICY",
        "effective_model_source":"EXPLICIT_RUNTIME_BINDING",
        "codex_argv":cmd,
        "logical_asset_key":logical_asset_key,
        "runner_request_id":runner_request_id,
    }
    if step == "EXACT_CONTROLLER_CAPABILITY_PREFLIGHT":
        receipt["runner_diagnostics"]=runner_diagnostics
    if isinstance(receipt_fields, dict):
        receipt.update(receipt_fields)
    if persist_output_stream and output_handle is not None and hasattr(output_handle,"getvalue"):
        receipt["scoped_output_stream"]=output_handle.getvalue()
    receipt_path=runtime_observability.write_model_execution_receipt(ep,receipt=receipt)
    _model_event(ep,"MODEL_EXECUTION",step,binding,worker_id=worker_id,
        generation_key=call_id,duration_ms=duration_ms,status=status,run_id=run_id,
        trace_id=trace_id,call_id=call_id,requested_model=binding.get("model"),
        effective_model_source="EXPLICIT_RUNTIME_BINDING",started_at=started_at,
        finished_at=finished_at,receipt_path=str(receipt_path),logical_asset_key=logical_asset_key)
    _model_event(ep,"WORKER_RESULT_RECEIVED",step,binding,worker_id=worker_id,
        generation_key=call_id,duration_ms=duration_ms,status=status.lower(),run_id=run_id,
        trace_id=trace_id,call_id=call_id,logical_asset_key=logical_asset_key)
    return rc,receipt


def _safe_runner_diagnostics(remote):
    """Persist only non-secret runner metadata needed to explain scoped failures."""
    if not isinstance(remote,dict):
        return {}
    request_id=str(remote.get("request_id") or "").strip() or None
    durable_result_present=False
    if request_id:
        try:
            durable = codex_user_runner.read_task_result(request_id)
            # read_task_result may return {} for a missing or untrusted file.
            # An empty dict must NEVER count as durable controller evidence.
            if (isinstance(durable, dict)
                    and durable.get("schema_version") == 1
                    and durable.get("request_id") == request_id
                    and type(durable.get("returncode")) is int
                    and type(durable.get("output_bytes")) is int
                    and 0 <= durable["output_bytes"] <= 32 * 1024 * 1024
                    and isinstance(durable.get("output_base64"), str)
                    and isinstance(durable.get("output_sha256"), str)
                    and re.fullmatch(r"[0-9a-f]{64}", durable["output_sha256"])):
                output = base64.b64decode(
                    durable["output_base64"], validate=True)
                durable_result_present = (
                    len(output) == durable["output_bytes"]
                    and hashlib.sha256(output).hexdigest()
                    == durable["output_sha256"])
        except (ValueError, TypeError, binascii.Error, OSError):
            durable_result_present=False
    return {
        "request_id":request_id,
        "returncode":remote.get("returncode"),
        "elapsed_seconds":remote.get("elapsed_seconds"),
        "timed_out":bool(remote.get("timed_out",False)),
        "task_type":str(remote.get("task_type") or "") or None,
        "transport":str(remote.get("transport") or "") or None,
        "durable_result_present":durable_result_present,
    }


def run_repair_prompt_task(ep, *, task_input, codex_raw=None, timeout=None):
    """Run/reuse an internal prompt.repair task without adding a Runtime DAG node."""
    import io
    import json
    import hashlib
    import inflight_codex_task
    import logical_asset_identity

    ep=Path(ep).resolve()
    binding=model_policy.resolve("prompt.repair",episode=ep)
    required=("logical_asset_key","source_generation_key","source_artifact_sha256",
              "review_receipt_sha256","policy_sha256")
    missing=[key for key in required if not str(task_input.get(key) or "").strip()]
    if missing:
        raise ValueError("repair prompt task inputs missing: "+", ".join(missing))
    if str(binding.get("model_policy_sha256") or "") != str(task_input["policy_sha256"]):
        raise ValueError("repair prompt policy SHA differs from frozen task input")
    text=("你是限定范围的图片返修提示词编写任务。只输出 JSON：{\\\"repair_instruction\\\":\\\"...\\\"}。"
          "生成最小修改指令；保留所有已通过的人物身份、服装、场景、镜头、动作和连续性，仅修改明确失败维度。"
          "不得重写故事或自由创作整帧。\n\n任务证据：\n"+
          json.dumps(task_input,ensure_ascii=False,sort_keys=True,indent=2))
    source_sha=hashlib.sha256(json.dumps(task_input,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()
    fingerprint=inflight_codex_task.fingerprint(
        step="REPAIR_PROMPT",prompt=text,source_sha256=source_sha,
        model_role="prompt.repair",effective_model=str(binding["model"]),
        reasoning_effort=str(binding["reasoning_effort"]),
        model_policy_sha256=str(binding["model_policy_sha256"]),
        runtime_request_sha="",evidence_sha256=source_sha)
    call_id=fingerprint[:32]
    prompt_sha=hashlib.sha256(text.encode("utf-8")).hexdigest()
    receipt_path=ep/"meta/provider-receipts/model-executions"/(call_id+".json")
    output_path=ep/"meta/runtime/repair-prompts"/(call_id+".txt")
    if receipt_path.is_file():
        receipt=json.loads(receipt_path.read_text(encoding="utf-8"))
        valid_receipt=(receipt.get("status")=="SUCCESS" and receipt.get("task_fingerprint")==fingerprint
                and receipt.get("prompt_sha256")==prompt_sha
                and receipt.get("source_artifact_sha256")==task_input["source_artifact_sha256"]
                and receipt.get("review_receipt_sha256")==task_input["review_receipt_sha256"]
                and receipt.get("model_policy_sha256")==binding.get("model_policy_sha256"))
        output=output_path.read_text(encoding="utf-8").strip() if output_path.is_file() else ""
        if valid_receipt and not output and receipt.get("scoped_output_stream"):
            import codex_critic_runner
            recovered=codex_critic_runner.recover_completed_agent_json(receipt["scoped_output_stream"])
            output=str((recovered or {}).get("repair_instruction") or "").strip()
            if output and len(output)<=250 and len(output.encode("utf-8"))<=860:
                output_path.parent.mkdir(parents=True,exist_ok=True)
                output_path.write_text(output+"\n",encoding="utf-8",newline="\n")
                receipt["repair_output_sha256"]=hashlib.sha256(output.encode("utf-8")).hexdigest()
                try:
                    receipt["repair_prompt_path"]=str(output_path.relative_to(ROOT))
                except ValueError:
                    receipt["repair_prompt_path"]=str(output_path)
                receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        if valid_receipt and output:
            return {"status":"REUSED","fingerprint":fingerprint,"prompt_path":str(output_path),"receipt_path":str(receipt_path),"receipt":receipt}
    stream=io.StringIO()
    rc,receipt=execute_model_call(
        ep,"REPAIR_PROMPT",binding,text,codex_raw=codex_raw,timeout=timeout,
        logical_asset_key=task_input["logical_asset_key"],call_id=call_id,output_handle=stream,
        persist_output_stream=True,
        receipt_fields={"task_fingerprint":fingerprint,"prompt_sha256":prompt_sha,
            "source_generation_key":task_input["source_generation_key"],
            "source_artifact_sha256":task_input["source_artifact_sha256"],
            "review_receipt_sha256":task_input["review_receipt_sha256"]})
    if rc != 0:
        return {"status":"TECH_FAILED","fingerprint":fingerprint,"receipt":receipt}
    import codex_critic_runner
    result=codex_critic_runner.recover_completed_agent_json(stream.getvalue())
    instruction=str((result or {}).get("repair_instruction") or "").strip()
    if not instruction:
        raise ValueError("repair prompt task returned no completed repair_instruction JSON")
    if len(instruction)>250 or len(instruction.encode("utf-8"))>860:
        raise ValueError("repair prompt exceeds Story OS image prompt byte budget")
    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_text(instruction+"\n",encoding="utf-8",newline="\n")
    try:
        prompt_ref=str(output_path.relative_to(ROOT))
    except ValueError:
        prompt_ref=str(output_path)
    receipt.update({"task_fingerprint":fingerprint,"prompt_sha256":prompt_sha,
        "source_generation_key":task_input["source_generation_key"],
        "source_artifact_sha256":task_input["source_artifact_sha256"],
        "review_receipt_sha256":task_input["review_receipt_sha256"],
        "repair_output_sha256":hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        "repair_prompt_path":prompt_ref})
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return {"status":"SUCCESS","fingerprint":fingerprint,"prompt_path":str(output_path),"receipt_path":str(receipt_path),"receipt":receipt}

def scoped_fingerprint(ep, step, text, binding, source_sha):
    request=runtime_request.authority_for_episode(ep) or {}
    request_sha=runtime_request.authority_sha256(request) if request else ""
    return inflight_codex_task.fingerprint(
        step=step,prompt=text,source_sha256=source_sha,
        model_role=str(binding.get("role") or SCOPED_MODEL_ROLES[step]),
        effective_model=str(binding.get("model") or ""),
        reasoning_effort=str(binding.get("reasoning_effort") or ""),
        model_policy_sha256=str(binding.get("model_policy_sha256") or ""),
        runtime_request_sha=request_sha,evidence_sha256=source_sha)

def resolve_codex(raw):
    import codex_cli_contract
    return codex_cli_contract.resolve_path(raw)

def prefix(codex):
    import codex_cli_contract
    return codex_cli_contract.command_prefix(codex)

def request_block(ep,step):
    data=runtime_request.authority_for_episode(ep)
    if not data: return "<runtime_request>ABSENT</runtime_request>"
    if step=="CREATIVE_STORY":
        payload={"creative_request":runtime_request.creative_request_view(data)}
    else:
        payload=runtime_request.partitioned_view(data)
    return "<runtime_request>\n"+json.dumps(payload,ensure_ascii=False,indent=2)+"\n</runtime_request>"

def prompt(ep,step):
    rel=ep.relative_to(ROOT).as_posix()
    if step=="CREATIVE_STORY":
        directing_quality.enable(ep)
        character_contract.prepare(ep,force=False)
        character_visual_contract.prepare(ep,force=False)
        resource_library.resolve(ep,write=True)
    if step in {"PREIMAGE_COMPILE","VISUAL_LOCK"}:
        resource_library.resolve(ep,write=True)
    if step=="RELEASE":
        intro_policy.resolve(ep,write=True)
    capsule=execution_capsule.compile_capsule(ep,step,write=True)
    # PREIMAGE uses one immutable Story/Snapshot authority. Give the World
    # writer the actual Host-frozen nested values, not a vague instruction to
    # reconstruct them by searching the repository; the independent semantic
    # comparator still verifies every frozen leaf.
    frozen_world_block=""
    if step=="PREIMAGE_WORLD":
        import preimage_authority_snapshot
        import preimage_task_contract
        from agents import world_prepare_model_producer
        snapshot=preimage_authority_snapshot.build(ep,write=False)
        task=preimage_task_contract.task_contract(ep,"WORLD_PREPARE",snapshot,resume=True)
        frozen=world_prepare_model_producer.freeze_task(ep,task)
        frozen_world_block=(
            "<HOST_FROZEN_WORLD>\\n"
            + json.dumps(frozen["input_contract"]["world_prepare_capsule"]["obligations"]["scopes"],
                         ensure_ascii=False,sort_keys=True)
            + "\\n</HOST_FROZEN_WORLD>"
        )
    return f"""You are a bounded Story OS V2.1 scoped worker for exactly {rel}.
Use the derived Execution Capsule first; do NOT reread the entire repository policy stack by default.
Open authoritative source files listed by the capsule only when details are missing or a conflict must be resolved.
Do not spawn another full-auto supervisor. Do not perform downstream work beyond this step.
Reuse valid SHA-bound evidence. Never fabricate PASS/review/user approval.
Reality constrains capture behavior, not concept ambition.
Read the embedded FAST_RUNTIME_INDEX first. Do NOT recursively scan the repository while its declared read set + Execution Capsule are sufficient. Broaden only for a missing dependency or real conflict.

<FAST_RUNTIME_INDEX>
{runtime_index_block(step)}
</FAST_RUNTIME_INDEX>

<EXECUTION_CAPSULE>
{json.dumps(capsule,ensure_ascii=False,indent=2)}
</EXECUTION_CAPSULE>

{frozen_world_block}

{request_block(ep,step)}

{runtime_memory_advice.prompt_block(ep) if step=="CREATIVE_STORY" else ""}

<SCOPED_STEP id="{step}">
{STEP_DIRECTIVES[step].strip()}
</SCOPED_STEP>

Stop when the bounded target is reached. The parent runtime independently verifies all gates.
"""

def _attach(ep,step,text,timeout,log,binding,poll_seconds=None):
    """Claim a Codex result a dead Driver already paid for, or wait for it.

    Returns (rc, handled). ``handled`` is False when there is nothing to attach
    to and the caller should submit a new task.

    A result is only ever adopted through inflight_codex_task.validate_result,
    which requires rc=0, matching request_id, matching stdin SHA and an output
    that hashes to its own recorded digest. Anything else is treated as no result
    at all, so a half-written or drifted file cannot close a step.
    """
    if not codex_user_runner.bridge_required():
        return None,False
    source_sha=attach_source_sha256(ep,step)
    fp=scoped_fingerprint(ep,step,text,binding,source_sha)
    verdict=inflight_codex_task.classify(ep,step=step,fingerprint_value=fp)
    if verdict["decision"]==inflight_codex_task.ADOPT:
        with log.open("ab") as h:
            h.write(verdict["output"])
        # The paid task is no longer in-flight once its durable result has been
        # adopted.  Leaving the record behind makes a later Driver cycle adopt
        # the same business result forever, so a downstream gate failure can
        # never progress into a real repair submission.
        inflight_codex_task.clear(ep,step)
        return int(verdict["returncode"]),True
    if verdict["decision"]!=inflight_codex_task.WAIT:
        return None,False
    # The task is still running under the resident user-mode runner. Submitting
    # the same step again would run it twice, so wait for the result the dead
    # Driver's call would have received instead.
    record=verdict.get("record") or {}
    deadline=_deadline_epoch(record)
    poll=ATTACH_POLL_SECONDS if poll_seconds is None else max(0.0,float(poll_seconds))
    print(f"ATTACH {step} request_id={record.get('request_id')} "
          f"reason={verdict['reason']} validation={verdict.get('validation')}",flush=True)
    while True:
        if deadline is not None and time.time()>=deadline:
            return ATTACH_TIMEOUT_RC,True
        if poll:
            time.sleep(poll)
        again=inflight_codex_task.classify(ep,step=step,fingerprint_value=fp)
        if again["decision"]==inflight_codex_task.ADOPT:
            with log.open("ab") as h:
                h.write(again["output"])
            inflight_codex_task.clear(ep,step)
            return int(again["returncode"]),True
        if again["decision"]==inflight_codex_task.RESUBMIT and again.get("reason")!="WITHIN_TASK_DEADLINE":
            # The task is provably gone and left nothing usable behind.
            return None,False
        if not poll:
            return ATTACH_TIMEOUT_RC,True


def _deadline_epoch(record):
    raw=str(record.get("deadline_at") or "")
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw).timestamp()
    except (TypeError,ValueError):
        return None


def run_step(ep,step,codex_raw=None,timeout=None,attach_poll_seconds=None,run_id=None,trace_id=None):
    if step not in STEP_DIRECTIVES: raise ValueError(f"unknown scoped step: {step}")
    if timeout is None:
        timeout = runtime_timeout_policy.seconds("codex_scoped_step")
    perf_run=episode_performance.safe_begin_stage(ep,step,source="scoped_codex_worker")
    rc=99;log=ep/"meta/scoped-workers"/f"{step.lower()}.jsonl";log.parent.mkdir(parents=True,exist_ok=True)
    text=prompt(ep,step)
    binding=resolved_model(step,ep)
    if not runtime_router.local_codex_allowed(explicit=bool(codex_raw)):
        runtime,_=runtime_router.detect()
        request=product_runtime_adapter.build_request(
            ep,runtime=runtime,mode="full_auto",resume=True,source=f"scoped_codex_worker:{step}")
        log.write_text(json.dumps({"status":"HOST_ACTION_REQUIRED","request":request},ensure_ascii=False)+"\n",encoding="utf-8")
        episode_performance.safe_end_stage(ep,step,perf_run,status="HOST_ACTION_REQUIRED",
                                           metadata={"timeout_seconds":timeout,"log":str(log)})
        return product_runtime_adapter.HOST_ACTION_REQUIRED_RC,str(log)
    attached,handled=_attach(ep,step,text,timeout,log,binding,poll_seconds=attach_poll_seconds)
    if handled:
        rc=int(attached)
        episode_performance.safe_end_stage(ep,step,perf_run,status="PASS" if rc==0 else f"RC_{rc}",
                                           metadata={"timeout_seconds":timeout,"log":str(log),"attached":True})
        return rc,str(log)
    request_id=None
    collected=False
    try:
        resolve_codex(codex_raw)
        request_id=uuid.uuid4().hex if codex_user_runner.bridge_required() else None
        if request_id:
            # Written before submission on purpose: a record written afterwards
            # would be missing in exactly the case it exists for.
            inflight_codex_task.begin(
                ep,step=step,request_id=request_id,
                fingerprint_value=scoped_fingerprint(
                    ep,step,text,binding,attach_source_sha256(ep,step)),
                stdin_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                timeout_seconds=int(timeout),
                source_sha256=attach_source_sha256(ep,step))
        with log.open("a",encoding="utf-8",newline="\n") as h:
            try:
                worker_id=uuid.uuid4().hex
                generation_key=request_id or worker_id
                rc,_receipt=execute_model_call(ep,step,binding,text,codex_raw=codex_raw,
                    timeout=timeout,run_id=run_id,trace_id=trace_id,
                    call_id=generation_key,runner_request_id=request_id,output_handle=h)
                collected=True
            except subprocess.TimeoutExpired:
                rc=124; collected=True
        return rc,str(log)
    finally:
        # Only a collected outcome clears the record. If this process dies while
        # the task runs, the record stays and the next Driver attaches instead of
        # paying for the step again.
        if collected and request_id:
            inflight_codex_task.clear(ep,step)
        episode_performance.safe_end_stage(ep,step,perf_run,status="PASS" if rc==0 else f"RC_{rc}",
                                           metadata={"timeout_seconds":timeout,"log":str(log)})

def self_test():
    assert {"CREATIVE_STORY","PREIMAGE_COMPILE","PROMPT_AUTHORING","PREIMAGE_ENVIRONMENT","PREIMAGE_WORLD","PREIMAGE_CHARACTER_FINALIZE","PREIMAGE_VISUAL_NARRATIVE","VISUAL_LOCK","PRODUCTION","RELEASE"}.issubset(STEP_DIRECTIVES)
    print("SCOPED CODEX WORKER SELF-TEST PASS")

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("run"); p.add_argument("episode_dir"); p.add_argument("step",choices=sorted(STEP_DIRECTIVES)); p.add_argument("--codex"); p.add_argument("--timeout",type=int,default=None)
    sub.add_parser("self-test"); a=ap.parse_args()
    if a.cmd=="self-test": self_test(); return 0
    ep=Path(a.episode_dir).resolve(); rc,log=run_step(ep,a.step,codex_raw=a.codex,timeout=runtime_timeout_policy.resolve("codex_scoped_step", a.timeout))
    print(json.dumps({"step":a.step,"returncode":rc,"log":log},ensure_ascii=False)); return rc

if __name__=="__main__": raise SystemExit(main())

# STORY_OS_V211_RUNTIME_CLOSURE_R31
