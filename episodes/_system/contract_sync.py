#!/usr/bin/env python3
"""Story OS contract/adapter consistency validator.

Checks contract parity, not implementation parity. The product version comes from
story_os_manifest.json. Episode stage truth remains meta/episode-state.json.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from story_os_contract import CANONICAL_STAGES, load_contract
import storyos_config
import story_json

CORE_ENGINE_FILES = [
    "story_os_contract.py",
    "episode_state.py",
    "validate_episode.py",
    "machine_gate.py",
    "evidence_gate.py",
    "release_package.py",
    "canvas_normalize.py",
    "delegated_delivery.py",
    "codex_auto_orchestrator.py",
    "story_review.py",
    "visual_review.py",
    "frame_semantic_review.py",
    "subtitle_layout.py",
    "incremental_closure.py",
    "incremental_frame_review.py",
    "media_workspace.py",
    "runtime_log_policy.py",
]
# STORY_OS_V2_6_1_1_SINGLE_DRIVER: the resident driver (story_os.py runner) and a
# step engine (runtime_dag.py) must stay distinguishable in the portal, because an
# agent that cannot tell them apart drives the DAG by hand and leaves the episode
# unattended -- that is exactly what happened to 尸解仙 on 2026-09-14. Docs alone
# already failed once, so the block is machine-checked here on every doctor/CI run.
SINGLE_DRIVER_MARKER = "STORY_OS_SINGLE_DRIVER"
SINGLE_DRIVER_REQUIRED_TOKENS = (
    "story_os.py runner",
    "story_os.py run",
    "story_os.py driver",
    "runtime_dag",
    "host_loop",
    "orphaned_pending_work",
)
REQUIRED_CAPABILITIES = {
    "single_state_machine",
    "multi_runtime",
    "machine_gate",
    "evidence_gate",
    "production_ledger",
    "frame_reviews",
    "canvas_normalization",
    "deterministic_postflight",
    "delegated_delivery",
    "release_manifest",
    "minimal_edit_contract",
    "story_semantic_review",
    "visual_profile_enforcement",
    "deterministic_subtitle_layout",
    "actual_frame_semantic_review",
    "sha_bound_frame_reviews",
    "release_evidence_closure",
    "incremental_closure",
    "dirty_set_propagation",
    "incremental_frame_review",
    "caption_fingerprint_binding",
    "local_media_workspace",
    "media_sha_index",
    "safe_media_migration",
    "product_runtime_first",
    "local_codex_explicit_only",
    "no_silent_codex_fallback",
    "product_runtime_host_action",
    "product_runtime_image_route",
    "continuous_work_host_loop",
    "derived_next_action",
    "preimage_runtime_node",
    "work_actual_pixel_review_barrier",
    "canonical_episode_discovery",
    "semantic_text_encoding_health",
    "runtime_path_portability",
    "canonical_module_index",
    "codex_batch_inflight_3",
}
ADAPTER_SKILLS = [
    Path("skills/dali-cat-story/SKILL.md"),
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def read_json(path: Path) -> dict:
    return story_json.read_json(path)


def declares_version(text: str, version: str) -> bool:
    return bool(re.search(rf"\bV?{re.escape(version)}\b", text, flags=re.IGNORECASE))


def tracked_local_artifacts(root: Path) -> list[str]:
    if not (root / ".git").exists():
        return []
    try:
        p = subprocess.run(
            [
                "git", "-C", str(root), "ls-files", "--",
                ".story-os-v*.installed.json",
                ".story-os-*-backups/**",
                ".story-upgrade-backups/**",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return []
    if p.returncode != 0:
        return []
    # A locally deleted-but-not-yet-committed tracked path is acceptable while applying
    # the patch. CI will catch it if the deletion is not actually committed.
    return [x.strip() for x in p.stdout.splitlines() if x.strip() and (root / x.strip()).exists()]


SERIES_IDENTITY_NAME = "series-character-identity.json"


def series_master_assets(identity: dict) -> list[tuple[str, str]]:
    """(owner, repo-relative path) for every master image a series identity declares."""
    rows: list[tuple[str, str]] = []
    group = identity.get("group_identity_asset")
    if isinstance(group, dict) and str(group.get("path") or "").strip():
        rows.append(("group", str(group["path"]).strip()))
    for cid, row in (identity.get("characters") or {}).items():
        if not isinstance(row, dict):
            continue
        slots = [("primary", row.get("primary_asset"))]
        slots += [(f"supporting:{i}", s) for i, s in enumerate(row.get("supporting_assets") or [])]
        for slot, asset in slots:
            if isinstance(asset, dict) and str(asset.get("path") or "").strip():
                rows.append((f"{cid}:{slot}", str(asset["path"]).strip()))
    return rows


def untracked_series_masters(root: Path) -> list[str]:
    """Series master images are the one pixel class that MUST be committed to Git.

    Every path referenced by a series-level meta/series-character-identity.json is
    the pixel anchor of the series identity authority. A local-only master image
    cannot be resolved by a fresh clone, so the gap is reported here rather than
    surfacing later as a dangling identity binding.
    """
    if not (root / ".git").exists():
        return []
    identities = sorted(root.glob(f"episodes/**/{SERIES_IDENTITY_NAME}"))
    if not identities:
        return []
    try:
        p = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "episodes"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return []
    if p.returncode != 0:
        return []
    tracked = {item.replace("\\", "/") for item in p.stdout.split("\0") if item}

    errors: list[str] = []
    for identity_path in identities:
        declared = identity_path.relative_to(root).as_posix()
        try:
            identity = read_json(identity_path)
        except Exception as exc:
            errors.append(f"invalid series character identity {declared}: {exc}")
            continue
        for owner, rel in series_master_assets(identity):
            target = rel.replace("\\", "/")
            if not (root / target).is_file():
                errors.append(f"series master image missing for {owner}: {rel} (declared by {declared})")
            elif target not in tracked:
                errors.append(
                    f"series master image must be committed to Git for {owner}: {rel} "
                    f"(declared by {declared}; see AGENTS.md 提交规则)"
                )
    return errors


def single_driver_errors(root: Path) -> list[str]:
    rel = Path("START_HERE.md")
    p = root / rel
    if not p.is_file():
        return [f"missing contract file: {rel.as_posix()}"]
    text = read_text(p)
    begin = f"<!-- {SINGLE_DRIVER_MARKER}_BEGIN -->"
    end = f"<!-- {SINGLE_DRIVER_MARKER}_END -->"
    if text.count(begin) != 1 or text.count(end) != 1:
        return [f"{rel.as_posix()} must contain exactly one {SINGLE_DRIVER_MARKER} block"]
    body = text.split(begin, 1)[1].split(end, 1)[0]
    return [
        f"{rel.as_posix()} single-driver block must declare {token}"
        for token in SINGLE_DRIVER_REQUIRED_TOKENS
        if token not in body
    ]


def collect_errors(root: Path | None = None) -> list[str]:
    root = root or repo_root()
    errors: list[str] = []

    try:
        manifest = load_contract(root)
    except Exception as exc:
        return [f"invalid story_os_manifest.json: {exc}"]

    version = manifest.get("platform_version")
    if not isinstance(version, str) or not version.strip():
        errors.append("manifest platform_version must be a non-empty string")
        version = "<invalid>"
    semantics = manifest.get("version_semantics") or {}
    if not str(semantics.get("platform_version") or "").startswith("Root product release identifier"):
        errors.append("story_os_manifest.json must declare platform_version as the sole product-version authority")
    story_contract_source = read_text(root / "episodes/_system/story_os_contract.py")
    if 'load_contract(root).get("platform_version")' not in story_contract_source:
        errors.append("story_os_contract.py must derive Story OS version from story_os_manifest.json#platform_version")
    for rel in (Path("runtimes/runtime-contract.json"), Path("config/storyos.yaml"), Path("config/index.yaml")):
        p = root / rel
        if p.is_file() and re.search(r'(?m)^\s*["\']?platform_version["\']?\s*:', read_text(p)):
            errors.append(f"{rel.as_posix()} must not declare a second platform_version authority")
    if manifest.get("contract_schema") != 1:
        errors.append("manifest contract_schema must remain 1")
    if manifest.get("canonical_engine") != "episodes/_system":
        errors.append("canonical_engine must be episodes/_system")
    if manifest.get("canonical_state_source") != "<episode>/meta/episode-state.json":
        errors.append("canonical_state_source must remain <episode>/meta/episode-state.json")
    if manifest.get("canonical_creative_authority") != "standards/制作规范_正式版.md":
        errors.append("canonical_creative_authority drifted")
    if manifest.get("stages") != list(CANONICAL_STAGES):
        errors.append("manifest stages drifted from the canonical seven-stage machine")

    declared_capabilities = set(manifest.get("capabilities") or [])
    missing_caps = sorted(REQUIRED_CAPABILITIES - declared_capabilities)
    if missing_caps:
        errors.append("manifest missing capabilities: " + ", ".join(missing_caps))

    version_files = [
        Path("START_HERE.md"),
        Path("SKILL.md"),
        Path("episodes/_system/README.md"),
        *ADAPTER_SKILLS,
    ]
    for rel in version_files:
        p = root / rel
        if not p.is_file():
            errors.append(f"missing contract file: {rel.as_posix()}")
            continue
        if not declares_version(read_text(p), version):
            errors.append(f"{rel.as_posix()} does not declare Story OS V{version}")

    errors.extend(single_driver_errors(root))

    for rel in [Path("runtimes/runtime-contract.json"), Path("standards/AUTHORITY_INDEX.json")]:
        p = root / rel
        if not p.is_file():
            errors.append(f"missing contract file: {rel.as_posix()}")
            continue
        try:
            data = read_json(p)
            minimum = data.get("platform_min_version")
            if not isinstance(minimum, str) or not minimum.strip():
                errors.append(f"{rel.as_posix()} platform_min_version must be a non-empty string")
        except Exception as exc:
            errors.append(f"invalid {rel.as_posix()}: {exc}")

    # Product-runtime-first routing must be identical across config, runtime contract,
    # authority routing metadata and the active multi-runtime standard.
    try:
        cfg = storyos_config.load_config()
        preferred = str(storyos_config.get_path(cfg, "runtime.preferred_runtime") or "").upper()
        production_mode = str(storyos_config.get_path(cfg, "production.mode") or "").upper()
        workspace_provider = str(storyos_config.get_path(cfg, "execution.workspace.provider") or "").lower()
        image_executor = str(storyos_config.get_path(cfg, "execution.image.executor") or "").upper()
        runtime_contract = read_json(root / "runtimes/runtime-contract.json")
        authority_index = read_json(root / "standards/AUTHORITY_INDEX.json")
        runtime_order = [str(x).upper() for x in (runtime_contract.get("routing_order") or [])]
        authority_order = [str(x).upper() for x in (((authority_index.get("rules") or {}).get("runtime_routing") or {}).get("order") or [])]
        contract_default = str((runtime_contract.get("common_rules") or {}).get("default_runtime") or "").upper()
        expected_order = ["WORK", "CODEX", "WEB"]
        if preferred != "WORK":
            errors.append("config runtime.preferred_runtime compatibility alias must remain WORK")
        if production_mode != "COLLABORATIVE":
            errors.append("config production.mode must remain COLLABORATIVE by default")
        if workspace_provider != "webcodex":
            errors.append("config execution.workspace.provider must remain webcodex")
        if image_executor != "CODEX":
            errors.append("config execution.image.executor must remain CODEX")
        if contract_default != preferred:
            errors.append("runtime contract default_runtime drifted from config runtime.preferred_runtime")
        if runtime_order != expected_order:
            errors.append("runtime-contract routing_order must be WORK,CODEX,WEB")
        if authority_order != expected_order:
            errors.append("AUTHORITY_INDEX runtime_routing.order must be WORK,CODEX,WEB")
        runtime_standard = read_text(root / "standards/多运行时执行与断点规范_V2.0.md")
        if "WORK > CODEX > WEB" not in runtime_standard:
            errors.append("active multi-runtime standard must declare WORK > CODEX > WEB")
        if "CODEX > WORK > WEB" in runtime_standard:
            errors.append("active multi-runtime standard still contains CODEX-first routing")
    except Exception as exc:
        errors.append(f"runtime routing consistency check failed: {exc}")

    for rel in [
        Path("standards/创作执行强制规范_V2.0.3.2.md"),
        Path("standards/生产帧语义强制规范_V1.0.md"),
        Path("standards/工作区与增量闭环规范_V1.0.md"),
        Path("standards/最终字幕视觉规范_V1.2.md"),
        Path("standards/导演镜头光影与异常隐藏规范_V1.0.md"),
        Path("standards/directing_grammar_v1.json"),
    ]:
        if not (root / rel).is_file():
            errors.append(f"missing active creative enforcement standard: {rel.as_posix()}")
    authority_text = read_text(root / "standards/AUTHORITY_INDEX.json")
    for token in ["standards/创作执行强制规范_V2.0.3.2.md", "standards/生产帧语义强制规范_V1.0.md", "standards/工作区与增量闭环规范_V1.0.md", "standards/最终字幕视觉规范_V1.2.md", "standards/导演镜头光影与异常隐藏规范_V1.0.md"]:
        if token not in authority_text:
            errors.append(f"AUTHORITY_INDEX missing active creative enforcement route: {token}")

    requirements = root / "episodes/_system/requirements.txt"
    if not requirements.is_file() or "Pillow" not in read_text(requirements):
        errors.append("canonical runtime dependencies missing Pillow: episodes/_system/requirements.txt")
    adapter_requirements = root / "skills/dali-cat-story/requirements.txt"
    if adapter_requirements.exists():
        errors.append("thin adapter must not own runtime requirements; use episodes/_system/requirements.txt")

    gitattributes = root / ".gitattributes"
    if not gitattributes.is_file():
        errors.append("repository EOL policy missing: .gitattributes")
    else:
        attrs = read_text(gitattributes)
        for token in ["* text=auto eol=lf", "*.cmd text eol=crlf", "*.bat text eol=crlf"]:
            if token not in attrs:
                errors.append(f".gitattributes missing EOL token: {token}")

    engine = root / "episodes" / "_system"
    for name in CORE_ENGINE_FILES:
        if not (engine / name).is_file():
            errors.append(f"missing canonical engine file: episodes/_system/{name}")

    source_expectations = {
        "episode_state.py": [
            "from story_os_contract import canonical_stages, story_os_version",
            "STATES = canonical_stages()",
            "SYSTEM_VERSION = story_os_version()",
        ],
        "story_os.py": [
            "from story_os_contract import canonical_stages, story_os_version",
            "STATES = canonical_stages()",
            "story_os_version()",
        ],
        "runtime_router.py": [
            "from story_os_contract import story_os_version",
            "'story_os_version': story_os_version()",
        ],
        "machine_gate.py": [
            "from story_os_contract import canonical_stages",
            "STATES = canonical_stages()",
        ],
        "evidence_gate.py": [
            "from story_os_contract import canonical_stages",
            "STATES=canonical_stages()",
        ],
        "release_package.py": [
            "from story_os_contract import story_os_version",
            "STORY_OS_VERSION = story_os_version()",
        ],
        "delegated_approval.py": [
            "from story_os_contract import story_os_version",
            "STORY_OS_VERSION = story_os_version()",
        ],
        "visual_profile_bridge_v224.py": [
            "def compile_prompt_contract",
            "profile_sha256",
        ],
        "codex_subscription_image.py": [
            "from visual_profile_bridge_v224 import compile_prompt_contract",
            "<visual_contract>",
        ],
        "approval_lock.py": [
            "verify_story_review",
            "verify_visual_review",
        ],
        "evidence_gate.py": [
            "from story_os_contract import canonical_stages",
            "STATES=canonical_stages()",
            "verify_story_review",
            "verify_visual_review",
            "verify_layout_audit",
        ],
        "story_review.py": [
            "runtime_provenance.validate_critic_provenance",
            "product_review_adapter",
            "MECHANISM_CONTRADICTION",
        ],
        "visual_review.py": [
            "FOUR_ADMISSION_V21_POLICY",
            "visual_lock_v21",
        ],
        "frame_semantic_review.py": [
            "runtime_provenance.validate_critic_provenance",
            "product_review_adapter",
            "asset_sha256",
            "scene_storyboard_fidelity",
            "actual_information_gain",
        ],
        "delegated_delivery.py": [
            "from story_os_contract import story_os_version",
            "verify_frame_semantic_episode",
        ],
        "subtitle_layout.py": [
            "drop_entire_second_line",
            "PUNCTUATION_ONLY_SECOND_LINE",
            "LEFT_MIDDLE_MIN_RATIO",
            "safe_zone_override_reason",
        ],
        "shot_progression_gate.py": [
            "schema_version\":3",
            "scene_position_id",
            "cinematic_reference",
            "lighting_design",
            "anomaly_concealment",
        ],
        "codex_auto_orchestrator.py": [
            "from story_os_contract import canonical_stages, story_os_version",
            "STORY_OS_VERSION=story_os_version()",
            "STATES=canonical_stages()",
            "'story_os_version':STORY_OS_VERSION",
        ],
        "visual_review_legacy.py": [
            "runtime_provenance.validate_critic_provenance",
            "product_review_adapter",
            "WORK",
            "WEB",
        ],
        "product_runtime_adapter.py": [
            "REQUEST_HISTORY_REL",
            "request_fingerprint",
            "local_codex_spawn_allowed",
        ],
        "product_review_adapter.py": [
            "attempt_request_path",
            "request_fingerprint",
            "WORK_ISOLATED",
        ],
        "runtime_checkpoint.py": [
            "HOST_WAIT",
        ],
        "workflow_observability.py": [
            "awaiting_product_host",
            "HOST_WAIT",
        ],
        "runtime_log_policy.py": [
            "local_derived_not_git_authority",
            "tracked_historical_count",
        ],
    }
    source_expectations.update({
        "incremental_closure.py": [
            "incremental_frame_review.py",
            "POSTFLIGHT_ONLY",
            "PRODUCTION_INCREMENTAL_REQUIRED",
        ],
        "incremental_frame_review.py": [
            "action = \"FULL\" if context_change or first_review else \"PATCH\"",
            "INCREMENTAL_CONTEXT_SET",
            "caption_state",
        ],
        "media_workspace.py": [
            "meta/media-index.json",
            "evidence_frozen",
            ".story-os-media-migration",
        ],
    })
    for name, tokens in source_expectations.items():
        p = engine / name
        if not p.is_file():
            continue
        text = read_text(p)
        for token in tokens:
            if token not in text:
                errors.append(f"episodes/_system/{name} missing contract token: {token}")

    orchestrator = engine / "codex_auto_orchestrator.py"
    if orchestrator.is_file() and "2.0.2" in read_text(orchestrator):
        errors.append("codex_auto_orchestrator.py contains stale Story OS V2.0.2 literals")

    delegated = engine / "delegated_approval.py"
    if delegated.is_file() and ("'2.0.2'" in read_text(delegated) or '"2.0.2"' in read_text(delegated)):
        errors.append("delegated_approval.py contains stale Story OS V2.0.2 literals")

    delivery = engine / "delegated_delivery.py"
    if delivery.is_file() and ("'story_os_version':'2.0.2'" in read_text(delivery) or '"story_os_version": "2.0.2"' in read_text(delivery)):
        errors.append("delegated_delivery.py contains stale Story OS V2.0.2 literals")

    skill_scripts = root / "skills" / "dali-cat-story" / "scripts"
    for name in CORE_ENGINE_FILES:
        duplicate = skill_scripts / name
        if duplicate.exists():
            errors.append(
                f"duplicate engine implementation forbidden in Skill: {duplicate.relative_to(root).as_posix()}"
            )

    adapter_texts = []
    for rel in ADAPTER_SKILLS:
        p = root / rel
        if not p.is_file():
            continue
        text = read_text(p)
        adapter_texts.append((rel, text))
        for token in ["episodes/_system", "episode-state.json", *sorted(REQUIRED_CAPABILITIES)]:
            if token not in text:
                errors.append(f"{rel.as_posix()} missing adapter contract token: {token}")
        if "Skill is an adapter, not a Story OS copy" not in text:
            errors.append(f"{rel.as_posix()} missing thin-adapter invariant")
    if len({text for _, text in adapter_texts}) > 1:
        errors.append("dali-cat-story adapter contracts are not byte-equivalent")

    bootstrap = skill_scripts / "bootstrap_episode.py"
    if not bootstrap.is_file():
        errors.append("missing Skill wrapper: skills/dali-cat-story/scripts/bootstrap_episode.py")
    else:
        text = read_text(bootstrap)
        for token in ["episodes", "_system", "episode_state.py", '"init"']:
            if token not in text:
                errors.append(f"bootstrap_episode.py no longer delegates canonical init ({token})")
        if "V2.0.3 adapter" in text:
            errors.append("bootstrap_episode.py still hardcodes a product version")

    validate_all = skill_scripts / "validate_all.py"
    if not validate_all.is_file():
        errors.append("missing Skill wrapper: skills/dali-cat-story/scripts/validate_all.py")
    else:
        text = read_text(validate_all)
        for token in ["episodes", "_system", "validate_episode.py"]:
            if token not in text:
                errors.append(f"validate_all.py no longer delegates canonical validator ({token})")
        if "V1.1" in text:
            errors.append("validate_all.py still carries stale V1.1 adapter wording")

    scripts_readme = skill_scripts / "README.md"
    if not scripts_readme.is_file():
        errors.append("missing skills/dali-cat-story/scripts/README.md")
    else:
        text = read_text(scripts_readme)
        code_refs = set(re.findall(r"`([^`\n]+\.py)`", text))
        for ref in sorted(code_refs):
            if ref.startswith("episodes/_system/"):
                target = root / ref
            elif "/" in ref or "\\" in ref:
                target = root / Path(ref.replace("\\", "/"))
            else:
                target = skill_scripts / ref
            if not target.is_file():
                errors.append(f"adapter scripts README references missing file: {ref}")

    template_path = root / "standards/templates/story-gates.template.json"
    if not template_path.is_file():
        errors.append("missing standards/templates/story-gates.template.json")
    else:
        try:
            template = read_json(template_path)
            if template.get("tool_version") != version:
                errors.append("story-gates template tool_version drifted from manifest")
            template_profile = str((template.get("visual_profile") or {}).get("profile_path") or "")
            try:
                cfg_profile = str(storyos_config.get_path(storyos_config.load_config(), "visual.default_profile_path") or "")
            except Exception:
                cfg_profile = ""
            if template_profile != cfg_profile:
                errors.append("story-gates template visual_profile.profile_path drifted from config default")
            if "�" in template_profile or not (root / template_profile).is_file():
                errors.append("story-gates template visual profile path is corrupted or missing")
            if (template.get("machine_contract") or {}).get("strict") is not True:
                errors.append("story-gates template must represent current strict machine contract")
            visual = template.get("visual") or {}
            for key in ["authenticity_card", "calibration", "calibration_contact_sheet", "references"]:
                if key not in visual:
                    errors.append(f"story-gates template missing visual.{key}")
            if "production_evidence" not in template:
                errors.append("story-gates template missing production_evidence")
            if any(k in template for k in ("current_state", "stage", "workflow_state")):
                errors.append("story-gates template must never become a second stage source")
        except Exception as exc:
            errors.append(f"invalid story-gates template: {exc}")

    workflow = root / ".github/workflows/story-gates.yml"
    if not workflow.is_file():
        errors.append("missing .github/workflows/story-gates.yml")
    else:
        wf = read_text(workflow)
        for token in [
            "actions/checkout@v7",
            "actions/setup-python@v7",
            "python -m pip install -r episodes/_system/requirements.txt",
            "python episodes/_system/contract_sync.py",
            "python episodes/_system/test_v203_contract_hardening.py -v",
            "python episodes/_system/test_v2032_creative_enforcement.py -v",
            "python episodes/_system/story_review.py self-test",
            "python episodes/_system/visual_review.py self-test",
            "python episodes/_system/subtitle_layout.py self-test",
            "python episodes/_system/incremental_closure.py self-test",
            "python episodes/_system/incremental_frame_review.py self-test",
            "python episodes/_system/media_workspace.py self-test",
            "python episodes/_system/story_os.py doctor",
        ]:
            ci_adapter_token = token.replace("python episodes/_system/", "python scripts/ci_storyos_python.py episodes/_system/", 1)
            if token not in wf and ci_adapter_token not in wf:
                errors.append(f"CI missing Story OS hardening check: {token}")
        for token in ['"story_os_manifest.json"', '"runtimes/**"', '"START_HERE.md"', '"README.md"']:
            if wf.count(token) < 2:
                errors.append(f"CI must trigger on {token} for pull_request and story push")

    for runtime_doc in ["runtimes/CODEX.md", "runtimes/WORK.md", "runtimes/WEB.md"]:
        p = root / runtime_doc
        if not p.is_file():
            errors.append(f"missing {runtime_doc}")
            continue
        text = read_text(p)
        if "story_os_manifest.json" not in text:
            errors.append(f"{runtime_doc} must derive current product version from story_os_manifest.json")
        if re.match(r"^# .* Runtime V\\d", text):
            errors.append(f"{runtime_doc} should be product-version-neutral")

    root_readme = root / "README.md"
    if root_readme.is_file():
        text = read_text(root_readme)
        if "新篇执行流程唯一入口" not in text or "START_HERE.md" not in text:
            errors.append("README.md must delegate the new-episode execution flow to START_HERE.md")
        if "风格锚点_流水席_村子_误入小镇_V1.1.md" in text:
            errors.append("README.md still links the superseded V1.1 mother-style file")

    upgrade = root / "README_UPGRADE.md"
    if upgrade.is_file():
        text = read_text(upgrade)
        if "HISTORICAL_ONLY" not in text or "START_HERE.md" not in text:
            errors.append("README_UPGRADE.md is an unversioned stale active upgrade entrypoint")

    installer = root / "INSTALL_WINDOWS.ps1"
    if installer.is_file() and "DEPRECATED_STORY_OS_INSTALLER" not in read_text(installer):
        errors.append("INSTALL_WINDOWS.ps1 is a stale executable installer and must be retired")

    # Security/portability closure: no canonical shim may hard-code a local user path
    # or silently grant danger-full-access. Historical wrappers must be inert.
    fullaccess = engine / "codex_win_fullaccess.py"
    if fullaccess.is_file():
        text = read_text(fullaccess)
        if "C:\\Users\\" in text or "79873" in text:
            errors.append("codex_win_fullaccess.py contains a user-specific executable path")
        for token in ["STORY_OS_RUNTIME", "STORY_OS_ALLOW_CODEX_FULL_ACCESS", "CODEX_EXE"]:
            if token not in text:
                errors.append(f"codex_win_fullaccess.py missing explicit opt-in token: {token}")
    retired_root = root / "_tmp_codex_shim_0153.py"
    if retired_root.is_file() and "RETIRED_CODEX_SHIM" not in read_text(retired_root):
        errors.append("tracked root Codex temp shim must be retired/inert")
    retired_episode = root / "episodes/10_山难伪纪录片/01_鳌太线_热汤/meta/codex_danger_wrapper.py"
    if retired_episode.is_file() and "RETIRED_CODEX_DANGER_WRAPPER" not in read_text(retired_episode):
        errors.append("episode-local Codex danger wrapper must be retired/inert")

    gitignore = read_text(root / ".gitignore") if (root / ".gitignore").is_file() else ""
    for token in [
        "_tmp_*",
        "episodes/**/meta/image-workers/",
        "episodes/**/meta/rolling-review-workers/",
        "episodes/**/meta/scoped-workers/",
        # Named meta JSONL runtime logs are covered by this meta-wide wildcard.
        "episodes/**/meta/**/*.jsonl",
    ]:
        if token not in gitignore:
            errors.append(f".gitignore missing runtime-log hygiene token: {token}")

    tracked = tracked_local_artifacts(root)
    if tracked:
        errors.append("local installer receipts/backups are tracked by git: " + ", ".join(tracked[:10]))

    errors.extend(untracked_series_masters(root))

    return errors


def main(argv: Iterable[str] | None = None) -> int:
    errors = collect_errors()
    if errors:
        print("[FAIL] Story OS contract sync")
        for error in errors:
            print(f"  - {error}")
        return 1
    version = load_contract(repo_root()).get("platform_version")
    print(f"[PASS] Story OS V{version} contract sync")
    print("       one product version -> one canonical engine -> thin adapters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
