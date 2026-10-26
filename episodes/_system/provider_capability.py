#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, time
from pathlib import Path
from PIL import Image
import storyos_config
import model_policy
import provider_receipt_persistence
import storage_config

ROOT = Path(__file__).resolve().parents[2]
_CONFIG = storyos_config.load_config()
DEFAULT_MODEL = str(model_policy.resolve("image.payload")["model"])
PROVIDER_RAW_MIN_DIMENSION = int(storyos_config.get_path(_CONFIG, "normalize.provider_raw_min_dimension"))


class ProviderCapabilityError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = str(code)
        super().__init__(f"{self.code}: {message}")

def _json(path: Path) -> dict:
    data=json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data,dict): raise ValueError(f"JSON root must be object: {path}")
    return data

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def registry() -> dict:
    raw=storyos_config.get_path(_CONFIG,"provider.registry")
    if not isinstance(raw,str) or not raw.strip(): raise ValueError("provider.registry missing")
    return _json(ROOT/raw)

def resolve(model: str, route: str|None=None) -> dict:
    reg=registry(); profiles=reg.get("profiles") or {}; default_id=str(reg.get("default_capability_id") or "")
    requested=str(model or "").strip()
    selected=None
    for _,rel in profiles.items():
        profile=_json(ROOT/str(rel)); routes=set(profile.get("transport_family") or [])
        if requested and str(profile.get("model") or "")==requested and (not route or not routes or route in routes):
            selected=profile; break
    # A named model must never inherit another model's capability record. This
    # prevents a newly introduced or misspelled model from producing false
    # provider evidence under the registry default.
    if requested and selected is None:
        raise ValueError(f"PROVIDER_CAPABILITY_MISSING: model={requested} route={route}")
    if selected is None and default_id in profiles:
        selected=_json(ROOT/str(profiles[default_id]))
    if selected is None:
        raise ValueError(f"PROVIDER_CAPABILITY_MISSING: model={requested} route={route}")
    return selected

def image_size(path: Path) -> tuple[int,int]:
    with Image.open(path) as im: return int(im.width),int(im.height)

def _direction(src,target):
    if src==target:return "exact"
    a=src[0]*src[1];b=target[0]*target[1]
    return "upscale" if a<b else ("downscale" if a>b else "reshape")

def inspect(raw_path:Path,requested_width:int,requested_height:int,*,model:str,route:str,frame:int|None=None)->dict:
    profile=resolve(model,route); src=image_size(raw_path); target=(int(requested_width),int(requested_height))
    if min(src) < PROVIDER_RAW_MIN_DIMENSION:
        raise ProviderCapabilityError(
            "PROVIDER_RAW_CANVAS_DEGENERATE",
            f"provider returned {src[0]}x{src[1]}; minimum production RAW dimension is {PROVIDER_RAW_MIN_DIMENSION}px",
        )
    sr=src[0]/src[1];tr=target[0]/target[1];delta=abs(sr-tr)/tr
    auto=float(storyos_config.get_path(_CONFIG,"normalize.automatic_ratio_delta_max"))
    review=float(storyos_config.get_path(_CONFIG,"normalize.review_ratio_delta_max"))
    decision="AUTO_NORMALIZE" if delta<=auto else ("NORMALIZE_REVIEW" if delta<=review else "ASPECT_RATIO_MISMATCH")
    return {
        "schema_version":1,"recorded_at_epoch":int(time.time()),
        "frame":f"{int(frame):02d}" if frame is not None else None,
        "provider":profile.get("provider"),"model":model,"generation_route":route,
        "capability_id":profile.get("capability_id"),
        "requested_canvas":{"width":target[0],"height":target[1],"aspect_ratio":round(tr,9)},
        "provider_raw_canvas":{"width":src[0],"height":src[1],"aspect_ratio":round(sr,9),
            "exact_requested_canvas":src==target,"resize_direction_to_release":_direction(src,target)},
        "ratio_delta":round(delta,9),"normalize_decision":decision,
        "raw_path":str(raw_path),"raw_sha256":sha256_file(raw_path),
        "provider_attestation":False,
        "exact_raw_canvas_guaranteed":bool(((profile.get("requested_canvas") or {}).get("exact_raw_canvas_guaranteed"))),
        "receipt_is_evidence_not_authority":True,
    }

def receipt_path(ep:Path,frame:int,stamp:int|None=None)->Path:
    return ep/"meta"/"provider-receipts"/f"{int(frame):02d}-{int(stamp or time.time())}.json"

def _rel(path:Path)->str:
    try:return path.relative_to(ROOT).as_posix()
    except ValueError:return str(path)

