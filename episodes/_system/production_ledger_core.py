#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from canvas_spec import DEFAULT_ASPECT_RATIO, resolve_canvas_spec
from visual_profile import compile_prompt_contract
import frame_contract as resolved_frame_contract
import storyos_config
import model_policy
import episode_lifecycle
import episode_state_persistence
import production_ledger_persistence
from runtime_atomic_store import atomic_write_json
import user_visual_reference_contract

LEDGER_FILE = Path("meta/production-ledger.json")
MANIFEST_FILE = Path("meta/release-manifest.json")
ENGINE_VERSION = "1.2"
PROMPT_CHAR_LIMIT = 260
PROMPT_BYTE_LIMIT = 900
_CONFIG = storyos_config.load_config()
DEFAULT_IMAGE_QUALITY = str(model_policy.resolve("image.payload")["quality"])
FRAME_STATES = {
    "PENDING",
    "GENERATING",
    "TECH_FAILED",
    "ORIGINAL_READY",
    "CONTENT_FAILED",
    "REPAIR_AUTHORIZED",
    "AUTHORITY_REFRESH_AUTHORIZED",
    "EXCEPTION_REPAIR_AUTHORIZED",
    "USER_CONTINUATION_REPAIR_AUTHORIZED",
    "REPAIRING",
    "REPAIR_READY",
    "PASSED",
    "WEAK_PASS",
    "NEEDS_USER",
    "LOCKED",
}
REFERENCE_KINDS = {"identity", "prop", "location", "capture_style"}
# Canonical derived subsets of FRAME_STATES. Consumers import these instead of
# re-typing the member sets so scheduler/recovery/gate vocabulary cannot drift.
READY_LEDGER_STATES = frozenset({"ORIGINAL_READY", "REPAIR_READY", "PASSED", "WEAK_PASS", "LOCKED"})
ACTIVE_LEDGER_STATES = frozenset({"GENERATING", "REPAIRING"})
ACCEPTED_LEDGER_STATES = frozenset({"PASSED", "WEAK_PASS", "LOCKED"})


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"JSON root must be object: {path}")
    return data


def save_json(path: Path, data: dict) -> None:
    path = Path(path).resolve()
    if path.name == LEDGER_FILE.name and path.parent.name == "meta":
        ep = path.parent.parent
        episode_lifecycle.assert_writable(ep, "production_ledger.write")
        current_mode = production_ledger_persistence.mode()
        if current_mode in {"dual", "mysql"}:
            # MySQL is written first. In mysql-only mode the Episode JSON is
            # not written at all; in dual it remains a compatibility replica.
            production_ledger_persistence.persist_authority(ep, data)
        if current_mode != "mysql":
            atomic_write_json(path, data)
        return
    atomic_write_json(path, data)



def load_authority(ep: Path, default=None):
    """Read the complete Production Ledger from its configured authority.

    mysql is strict DB authority with no stale-file fallback. dual prefers
    MySQL and may fall back to the compatibility file during migration.
    """
    ep = Path(ep).resolve()
    current_mode = production_ledger_persistence.mode()
    if current_mode in {"dual", "mysql"}:
        try:
            data = production_ledger_persistence.load_authority(ep)
            if isinstance(data, dict):
                return data
        except Exception:
            if current_mode == "mysql":
                raise
        if current_mode == "mysql":
            return default
    path = ep / LEDGER_FILE
    if not path.is_file():
        return default
    return load_json(path)


def authority_exists(ep: Path) -> bool:
    return isinstance(load_authority(ep, default=None), dict)


def authority_sha256(ep: Path) -> str | None:
    data = load_authority(ep, default=None)
    if not isinstance(data, dict):
        return None
    raw = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def materialize_export(ep: Path) -> Path | None:
    """Materialize a delivery/export view without restoring file authority."""
    ep = Path(ep).resolve()
    compatibility = ep / LEDGER_FILE
    if production_ledger_persistence.mode() != "mysql" and compatibility.is_file():
        return compatibility
    data = load_authority(ep, default=None)
    if not isinstance(data, dict):
        return None
    import runtime_workspace
    target = runtime_workspace.workspace_path(
        ep, Path("exports/production-ledger.json")
    )
    atomic_write_json(target, data)
    return target


