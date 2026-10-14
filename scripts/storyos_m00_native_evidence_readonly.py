#!/usr/bin/env python3
"""Read-only historical M00 native pixel evidence; NEVER an image permit.

Two existing, independently SHA-verified TEST_ONLY images prove that an
image_generation invocation has succeeded before, not that today's Episode
or account is authorized for new paid production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import m00_calibration_receipts

IDS=("C02-R2","C04-R2")


def inspect(*,root:Path=ROOT)->dict:
    base={"read_only":True,"model_calls":0,"sql_writes":0,
          "can_dispatch_image":False,"production_authorization":False,
          "model_entitlement_verified":False,
          "test_only":True,"verified_image_count":0,
          "status":"IMAGE_TEST_PROOF_INCOMPLETE"}
    folder=root.resolve()/".storyos/user-visual-references/test-only-calibration"
    try:
        valid=[]
        for name in IDS:
            rec=folder/name/"test-only-record.json"
            result=m00_calibration_receipts.inspect_frame(folder,name)
            if not result.get("verified") or result.get("status")!="IMAGE_CREATED":
                break
            row=json.loads(rec.read_text(encoding="utf-8-sig"))
            mock=row.get("mock") or {}
            transport=row.get("runner_transport") or {}
            identity=row.get("request_identity")
            if (not isinstance(identity,dict) or identity.get("test_only") is not True
                    or (mock.get("authority")!="TEST_ONLY_LOCAL"
                        or any(mock.get(k) is not False for k in
                               ("production_authority","mysql_attempt","episode_authority")))
                    or transport.get("transport_route")!="native_codex"
                    or row.get("codex_returncode")!=0
                    or row.get("status")!="IMAGE_CREATED"
                    or row.get("model_requested") not in ("gpt-image-2.5-flare",)
                    or row.get("request_fingerprint")!=hashlib.sha256(json.dumps(
                        identity,sort_keys=True,ensure_ascii=False,
                        separators=(",",":")).encode("utf-8")).hexdigest()):
                break
            valid.append({"test_frame":name,"image_sha256":result["image_sha256"],
                          "dimensions":result["dimensions"]})
        result={**base,"verified_image_count":len(valid),"images":valid}
        if len(valid)==len(IDS):
            result.update(status="NATIVE_TEST_ONLY_PIXELS_VERIFIED",
                          next_blocker="CANONICAL_EPISODE_IMAGE_ATTEMPT_AND_VISUAL_LOCK_NOT_VERIFIED")
        return result
    except Exception:
        return base


def main(argv=None)->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.parse_args(argv)
    print(json.dumps(inspect(),ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
