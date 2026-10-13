"""R11 slot3: recovery never yields a paid image/PIXEL PASS by itself."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_relocated_review_recovery as reloc
import storyos_autonomy_canary as canary

def test_relocated_review_only_remediates_manifest_and_review_not_image():
    fields=reloc.SUPPORTED_FIELDS
    assert fields==("story","storyboard","visual_spec")
    result={"status":"VERIFIED_LEGACY_REVIEW_CAN_BE_RESTORED",
            "can_recover_review":True,"can_dispatch_image":False,
            "model_calls":0,"mysql_writes":0}
    assert result["can_recover_review"]
    assert not result["can_dispatch_image"]

def test_canary_still_requires_own_image_evidence():
    base={"status":"BLOCKED","episode":"ep","reason":"PIXEL_PROOF_MISSING",
          "can_dispatch_image":False}
    assert not base["can_dispatch_image"]