def episode_dir(raw: str) -> Path:
    p = Path(raw).resolve()
    if not p.is_dir():
        raise SystemExit(f"episode directory not found: {p}")
    return p


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def image_dimensions(path: Path) -> tuple[int, int] | None:
    ext = path.suffix.lower()
    try:
        if ext == ".png":
            head = path.read_bytes()[:24]
            if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
                return struct.unpack(">II", head[16:24])
            return None
        if ext in {".jpg", ".jpeg"}:
            with path.open("rb") as f:
                if f.read(2) != b"\xff\xd8":
                    return None
                while True:
                    b = f.read(1)
                    if not b:
                        return None
                    if b != b"\xff":
                        continue
                    marker = f.read(1)
                    while marker == b"\xff":
                        marker = f.read(1)
                    if not marker:
                        return None
                    code = marker[0]
                    if code in {0xD8, 0xD9}:
                        continue
                    raw_len = f.read(2)
                    if len(raw_len) != 2:
                        return None
                    length = struct.unpack(">H", raw_len)[0]
                    if length < 2:
                        return None
                    if code in {0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF}:
                        payload = f.read(length - 2)
                        if len(payload) < 5:
                            return None
                        height, width = struct.unpack(">HH", payload[1:5])
                        return width, height
                    f.seek(length - 2, 1)
    except OSError:
        return None
    return None


def read_manifest(ep: Path) -> dict | None:
    p = ep / MANIFEST_FILE
    return load_json(p) if p.exists() else None


def resolve_episode_canvas(ep: Path, override: str | None = None):
    manifest = read_manifest(ep)
    manifest_ratio = ((manifest.get("episode") or {}).get("aspect_ratio")) if manifest else None
    if override:
        override_spec = resolve_canvas_spec(override)
        if manifest_ratio and resolve_canvas_spec(manifest_ratio).aspect_ratio != override_spec.aspect_ratio:
            raise SystemExit(f"aspect-ratio override {override_spec.aspect_ratio} conflicts with Episode manifest lock {manifest_ratio}")
        return override_spec, "override"
    if manifest_ratio:
        return resolve_canvas_spec(manifest_ratio), "manifest"
    return resolve_canvas_spec(DEFAULT_ASPECT_RATIO), "default"


def frame_count(ep: Path, explicit: int | None = None) -> int:
    if explicit is not None:
        if explicit <= 0:
            raise SystemExit("frame count must be > 0")
        return explicit
    manifest = read_manifest(ep)
    if manifest:
        value = ((manifest.get("release") or {}).get("body_frame_count"))
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return 20


def blank_frame(number: int) -> dict:
    return {
        "number": number,
        "status": "PENDING",
        "content_repairs_used": 0,
        "technical_failures": [],
        "attempts": [],
        "current_candidate": None,
        "approved_asset": None,
        "lock": None,
        "reviews": [],
    }


def init_ledger(ep: Path, *, count: int | None = None, ratio: str | None = None, overwrite: bool = False) -> dict:
    production_ledger_persistence.assert_full_authority_available()
    path = ep / LEDGER_FILE
    if path.exists() and not overwrite:
        return load_json(path)
    spec, source = resolve_episode_canvas(ep, ratio)
    total = frame_count(ep, count)
    data = {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "note": "Per-frame production transaction ledger. This is NOT an episode stage source.",
        "canvas": {
            "aspect_ratio": spec.aspect_ratio,
            "width": spec.width,
            "height": spec.height,
            "source": source,
        },
        "policy": {
            "default_aspect_ratio": DEFAULT_ASPECT_RATIO,
            "prompt_char_limit": PROMPT_CHAR_LIMIT,
            "prompt_byte_limit": PROMPT_BYTE_LIMIT,
            "max_content_repairs_per_frame": int(storyos_config.get_path(_CONFIG, "production.max_content_repairs_per_frame")),
            "technical_failures_consume_content_repair": False,
            "image_quality": DEFAULT_IMAGE_QUALITY,
            "normalize_enabled": True,
            "preserve_raw": True,
            "final_format": "PNG",
            "resize_algorithm": "Lanczos",
            "default_crop": "forbidden",
            "imageops_fit": "exception_only",
            "automatic_ratio_delta_max": float(storyos_config.get_path(_CONFIG, "normalize.automatic_ratio_delta_max")),
            "review_ratio_delta_max": float(storyos_config.get_path(_CONFIG, "normalize.review_ratio_delta_max")),
            "reject_ratio_delta_above": float(storyos_config.get_path(_CONFIG, "normalize.review_ratio_delta_max")),
            "noop_when_exact_match": True,
            "technical_failure_triggers_generation": False,
        },
        "asset_roots": {
            "raw": "media/raw",
            "originals": "media/candidates/originals",
            "repairs": "media/candidates/repairs",
            "approved": "media/approved",
            "publish": "media/publish",
            "contact_sheets": "media/review/contact-sheets",
        },
        "frames": {f"{i:02d}": blank_frame(i) for i in range(1, total + 1)},
        "batches": [],
    }
    for rel in data["asset_roots"].values():
        (ep / rel).mkdir(parents=True, exist_ok=True)
    save_json(path, data)
    return data


