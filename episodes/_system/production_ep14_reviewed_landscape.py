"""Episode14 SHA-scoped, visually reviewed landscape-to-portrait recovery.

Not a general-purpose crop exception. Does not approve publication, change
storyboards, or grant additional paid image Attempts. Real original pixels,
independent production ledger provenance and MySQL fenced UNKNOWN are checked
by image_unknown_raw_reconcile before accepting this editorial presentation.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from PIL import Image
import canvas_normalize

ROOT=Path(__file__).resolve().parents[2]
EP=ROOT/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
SOURCE_SIZE=(1448,1086)
TARGET_SIZE=(1080,1350)
# Original SHA, exact reviewed crop box, protected narrative beat.
PROOFS={
    22:("24091e2e90c2b69dff87167c07a754b81ec778b0b42d064bee7ef6b7fd325efd",
        (350,0,1219,1086),"mirror reflection, high collar and hands all visible"),
    39:("2ee40c638334f651c97410d9cac49a02f16bc2ac11f19911b196d1f0dd2f8afa",
        (579,0,1448,1086),"right POV index finger with film and basin visible"),
    40:("0881fb7590e5920b004ac4707d095de0ca4ba0e3a4cafc4e038d72c81513c116",
        (50,0,919,1086),"investigator, pliers, white robe seam visible"),
}
EDITORIAL_RATIO_MAX=0.666667

def is_scoped(ep,frame):
    return Path(ep).resolve()==EP.resolve() and int(frame) in PROOFS

def verify_original(ep,frame,raw,receipt,ratio_delta):
    if not is_scoped(ep,frame):return False
    digest,box,_=PROOFS[int(frame)]
    raw=Path(raw).resolve();ep=Path(ep).resolve()
    if not raw.is_relative_to(ep/"media"/"raw"):return False
    if (str(receipt.get("raw_sha256") or "")!=digest
        or abs(float(ratio_delta)-2/3)>0.000001
        or (int(receipt.get("requested_canvas",{}).get("width") or 0),
            int(receipt.get("requested_canvas",{}).get("height") or 0))!=TARGET_SIZE):
        return False
    if not raw.is_file() or hashlib.sha256(raw.read_bytes()).hexdigest()!=digest:
        return False
    with Image.open(raw) as image:
        if image.format!="PNG" or image.size!=SOURCE_SIZE:return False
        image.verify()
    return (box[0]>=0 and box[1]>=0 and box[2]<=SOURCE_SIZE[0]
            and box[3]<=SOURCE_SIZE[1]
            and abs((box[2]-box[0])*TARGET_SIZE[1]-
                    (box[3]-box[1])*TARGET_SIZE[0])<=TARGET_SIZE[1]//2)

def normalize_verified(ep,frame,raw,out,width,height):
    if not is_scoped(ep,frame) or (width,height)!=TARGET_SIZE:
        raise canvas_normalize.NormalizeError("EDITORIAL_REFRAME_SCOPE_DENIED",
                                              "not an approved Episode14 canvas")
    original_sha,box,beat=PROOFS[int(frame)]
    src=Path(raw).resolve();dst=Path(out).resolve()
    if (not src.is_relative_to(Path(ep).resolve()/"media"/"raw")
        or src.suffix.lower()!=".png"
        or hashlib.sha256(src.read_bytes()).hexdigest()!=original_sha
        or dst.exists()):
        raise canvas_normalize.NormalizeError("EDITORIAL_REFRAME_SOURCE_INVALID",
                                              "original missing/mutated or candidate exists")
    with Image.open(src) as image:
        if image.format!="PNG" or image.size!=SOURCE_SIZE:
            raise canvas_normalize.NormalizeError("EDITORIAL_REFRAME_INPUT_INVALID",
                                                  "pixel format or dimensions drift")
        output=image.convert("RGB").crop(box).resize(TARGET_SIZE,resample=Image.Resampling.LANCZOS)
        dst.parent.mkdir(parents=True,exist_ok=True)
        temp=dst.with_name(f".{dst.name}.editorial-tmp")
        try:
            output.save(temp,"PNG",optimize=True)
            temp.replace(dst)
        finally:
            if temp.exists():temp.unlink()
    return {
        "source":str(src),"output":str(dst),
        "source_size":list(SOURCE_SIZE),"target_size":list(TARGET_SIZE),
        "ratio_delta":round(2/3,6),"operation":"SHA_BOUND_EDITORIAL_REFRAME_LANCZOS",
        "reencoded":True,"crop_applied":True,"crop_box":list(box),
        "policy":"NP01_EP14_REVIEWED_EDITORIAL_REFRAME",
        "exception_reason":"frame-specific source-SHA-bound editorial composition review; "
                           "original RAW remains untouched; subsequent independent Vision gate required",
        "protected_story_beat":beat,
        "original_raw_sha256":original_sha,
        "editorial_review_source":"assistant_visual_inspection_2026-10-26",
        "user_approved":False,
        "requires_independent_vision_review":True,
        "local_attempts":1,
    }
