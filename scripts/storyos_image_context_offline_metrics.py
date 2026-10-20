"""Read-only counters for a frozen image payload; no model, SQL or Provider call."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path


def summarize(request: dict) -> dict:
    scene = str(request.get("scene_prompt") or "")
    refs = request.get("references") if isinstance(request.get("references"), list) else []
    return {
        "status": "EVIDENCE_ONLY",
        "scene_utf8_bytes": len(scene.encode("utf-8")),
        "scene_sha256": hashlib.sha256(scene.encode("utf-8")).hexdigest(),
        "frozen_block_count": scene.count("[STORYOS FROZEN FRAME OBLIGATIONS]"),
        "reference_count": len(refs),
        "reference_kinds": [str(r.get("kind") or "") for r in refs if isinstance(r, dict)],
        "model_calls": 0,
        "sql_writes": 0,
        "publish_ready_verified": False,
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen_payload_json",type=Path)
    args=parser.parse_args()
    request=json.loads(args.frozen_payload_json.read_text(encoding="utf-8"))
    print(json.dumps(summarize(request),ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