def reference_evidence(references)->list[dict]:
    """W-21 execution evidence: reference files actually handed to the provider.

    A story-gates reference registry only proves intent. The provider receipt
    must record the raw source files that were really sent, with their SHA-256,
    so a later gate can prove execution instead of only a declaration. Worker
    JPEG proxies are disposable and never recorded here; source authority wins.
    """
    rows=[]
    for index,ref in enumerate(references or [],1):
        raw=ref.get("path") if isinstance(ref,dict) else ref
        if not raw:continue
        path=Path(str(raw))
        path=path.resolve() if path.is_absolute() else (ROOT/str(raw)).resolve()
        rows.append({
            "order":index,
            "path":_rel(path),
            "sha256":sha256_file(path) if path.is_file() else None,
        })
    return rows

def write_receipt(ep:Path,frame:int,receipt:dict)->dict:
    path=receipt_path(ep,frame,receipt.get("recorded_at_epoch")); rel=_rel(path)
    serialized=json.dumps(receipt,ensure_ascii=False,indent=2)+"\n"
    mode=storage_config.episode_meta_store_config()["mode"]
    if mode != "mysql":
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(serialized,encoding="utf-8")
        digest=sha256_file(path)
    else:
        digest=hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    provider_receipt_persistence.persist(ep, receipt, status="RECORDED", legacy_path=rel, legacy_sha256=digest)
    return {"path":rel,"sha256":digest,"receipt":receipt}

def finalize_receipt(path:Path,normalization:dict,final_path:Path)->dict:
    path=Path(path).resolve(); ep=path.parents[2]
    loaded=provider_receipt_persistence.load_by_path(ep,path)
    if not loaded or not isinstance(loaded.get("payload"),dict):
        raise ValueError(f"provider receipt not found: {path}")
    data=dict(loaded["payload"])
    data["normalization"]={k:normalization.get(k) for k in ("operation","ratio_delta","crop_applied","reencoded","local_attempts")}
    data["release_canvas"]={"width":int(normalization["target_size"][0]),"height":int(normalization["target_size"][1]),
        "path":str(final_path),"sha256":sha256_file(final_path)}
    # Store the complete exceptional editorial crop geometry in the canonical
    # MySQL receipt. This is never a user approval or a completed Vision gate.
    if normalization.get("policy")=="NP01_EP14_REVIEWED_EDITORIAL_REFRAME":
        data["editorial_reframe"]={
            key:normalization[key] for key in (
                "policy","crop_box","original_raw_sha256","protected_story_beat",
                "editorial_review_source","user_approved",
                "requires_independent_vision_review")
        }
    serialized=json.dumps(data,ensure_ascii=False,indent=2)+"\n"; rel=_rel(path)
    mode=storage_config.episode_meta_store_config()["mode"]
    if mode != "mysql":
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(serialized,encoding="utf-8")
        digest=sha256_file(path)
    else:
        digest=hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    provider_receipt_persistence.persist(ep, data, status="FINALIZED", legacy_path=rel, legacy_sha256=digest)
    return {"path":rel,"sha256":digest,"receipt":data}

def self_test():
    p=resolve(DEFAULT_MODEL,"codex_subscription")
    assert p["model"] == DEFAULT_MODEL
    assert p["requested_canvas"]["exact_raw_canvas_guaranteed"] is False
    assert p["normalize"]["crop_forbidden_by_default"] is True
    assert resolve("gpt-image-2","codex_subscription")["model"] == "gpt-image-2"
    try:
        resolve("gpt-image-does-not-exist","codex_subscription")
    except ValueError as exc:
        assert "PROVIDER_CAPABILITY_MISSING" in str(exc)
    else:
        raise AssertionError("unknown named model must fail closed")
    print("PROVIDER CAPABILITY SELF-TEST PASS")

def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("show");p.add_argument("--model",default=DEFAULT_MODEL);p.add_argument("--route",default="codex_subscription")
    p=sub.add_parser("inspect");p.add_argument("raw_path",type=Path);p.add_argument("--width",type=int,required=True);p.add_argument("--height",type=int,required=True);p.add_argument("--model",default=DEFAULT_MODEL);p.add_argument("--route",default="codex_subscription")
    sub.add_parser("self-test");a=ap.parse_args()
    if a.cmd=="self-test":self_test();return 0
    if a.cmd=="show":print(json.dumps(resolve(a.model,a.route),ensure_ascii=False,indent=2));return 0
    print(json.dumps(inspect(a.raw_path.resolve(),a.width,a.height,model=a.model,route=a.route),ensure_ascii=False,indent=2));return 0

if __name__=="__main__":raise SystemExit(main())