def get_ledger(ep: Path) -> tuple[Path, dict]:
    production_ledger_persistence.assert_full_authority_available()
    path = ep / LEDGER_FILE
    # Always read through the configured authority facade. In mysql mode the
    # compatibility JSON may be stale (or intentionally absent) and must never
    # become the source for a subsequent command in the same ledger lifecycle.
    # In particular, begin persists its pending attempt to MySQL only; success
    # must read that same authority or it will lose the generation attempt.
    data = load_authority(ep, default=None)
    if not isinstance(data, dict):
        data = init_ledger(ep)
    return path, data


def frame_obj(data: dict, raw: str) -> tuple[str, dict]:
    try:
        n = int(raw)
    except ValueError:
        raise SystemExit(f"invalid frame: {raw}")
    key = f"{n:02d}"
    frames = data.get("frames")
    if not isinstance(frames, dict) or key not in frames:
        raise SystemExit(f"frame {key} not registered")
    frame = frames[key]
    if frame.get("status") not in FRAME_STATES:
        raise SystemExit(f"frame {key} has invalid status: {frame.get('status')!r}")
    return key, frame


def prompt_text(args: argparse.Namespace) -> str:
    if bool(args.prompt) == bool(args.prompt_file):
        raise SystemExit("provide exactly one of --prompt or --prompt-file")
    if args.prompt:
        text = args.prompt
    else:
        p = Path(args.prompt_file)
        if not p.is_file():
            raise SystemExit(f"prompt file not found: {p}")
        text = p.read_text(encoding="utf-8")
    text = text.strip()
    if not text:
        raise SystemExit("prompt cannot be empty")
    chars, nbytes = len(text), len(text.encode("utf-8"))
    if not args.allow_long_prompt and (chars > PROMPT_CHAR_LIMIT or nbytes > PROMPT_BYTE_LIMIT):
        raise SystemExit(
            f"prompt budget exceeded: {chars} chars/{nbytes} bytes; "
            f"limit={PROMPT_CHAR_LIMIT} chars/{PROMPT_BYTE_LIMIT} bytes. "
            "Shorten the per-frame prompt or use --allow-long-prompt with an explicit reason in notes."
        )
    return text


def parse_references(values: list[str] | None) -> list[dict]:
    out = []
    for value in values or []:
        parts = value.split("::")
        # W-21: an optional 4th field carries the declared anchor/id (for example
        # protagonist_identity) so reference execution evidence stays attributable.
        if len(parts) not in {3, 4}:
            raise SystemExit("--reference format must be PATH::ROLE::KIND[::ANCHOR]")
        raw_path, role, kind = (x.strip() for x in parts[:3])
        anchor = parts[3].strip() if len(parts) == 4 else ""
        if kind not in REFERENCE_KINDS:
            raise SystemExit(f"invalid reference kind {kind!r}; choose {sorted(REFERENCE_KINDS)}")
        p = Path(raw_path).resolve()
        if not p.is_file():
            raise SystemExit(f"reference file not found: {p}")
        row = {
            "path": repo_relative(p),
            "role": role,
            "kind": kind,
            "sha256": sha256_file(p),
        }
        if anchor:
            row["id"] = anchor
        out.append(row)
    if len(out) > 2:
        raise SystemExit("formal request supports at most 2 references by default; reduce references or split continuity anchors")
    return out


def _version_tuple(raw: object) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(raw or "").split("."))
    except ValueError:
        return (0,)


def creative_enforcement_required(ep: Path) -> bool:
    try:
        state = episode_state_persistence.load(ep) or {}
        if _version_tuple(state.get("tool_version")) >= (2, 0, 3, 2):
            return True
    except Exception:
        pass
    p = ep / "meta/release-manifest.json"
    if p.is_file():
        try:
            if _version_tuple(load_json(p).get("tool_version")) >= (2, 0, 3, 2):
                return True
        except Exception:
            pass
    return False


