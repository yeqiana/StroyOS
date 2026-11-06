#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from story_os_contract import story_os_version
from frame_semantic_review import review_required as frame_semantic_required, verify_episode as verify_frame_semantic_episode
import final_candidate_snapshot as final_snapshot
from final_acceptance import allows as acceptance_allows
import story_json
import frame_review_persistence
import story_review
import visual_profile_review_persistence
import verified_review_authority
import final_acceptance
import approval_persistence

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_REL = Path('meta/release-manifest.json')
PACKAGE_REL = Path('meta/release-package.json')
STORY_OS_VERSION = story_os_version()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


def load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise SystemExit(f'JSON root must be object: {path}')
    return data


def save_json(path: Path, data: dict) -> None:
    story_json.write_json(path, data)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def digest_payload(payload: dict) -> str:
    clean = json.loads(json.dumps(payload, ensure_ascii=False))
    clean.pop('package_sha256', None)
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def ep_dir(raw: str) -> Path:
    ep = Path(raw).resolve()
    if not ep.is_dir():
        raise SystemExit(f'episode directory not found: {ep}')
    return ep


def repo_file(raw: object, where: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise SystemExit(f'{where} missing')
    rel = Path(raw.strip())
    if rel.is_absolute():
        raise SystemExit(f'{where} must be repository-relative')
    p = (ROOT / rel).resolve()
    try:
        p.relative_to(ROOT.resolve())
    except ValueError:
        raise SystemExit(f'{where} escapes repository')
    if not p.is_file():
        raise SystemExit(f'{where} file missing: {raw}')
    return p


def repo_dir(raw: object, where: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise SystemExit(f'{where} missing')
    rel = Path(raw.strip())
    if rel.is_absolute():
        raise SystemExit(f'{where} must be repository-relative')
    p = (ROOT / rel).resolve()
    try:
        p.relative_to(ROOT.resolve())
    except ValueError:
        raise SystemExit(f'{where} escapes repository')
    if not p.is_dir():
        raise SystemExit(f'{where} directory missing: {raw}')
    return p


def file_row(path: Path, role: str) -> dict:
    return {
        'role': role,
        'path': path.resolve().relative_to(ROOT.resolve()).as_posix(),
        'sha256': sha256_file(path),
        'bytes': path.stat().st_size,
    }


def build_payload(ep: Path) -> dict:
    verified_review_authority.require_verified_episode_review_authority(ep, metadata_only=False)
    review_authority = verified_review_authority.verify_episode_review_authority(ep, metadata_only=False)
    user_final_authority = review_authority.get('status') == 'USER_ACCEPTED'
    snapshot_sha=None
    if final_snapshot.required(ep) or (ep/final_snapshot.SNAPSHOT_REL).is_file():
        errors=final_snapshot.verify(ep)
        if errors: raise SystemExit('final candidate snapshot preflight failed: ' + '; '.join(errors))
        snapshot_sha=(final_snapshot.read_json(ep/final_snapshot.SNAPSHOT_REL).get('snapshot_sha256'))
    if frame_semantic_required(ep):
        semantic_errors = verify_frame_semantic_episode(ep, metadata_only=False, write_audit=True)
        if semantic_errors:
            if not acceptance_allows(ep, "frame_semantic"):
                raise SystemExit('frame semantic release preflight failed: ' + '; '.join(semantic_errors))
            print('RELEASE PACKAGE WARN: frame semantic known defects accepted (meta/final-acceptance.json)')
    manifest = load_json(ep / MANIFEST_REL)
    release = manifest.get('release') or {}
    artifacts = manifest.get('artifacts') or {}
    episode = manifest.get('episode') or {}
    publication = manifest.get('publication') or {}

    publish_dir = repo_dir(release.get('publish_dir'), 'manifest.release.publish_dir')
    body_glob = str(release.get('body_glob') or '').strip()
    if not body_glob:
        raise SystemExit('manifest.release.body_glob missing')
    body_files = sorted([p for p in publish_dir.glob(body_glob) if p.is_file()], key=lambda p: p.name)
    expected_count = release.get('body_frame_count')
    if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count <= 0:
        raise SystemExit('manifest.release.body_frame_count invalid')
    if len(body_files) != expected_count:
        raise SystemExit(f'body image count mismatch: expected={expected_count}, found={len(body_files)}')

    cover = repo_file(release.get('cover_path'), 'manifest.release.cover_path')
    captions = repo_file(artifacts.get('captions'), 'manifest.artifacts.captions')
    publish_copy = repo_file(artifacts.get('publish_copy'), 'manifest.artifacts.publish_copy')
    propagation = repo_file(artifacts.get('propagation_card'), 'manifest.artifacts.propagation_card')

    payload = {
        'schema_version': 1,
        'story_os_version': STORY_OS_VERSION,
        'built_at': now_iso(),
        'episode': {
            'id': episode.get('id'),
            'series': episode.get('series'),
            'title': episode.get('title'),
            'aspect_ratio': episode.get('aspect_ratio'),
        },
        'release_version': release.get('version'),
        'publication': {
            'platform': publication.get('platform'),
            'actual_title': publication.get('actual_title'),
        },
        'cover': file_row(cover, 'cover'),
        'body': [file_row(p, f'body:{p.stem}') for p in body_files],
        'text_artifacts': [
            file_row(captions, 'captions'),
            file_row(publish_copy, 'publish_copy'),
            file_row(propagation, 'propagation_card'),
        ],
        'evidence': [],
        'final_candidate_snapshot_sha256': snapshot_sha,
        'package_sha256': None,
    }
    if user_final_authority:
        acceptance = final_acceptance.valid(ep)
        if not acceptance or not acceptance.get('accepted_visual_assets'):
            raise SystemExit('direct-user final acceptance invalid or without SHA-bound pixels')
        payload['direct_user_final_acceptance'] = {
            'basis': 'SHA_BOUND_DIRECT_USER_FINAL_ASSETS',
            'approval_sha256': approval_persistence.source_sha(
                ep, approval_persistence.FINAL_ACCEPTANCE),
            'known_defect_frames': acceptance['known_defect_frames'],
            'machine_review_pass': False,
        }
    if frame_semantic_required(ep):
        if user_final_authority:
            # The actual model verdict was not PASS: package the independent
            # recorded user decision and the original semantic candidate, not
            # synthetic model Review/PASS files.
            evidence_paths = [
                ep/'meta/.frame-semantic-review.candidate.json',
                ep/'meta/runtime/final-acceptance-events.jsonl',
                ep/'meta/subtitle-layout-audit.json', ep/'meta/story-gates.json',
            ]
        else:
            evidence_paths = [
                ep/'meta/frame-semantic-review.json', ep/'meta/frame-semantic-audit.json',
                ep/'meta/subtitle-layout-audit.json', ep/'meta/story-gates.json',
            ]
        story_review_export=story_review.materialize_review_export(ep,story_review.load_review(ep))
        if story_review_export is not None and story_review_export.is_file():
            evidence_paths.append(story_review_export)
        visual_review_export=visual_profile_review_persistence.materialize_export(
            ep,visual_profile_review_persistence.load(ep)
        )
        if visual_review_export is not None and visual_review_export.is_file():
            evidence_paths.append(visual_review_export)
        missing = [str(p.relative_to(ep)) for p in evidence_paths[:2] if not p.is_file()]
        if missing: raise SystemExit('release evidence missing: ' + ', '.join(missing))
        payload['evidence'] = [file_row(p, 'evidence') for p in evidence_paths if p.is_file()]
        payload['frame_review_db_evidence'] = frame_review_persistence.evidence_digest(ep)
    payload['package_sha256'] = digest_payload(payload)
    return payload


def verify_payload(ep: Path, payload: dict) -> list[str]:
    errors: list[str] = []
    expected_pkg = str(payload.get('package_sha256') or '')
    actual_pkg = digest_payload(payload)
    if expected_pkg.lower() != actual_pkg.lower():
        errors.append(f'package manifest digest drift: expected={expected_pkg}, actual={actual_pkg}')
    rows = []
    if isinstance(payload.get('cover'), dict):
        rows.append(payload['cover'])
    rows.extend([x for x in payload.get('body') or [] if isinstance(x, dict)])
    rows.extend([x for x in payload.get('text_artifacts') or [] if isinstance(x, dict)])
    rows.extend([x for x in payload.get('evidence') or [] if isinstance(x, dict)])
    if not rows:
        errors.append('release package contains no files')
    for row in rows:
        raw = row.get('path')
        expected = str(row.get('sha256') or '')
        try:
            p = repo_file(raw, 'release-package.path')
        except SystemExit as e:
            errors.append(str(e))
            continue
        actual = sha256_file(p)
        if actual.lower() != expected.lower():
            errors.append(f'release file SHA256 drift: {raw}\nexpected={expected}\nactual  ={actual}')
        if isinstance(row.get('bytes'), int) and p.stat().st_size != row['bytes']:
            errors.append(f'release file size drift: {raw}')

    manifest = load_json(ep / MANIFEST_REL)
    expected_count = ((manifest.get('release') or {}).get('body_frame_count'))
    body = payload.get('body') or []
    if isinstance(expected_count, int) and len(body) != expected_count:
        errors.append(f'release-package body count mismatch: expected={expected_count}, package={len(body)}')
    user_final = payload.get('direct_user_final_acceptance')
    if isinstance(user_final, dict):
        observed = verified_review_authority.verify_episode_review_authority(
            ep, metadata_only=False)
        current_sha = approval_persistence.source_sha(
            ep, approval_persistence.FINAL_ACCEPTANCE)
        if (observed.get('status') != 'USER_ACCEPTED'
                or user_final.get('basis') != 'SHA_BOUND_DIRECT_USER_FINAL_ASSETS'
                or user_final.get('machine_review_pass') is not False
                or str(user_final.get('approval_sha256') or '') != current_sha
                or sorted(f'{int(value):02d}' for value in user_final.get('known_defect_frames') or [])
                   != observed.get('known_defect_frames')):
            errors.append('direct-user final acceptance authority drift or revoked')
    expected_reviews = payload.get('frame_review_db_evidence')
    if isinstance(expected_reviews, dict):
        actual_reviews = frame_review_persistence.evidence_digest(ep)
        if expected_reviews != actual_reviews:
            errors.append('release frame review database evidence drift')
    return errors


def cmd_build(args: argparse.Namespace) -> int:
    if not args.user_approved:
        raise SystemExit('release package lock requires --user-approved')
    ep = ep_dir(args.episode_dir)
    payload = build_payload(ep)
    payload['user_approved'] = True
    payload['approved_at'] = now_iso()
    # approval fields are part of the package lock too
    payload['package_sha256'] = digest_payload(payload)
    save_json(ep / PACKAGE_REL, payload)
    print(f"RELEASE PACKAGE LOCKED: {payload['package_sha256']}")
    print(f"  cover: {payload['cover']['path']}")
    print(f"  body: {len(payload['body'])}")
    print(f"  manifest: {(ep / PACKAGE_REL)}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    ep = ep_dir(args.episode_dir)
    path = ep / PACKAGE_REL
    if not path.is_file():
        print('FAIL: meta/release-package.json missing')
        return 2
    payload = load_json(path)
    if payload.get('user_approved') is not True:
        print('FAIL: release package is not explicitly user-approved')
        return 2
    errors = verify_payload(ep, payload)
    if errors:
        for e in errors:
            print(f'FAIL: {e}')
        return 2
    print(f"release-package: PASS {payload.get('package_sha256')}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    ep = ep_dir(args.episode_dir)
    print((ep / PACKAGE_REL).read_text(encoding='utf-8'))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=f'Story OS V{STORY_OS_VERSION} deterministic release package hash')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('build'); p.add_argument('episode_dir'); p.add_argument('--user-approved', action='store_true'); p.set_defaults(func=cmd_build)
    p = sub.add_parser('verify'); p.add_argument('episode_dir'); p.set_defaults(func=cmd_verify)
    p = sub.add_parser('show'); p.add_argument('episode_dir'); p.set_defaults(func=cmd_show)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
