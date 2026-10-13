#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json
from pathlib import Path
import visual_profile as base
import capture_grammar_v228

ROOT = base.ROOT
META_REL = Path("meta/visual-profile.json")

def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise SystemExit(f"JSON root must be object: {path}")
    return data

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()

def episode_meta(ep: Path):
    p = ep / META_REL
    if not p.is_file():
        alt = ep / "meta" / "visual_profile.json"
        p = alt if alt.is_file() else p
    if not p.is_file():
        return None
    data = load(p)
    profile_id = str(data.get("profile_id") or "").strip()
    if not profile_id:
        raise SystemExit("EPISODE_VISUAL_PROFILE_INVALID: profile_id missing")
    rel = Path(str(data.get("profile_path") or "").strip()) if data.get("profile_path") else Path("standards/visual_profiles") / f"{profile_id}.json"
    canonical = (ROOT / rel).resolve()
    try:
        canonical.relative_to(ROOT.resolve())
    except ValueError:
        raise SystemExit("EPISODE_VISUAL_PROFILE_INVALID: path escapes repository")
    if not canonical.is_file():
        raise SystemExit(f"EPISODE_VISUAL_PROFILE_MISSING: {rel.as_posix()}")
    cdata = load(canonical)
    cid = str(cdata.get("profile_id") or "").strip()
    if cid and cid != profile_id:
        raise SystemExit(f"VISUAL_PROFILE_ID_MISMATCH: episode={profile_id} canonical={cid}")
    return {
        "selection": "episode_meta",
        "profile_id": profile_id,
        "profile_name": cdata.get("profile_name") or data.get("profile_name"),
        "profile_path": rel.as_posix(),
        "capture_profile": str((data.get("capture") or {}).get("device") or data.get("capture_profile") or "auto"),
        "override_reason": str(data.get("override_reason") or "episode meta visual profile lock"),
        "authority_source": p.relative_to(ep).as_posix(),
        "rule": "Episode explicit Visual Profile is authoritative for visual texture; global Capture Grammar owns camera authorship/framing unless explicitly overridden.",
    }

def resolve_profile(ep: Path) -> dict:
    meta = episode_meta(ep)
    resolved = base.resolve_base_profile(ep)
    if not meta:
        resolved["authority_source"] = resolved.get("authority_source") or "story-gates/default"
        return resolved
    if resolved.get("selection") == "override" and resolved.get("profile_id") != meta["profile_id"]:
        raise SystemExit(
            "VISUAL_PROFILE_AUTHORITY_MISMATCH: "
            f"episode_meta={meta['profile_id']} story_gates={resolved.get('profile_id')}"
        )
    if resolved.get("selection") == "override" and resolved.get("profile_id") == meta["profile_id"]:
        merged = dict(resolved)
        merged["selection"] = "episode_meta+story_gates"
        merged["authority_source"] = f"{meta['authority_source']} + meta/story-gates.json"
        return merged
    return meta

def _fmt(v):
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, list): return "; ".join(map(str, v))
    if isinstance(v, dict): return "; ".join(f"{k}={v}" for k,v in v.items())
    return str(v)

def compile_prompt_contract(ep: Path) -> dict:
    profile = resolve_profile(ep)
    p = (ROOT / profile["profile_path"]).resolve()
    data = load(p)
    dna = data.get("visual_dna") or {}

    # Visual Profile is the texture/era layer. Capture Grammar is the camera-behavior layer.
    lines = [
        f"profile={profile['profile_id']} | {profile.get('profile_name') or ''}",
        f"authority={profile.get('authority_source') or profile.get('selection')}",
        f"principle={data.get('principle') or profile.get('rule') or ''}",
    ]
    for k in [
        "reality_first","film_medium","color","texture","lighting","skin","sets",
        "era","wardrobe","people","ordinary_chinese_life_density",
        "subject_awareness","practical_available_light","available_light_only",
        "cinematic_lighting","commercial_hdr","portrait_bokeh","camera_perfection",
        "hero_shot","symmetrical_composition","beautification","skin_rendering",
        "global_vintage_lut","cinematic_color_grading","white_balance","contrast",
        "dynamic_range","noise","motion_blur","lens_artifacts","scene_cleaning",
        "life_clutter","environment_imperfection","visual_polish_ceiling","anomaly",
        "anomaly_environment_binding","spectacle_first","scale_reference",
        "screen_ui_physics","camera_authorship","ghost_camera","capture_reason",
        "save_reason","narrative_information_gain","narrative_redundancy",
        "continuity","reference_assets","seed_dependency"
    ]:
        if k in dna:
            lines.append(f"{k}={_fmt(dna[k])}")

    if "composition" in dna:
        key = "composition" if profile.get("profile_id") == "M00" else "visual_profile_composition_hint_NON_AUTHORITY"
        lines.append(f"{key}={_fmt(dna['composition'])}")

    # Keep photography only as medium/style context; it cannot control camera authorship or staging.
    if "photography" in dna:
        lines.append(f"visual_medium_photography={_fmt(dna['photography'])}")
    if data.get("must_keep"):
        lines.append("must_keep=" + _fmt(data["must_keep"]))
    if data.get("forbidden"):
        lines.append("forbidden=" + _fmt(data["forbidden"]))

    # Compile M00's existing genre neutrality; do not mutate its frozen SHA.
    neutrality = data.get("anti_homogeneity") or {}
    if profile.get("profile_id") == "M00" and neutrality.get("lock_texture_not_scene") is True:
        lines.append("lock_texture_not_scene=true")
        if neutrality.get("rule"):
            lines.append("anti_homogeneity_rule=" + str(neutrality["rule"]))

    capture = capture_grammar_v228.compile_capture_contract(ep)
    lines += [
        "----- GLOBAL CAPTURE GRAMMAR -----",
        capture["text"],
        "----- END GLOBAL CAPTURE GRAMMAR -----",
        "capture physics and story era override decorative texture",
        "do not silently substitute another visual profile or capture grammar",
    ]
    return {
        **profile,
        "profile_sha256": sha256_file(p),
        "capture_grammar": {
            "grammar_id": capture["grammar_id"],
            "grammar_path": capture["grammar_path"],
            "selection": capture["selection"],
            "authority_source": capture["authority_source"],
        },
        "sequence_grammar": capture["sequence_grammar"],
        "text": "\n".join(lines),
    }

if __name__ == "__main__":
    d = base.default_profile()
    assert d.get("profile_id")
    print("VISUAL PROFILE BRIDGE V2.2.6 SELF-TEST PASS")
