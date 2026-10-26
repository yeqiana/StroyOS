#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalize an image to the exact Story OS episode canvas without overwriting the raw source.

Only a near-exact provider ratio may be resized.  This is technical standardization,
not geometric correction: larger ratio drift is held for review or rejected.
"""
from __future__ import annotations
import argparse
import json
import shutil
import time
from pathlib import Path
from canvas_spec import resolve_canvas_spec
import storyos_config
import production_ledger

_CONFIG = storyos_config.load_config()
AUTO_RATIO_DELTA_MAX = float(storyos_config.get_path(_CONFIG, 'normalize.automatic_ratio_delta_max'))
REVIEW_RATIO_DELTA_MAX = float(storyos_config.get_path(_CONFIG, 'normalize.review_ratio_delta_max'))
EXCEPTION_CROP_RATIO_DELTA_MAX = float(storyos_config.get_path(_CONFIG, 'normalize.exception_crop_ratio_delta_max', 0.06))
LOCAL_RETRIES = int(storyos_config.get_path(_CONFIG, 'normalize.local_retries'))


class NormalizeError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f'{code}: {message}')
        self.code = code


def require_pillow():
    try:
        from PIL import Image
        return Image
    except Exception as exc:
        raise SystemExit('Pillow is required. Run: python -m pip install -r episodes/_system/requirements.txt') from exc


def read_canvas(ep: Path) -> tuple[int, int, str]:
    manifest_ratio = None
    manifest = ep / 'meta' / 'release-manifest.json'
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding='utf-8'))
        manifest_ratio = str(((data.get('episode') or {}).get('aspect_ratio')) or '4:5')
        manifest_spec = resolve_canvas_spec(manifest_ratio)
    data = production_ledger.load_authority(Path(ep).resolve(), default=None)
    if isinstance(data, dict):
        canvas = data.get('canvas') or {}
        w, h = canvas.get('width'), canvas.get('height')
        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            ledger_ratio = str(canvas.get('aspect_ratio') or manifest_ratio or '4:5')
            ledger_spec = resolve_canvas_spec(ledger_ratio)
            if (w, h) != ledger_spec.size:
                raise NormalizeError('EPISODE_CANVAS_MISMATCH', f'ledger dimensions {w}x{h} do not match ledger ratio {ledger_ratio}')
            if manifest_ratio and ledger_spec.aspect_ratio != manifest_spec.aspect_ratio:
                raise NormalizeError('EPISODE_CANVAS_MISMATCH', f'ledger ratio {ledger_spec.aspect_ratio} != manifest ratio {manifest_spec.aspect_ratio}')
            return w, h, ledger_spec.aspect_ratio
    if manifest_ratio:
        return manifest_spec.width, manifest_spec.height, manifest_spec.aspect_ratio
    fallback = resolve_canvas_spec(None)
    return fallback.width, fallback.height, fallback.aspect_ratio


def _normalize_once(src: Path, dst: Path, width: int, height: int) -> dict:
    Image = require_pillow()
    if not src.is_file():
        raise NormalizeError('NORMALIZE_INPUT_MISSING', f'input missing: {src}')
    if dst.exists():
        raise NormalizeError('NORMALIZE_OUTPUT_EXISTS', f'output exists: {dst}')
    if dst.suffix.lower() != '.png':
        raise NormalizeError('NORMALIZE_OUTPUT_FORMAT', f'formal output must use .png: {dst}')
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        source_size = im.size
        source_ratio = source_size[0] / source_size[1]
        target_ratio = width / height
        ratio_delta = abs(source_ratio - target_ratio) / target_ratio
        if ratio_delta > REVIEW_RATIO_DELTA_MAX:
            raise NormalizeError('ASPECT_RATIO_MISMATCH', f'source={source_size[0]}x{source_size[1]}, target={width}x{height}, ratio_delta={ratio_delta:.6f}; inspect Generation Request before deciding whether to regenerate')
        if ratio_delta > AUTO_RATIO_DELTA_MAX:
            raise NormalizeError('NORMALIZE_REVIEW', f'source={source_size[0]}x{source_size[1]}, target={width}x{height}, ratio_delta={ratio_delta:.6f}; manual review required and crop is forbidden')

        tmp = dst.with_name(f'.{dst.name}.normalize-tmp')
        try:
            if source_size == (width, height) and str(im.format or '').upper() == 'PNG':
                shutil.copy2(src, tmp)
                operation = 'NOOP'
                reencoded = False
            else:
                out = im.convert('RGB')
                if source_size != (width, height):
                    out = out.resize((width, height), resample=Image.Resampling.LANCZOS)
                    operation = 'RESIZE_LANCZOS'
                else:
                    operation = 'FORMAT_TO_PNG'
                out.save(tmp, 'PNG', optimize=True)
                reencoded = True
            tmp.replace(dst)
        finally:
            if tmp.exists():
                tmp.unlink()
    return {
        'source': str(src),
        'output': str(dst),
        'source_size': list(source_size),
        'target_size': [width, height],
        'ratio_delta': round(ratio_delta, 6),
        'operation': operation,
        'reencoded': reencoded,
        'crop_applied': False,
        'policy': 'NP01',
    }


def normalize_provider_crop_exception(src: Path, dst: Path, width: int, height: int, *, reason: str, exception_crop_ratio_max: float | None = None) -> dict:
    """Explicit provider-size compatibility path; never used by default normalize().

    This preserves the provider RAW and only permits a small center crop when the
    generation request was already for the canonical canvas but the provider returned
    a nearby unsupported ratio. The caller must opt in explicitly and records the
    exception reason in the returned normalization evidence.
    """
    Image = require_pillow()
    if not src.is_file():
        raise NormalizeError('NORMALIZE_INPUT_MISSING', f'input missing: {src}')
    if dst.exists():
        raise NormalizeError('NORMALIZE_OUTPUT_EXISTS', f'output exists: {dst}')
    if dst.suffix.lower() != '.png':
        raise NormalizeError('NORMALIZE_OUTPUT_FORMAT', f'formal output must use .png: {dst}')
    with Image.open(src) as im:
        source_size = im.size
        source_ratio = source_size[0] / source_size[1]
        target_ratio = width / height
        ratio_delta = abs(source_ratio - target_ratio) / target_ratio
        maximum = (EXCEPTION_CROP_RATIO_DELTA_MAX if exception_crop_ratio_max is None
                   else float(exception_crop_ratio_max))
        if not EXCEPTION_CROP_RATIO_DELTA_MAX <= maximum <= 0.065:
            raise NormalizeError('ASPECT_RATIO_MISMATCH', 'unsupported exception crop upper bound')
        if ratio_delta > maximum:
            raise NormalizeError('ASPECT_RATIO_MISMATCH', f'provider exception refused: source={source_size[0]}x{source_size[1]}, target={width}x{height}, ratio_delta={ratio_delta:.6f} > exception_max={maximum:.6f}')
        if source_ratio < target_ratio:
            crop_h = max(1, round(source_size[0] / target_ratio))
            top = max(0, (source_size[1] - crop_h) // 2)
            box = (0, top, source_size[0], top + crop_h)
        else:
            crop_w = max(1, round(source_size[1] * target_ratio))
            left = max(0, (source_size[0] - crop_w) // 2)
            box = (left, 0, left + crop_w, source_size[1])
        out = im.convert('RGB').crop(box).resize((width, height), resample=Image.Resampling.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f'.{dst.name}.normalize-tmp')
        try:
            out.save(tmp, 'PNG', optimize=True)
            tmp.replace(dst)
        finally:
            if tmp.exists():
                tmp.unlink()
    return {
        'source': str(src),
        'output': str(dst),
        'source_size': list(source_size),
        'target_size': [width, height],
        'ratio_delta': round(ratio_delta, 6),
        'operation': 'CENTER_CROP_THEN_RESIZE_LANCZOS',
        'reencoded': True,
        'crop_applied': True,
        'crop_box': list(box),
        'policy': 'NP01_PROVIDER_EXCEPTION',
        'exception_reason': str(reason),
        'exception_ratio_delta_max': maximum,
        'local_attempts': 1,
    }


def normalize(src: Path, dst: Path, width: int, height: int, *, local_retries: int = LOCAL_RETRIES) -> dict:
    last_error = None
    for attempt in range(local_retries + 1):
        try:
            result = _normalize_once(src, dst, width, height)
            result['local_attempts'] = attempt + 1
            return result
        except NormalizeError:
            raise
        except OSError as exc:
            last_error = exc
            if attempt < local_retries:
                time.sleep(0.05 * (attempt + 1))
    raise NormalizeError('NORMALIZE_TECHNICAL_FAILURE', f'local retries exhausted ({local_retries + 1} attempts): {last_error}')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('file')
    p.add_argument('--input', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--width', required=True, type=int)
    p.add_argument('--height', required=True, type=int)
    p = sub.add_parser('episode')
    p.add_argument('episode_dir', type=Path)
    p.add_argument('--input', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    sub.add_parser('self-test')
    args = ap.parse_args()
    if args.cmd == 'self-test':
        from unittest.mock import patch
        # Simulate absent authority in an ephemeral fixture; never query MySQL.
        with patch.object(production_ledger, 'load_authority', return_value=None) as load:
            assert read_canvas(Path('__missing__')) == (1080, 1350, '4:5')
            load.assert_called_once()
        print('CANVAS NORMALIZE SELF-TEST PASS')
        return 0
    if args.cmd == 'episode':
        ep = args.episode_dir.resolve()
        width, height, ratio = read_canvas(ep)
    else:
        width, height, ratio = args.width, args.height, ''
    if width <= 0 or height <= 0:
        raise SystemExit('invalid target canvas')
    try:
        result = normalize(args.input.resolve(), args.output.resolve(), width, height)
    except NormalizeError as exc:
        print(json.dumps({'ok': False, 'code': exc.code, 'error': str(exc)}, ensure_ascii=False))
        return 2
    result['aspect_ratio'] = ratio
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