def approved_capture_style_source(ep: Path, ref_path: str) -> str | None:
    # A direct user upload cannot be marked as a passed generated calibration
    # frame. It has its own exact SHA, original-upload provenance and safe path.
    if user_visual_reference_contract.approved_user_capture_style(ep, ref_path):
        return "explicit_user_upload_capture_style"
    gates_path = ep / "meta/story-gates.json"
    if not gates_path.is_file():
        return None
    gates = load_json(gates_path)
    visual = gates.get("visual") or {}
    calibration = visual.get("calibration") or {}
    passed_paths = set()
    if isinstance(calibration.get("items"), list):
        for item in calibration["items"]:
            if isinstance(item, dict) and item.get("decision") in {"passed", "pass"}:
                raw = item.get("path") or item.get("asset_path")
                if raw:
                    try:
                        passed_paths.add(repo_relative(Path(raw).resolve() if Path(raw).is_absolute() else repo_root() / raw))
                    except Exception:
                        pass
    else:
        for key in ("baseline", "worst_condition", "first_major_anomaly"):
            item = calibration.get(key) or {}
            if item.get("decision") in {"passed", "pass"}:
                raw = item.get("asset_path") or item.get("path")
                if raw:
                    try:
                        passed_paths.add(repo_relative(Path(raw).resolve() if Path(raw).is_absolute() else repo_root() / raw))
                    except Exception:
                        pass
    if ref_path in passed_paths:
        return "approved_calibration"

    for item in ((visual.get("references") or {}).get("items") or []):
        if not isinstance(item, dict) or item.get("decision") not in {"passed", "pass"}:
            continue
        raw = item.get("path")
        kind = item.get("reference_kind") or item.get("kind")
        if not raw or kind != "capture_style":
            continue
        p = Path(raw)
        rel = repo_relative(p.resolve() if p.is_absolute() else repo_root() / p)
        if rel == ref_path:
            return "approved_reference"
    return None


def enforce_capture_style_provenance(ep: Path, refs: list[dict]) -> None:
    if not creative_enforcement_required(ep):
        return
    for ref in refs:
        if ref.get("kind") != "capture_style":
            continue
        source = approved_capture_style_source(ep, str(ref.get("path") or ""))
        if source is None:
            raise SystemExit(
                "capture_style reference must be an approved calibration frame or an explicitly "
                "passed capture_style reference; unapproved generated frames cannot recursively define style"
            )
        ref["source_kind"] = source


def current_visual_provenance(ep: Path) -> dict:
    contract = compile_prompt_contract(ep)
    return {
        "profile_id": contract["profile_id"],
        "profile_path": contract["profile_path"],
        "profile_sha256": contract["profile_sha256"],
        "capture_profile": contract["capture_profile"],
    }


def current_frame_contract_provenance(ep: Path, frame: str) -> dict | None:
    return resolved_frame_contract.provenance(ep, frame)


def verify_attempt_frame_contract_provenance(ep: Path, frame: str, attempt: dict) -> None:
    if not resolved_frame_contract.required(ep):
        return
    request = attempt.get("request") or {}
    errors = resolved_frame_contract.verify_recorded_provenance(ep, frame, request.get("frame_contract"))
    if errors:
        raise SystemExit("; ".join(errors))


def verify_attempt_visual_provenance(ep: Path, attempt: dict) -> None:
    request = attempt.get("request") or {}
    recorded = request.get("visual_profile")
    if not isinstance(recorded, dict):
        if creative_enforcement_required(ep):
            raise SystemExit("generation attempt missing visual profile provenance")
        return
    current = current_visual_provenance(ep)
    for key in ("profile_id", "profile_path", "profile_sha256", "capture_profile"):
        if str(recorded.get(key)) != str(current.get(key)):
            raise SystemExit(f"visual profile drift before candidate acceptance: {key}")

def request_fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def active_attempt(frame: dict) -> dict:
    attempts = frame.get("attempts") or []
    if not attempts:
        raise SystemExit("frame has no generation attempt")
    attempt = attempts[-1]
    if attempt.get("result") not in {None, "pending"}:
        raise SystemExit("latest attempt is already closed")
    return attempt



def content_repair_limit(data:dict)->int:
    # Existing ledgers freeze their policy; legacy ledgers keep the original limit.
    value=(data.get("policy") or {}).get("max_content_repairs_per_frame",1)
    if type(value) is not int or value not in {0,1}:
        raise ValueError("max_content_repairs_per_frame must be 0 or 1 under the production standard")
    return value


def safe_ext(path: Path) -> str:
    ext = path.suffix.lower()
    return ext if ext in {".png", ".jpg", ".jpeg"} else ".png"


def parse_frame_set(raw: list[str]) -> list[str]:
    out: list[str] = []
    for item in raw:
        for part in item.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                start, end = int(a), int(b)
                if end < start:
                    raise SystemExit(f"invalid frame range {part}")
                out.extend(f"{i:02d}" for i in range(start, end + 1))
            else:
                out.append(f"{int(part):02d}")
    return list(dict.fromkeys(out))
