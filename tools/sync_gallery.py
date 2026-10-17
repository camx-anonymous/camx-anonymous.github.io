#!/usr/bin/env python3
"""Publish a completed local gallery without running a second renderer.

The public gallery keeps the same episodes, source frames, notes and comparisons.
Stitched videos are NVENC-compressed; camera selections crop those same strips.
Only gallery/ and data/gallery-sync.json are owned by this publisher. Existing
website previews, sample archives and unrelated working-tree edits are retained.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def run(args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, capture_output=True,
                          text=True, **kwargs).stdout.strip()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def local_path(root, url):
    parts = urlsplit(url)
    if parts.scheme or parts.netloc:
        raise ValueError('Expected a relative gallery asset URL')
    p = (root / unquote(parts.path)).resolve()
    if not p.is_relative_to(root.resolve()) or not p.is_file():
        raise ValueError(f'Missing or unsafe asset: {url}')
    return p


PRIVATE_KEYS = {'dataset_root', 'command', 'command_shell', 'stdout_tail',
                'stderr_tail', 'source_realpath', 'config_resolved', 'profile_resolved'}


def public_value(value):
    """Retain scientific metadata, omit local execution paths and account names."""
    if isinstance(value, dict):
        return {k: public_value(v) for k, v in value.items() if k not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [public_value(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'/(?:storage|home|nfs|tmp)/[^\s\"<>]+', '[local path]', value)
        return re.sub(r'\b(?:yihuai|chilingh?|yutianch|desktop001|realdesktop016)\b',
                      '[local account]', value, flags=re.I)
    return value


def probe(path):
    s = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,nb_frames,r_frame_rate',
        '-of', 'json', path]))['streams'][0]
    return {'width': int(s['width']), 'height': int(s['height']),
            'frames': int(s['nb_frames']), 'rate': s['r_frame_rate']}


def refs(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if k == 'url' and isinstance(v, str) and not urlsplit(v).scheme:
                yield v
            else:
                yield from refs(v)
    elif isinstance(value, list):
        for v in value:
            yield from refs(v)


def build(source, website, work, gpu=1, jobs=2, quiet_seconds=60):
    source, website, work = source.resolve(), website.resolve(), work.resolve()
    manifest_bytes = (source / 'gallery.json').read_bytes()
    gallery = json.loads(manifest_bytes)
    if gallery.get('counts', {}).get('pending') or gallery.get('counts', {}).get('failed'):
        raise ValueError('Publish only a completed gallery with no failed clips')
    clips = gallery['clips']
    if not clips or any(c['status'] not in ('ok', 'raw') for c in clips):
        raise ValueError('Incomplete gallery')
    target = website / 'gallery'
    cache = work / 'encoded'
    cache.mkdir(parents=True, exist_ok=True)
    inputs = {}

    def track(p):
        p = p.resolve()
        inputs[str(p)] = (p.stat().st_size, p.stat().st_mtime_ns)
        return p

    track(source / 'gallery.json')
    comparison_bytes = (source / 'comparisons.json').read_bytes() if (source / 'comparisons.json').exists() else None
    comparisons = json.loads(comparison_bytes) if comparison_bytes else None
    if comparisons:
        track(source / 'comparisons.json')
    for c in clips:
        for url in [c['meta_url'], c['poster'], c['views'][0]['url']]:
            if url:
                track(local_path(source, url))
    if comparisons:
        for url in refs(comparisons):
            track(local_path(source, url))
    for n in ('index.html', 'gallery.css', 'gallery.js', 'comparisons.css', 'comparisons.js',
              'projection-audit.json', 'projection-audit.js', 'publication-ui.js', 'publication-ui.css'):
        if (source / n).exists():
            track(source / n)
    audit = source / 'evidence/public-projection-screen-20261016'
    for p in audit.rglob('*'):
        if p.is_file():
            track(p)
    if quiet_seconds and any(time.time() - n / 1e9 < quiet_seconds for _, n in inputs.values()):
        raise ValueError('Gallery is still changing; waiting for a quiet snapshot')
    signature = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode() + Path(__file__).read_bytes()).hexdigest()
    existing = website / 'data/gallery-sync.json'
    if existing.exists():
        old = json.loads(existing.read_text())
        if old.get('source_signature') == signature and old.get('files') and all(
                (target / p).is_file() and sha(target / p) == digest
                for p, digest in old.get('files', {}).items()):
            return old, False

    def encode(c):
        src = local_path(source, c['views'][0]['url'])
        digest = sha(src)
        key = digest + '-360-cq34-nvenc-v1'
        video, receipt = cache / (key + '.mp4'), cache / (key + '.json')
        if not receipt.exists() or not video.exists() or sha(video) != json.loads(receipt.read_text())['sha256']:
            temp = video.with_suffix('.pending.mp4')
            run(['ffmpeg', '-nostdin', '-v', 'error', '-hwaccel', 'cuda',
                 '-hwaccel_device', gpu, '-threads', '1', '-i', src,
                 '-vf', "scale=-2:'min(360,ih)',setsar=1", '-c:v', 'h264_nvenc',
                 '-gpu', gpu, '-preset', 'p6', '-rc', 'vbr', '-cq', '34', '-b:v', '0',
                 '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', '-y', temp])
            before, after = probe(src), probe(temp)
            if before['frames'] != after['frames'] or Fraction(before['rate']) != Fraction(after['rate']):
                raise ValueError('Encoding changed frame count/rate: ' + c['id'])
            temp.replace(video)
            dump(receipt, {'sha256': sha(video), 'source_sha256': digest, **after})
        return c['id'], video, json.loads(receipt.read_text())

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        encoded = {}
        for i, (cid, p, rec) in enumerate(pool.map(encode, clips), 1):
            encoded[cid] = (p, rec)
            if i % 25 == 0:
                print(f'Encoded/verified {i}/{len(clips)} clips', flush=True)
    with tempfile.TemporaryDirectory(prefix='publish-stage-', dir=work) as temp:
        stage = Path(temp)

        def copy_asset(url, metadata=False):
            src = local_path(source, url)
            rel = unquote(urlsplit(url).path)
            dst = stage / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix == '.mp4':
                _, compressed, _ = encode({'id': url, 'views': [{'url': url}]})
                shutil.copyfile(compressed, dst)
            elif src.suffix == '.json':
                dump(dst, public_value(json.loads(src.read_text())))
            elif src.suffix in ('.md', '.txt', '.html'):
                dst.write_text(public_value(src.read_text()))
            else:
                shutil.copyfile(src, dst)
            return rel

        for c in clips:
            video, rec = encoded[c['id']]
            meta = json.loads(local_path(source, c['meta_url']).read_text())
            window = meta.get('clip', {})
            expected = math.ceil(window['source_frames'] / window['stride'])
            if (expected != rec['frames'] or
                    abs(float(Fraction(rec['rate'])) - window['out_fps']) > .001):
                raise ValueError('Video does not match its completed render metadata: ' + c['id'])
            stitch_url = c['views'][0]['url']
            dst = stage / unquote(stitch_url)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(video, dst)
            copy_asset(c['meta_url'], metadata=True)
            if c['poster']:
                copy_asset(c['poster'])
            views = meta.get('views', [])
            widths = (meta.get('renderer_summary') or {}).get('tile_w')
            if not widths:
                widths = [probe(local_path(source, v['url']))['width'] for v in c['views'][1:]]
            if len(widths) != len(views) or len(c['views']) != len(views) + 1:
                raise ValueError('Unknown tile geometry: ' + c['id'])
            full = sum(widths)
            if full != probe(local_path(source, stitch_url))['width']:
                raise ValueError('Camera tiles do not cover the stitched video: ' + c['id'])
            source_height = (meta.get('renderer_summary') or {}).get('tile_h')
            if not source_height:
                source_height = probe(local_path(source, stitch_url))['height']
            offset = 0
            for v, width in zip(c['views'][1:], widths):
                v['url'] = stitch_url
                v['crop'] = {'left': offset / full, 'width': width / full,
                             'aspect': width / source_height}
                offset += width
            c['published_media'] = {'source_sha256': rec['source_sha256'],
                                    'sha256': rec['sha256'], 'height': rec['height'],
                                    'frames': rec['frames'], 'rate': rec['rate']}
            for v in c['views']:
                v['url'] += '?v=' + rec['sha256'][:16]
            for key in ('poster', 'meta_url'):
                if c.get(key):
                    c[key] += '?v=' + sha(stage / unquote(c[key]))[:16]
        for n in ('index.html', 'gallery.css', 'gallery.js', 'comparisons.css', 'comparisons.js',
                  'projection-audit.json', 'projection-audit.js', 'publication-ui.js', 'publication-ui.css'):
            if (source / n).exists():
                copy_asset(n)
        for p in (source / 'evidence').iterdir():
            if p.is_file() and p.suffix in ('.md', '.json'):
                copy_asset(str(p.relative_to(source)))
        for p in audit.rglob('*'):
            if p.is_file():
                copy_asset(str(p.relative_to(source)))
        if comparisons:
            for url in set(refs(comparisons)):
                copy_asset(url)
            # Sanitized metadata has different bytes: keep comparison checksums truthful.
            def fix_hashes(v):
                if isinstance(v, dict):
                    if 'url' in v and not urlsplit(v['url']).scheme and 'sha256' in v:
                        v['source_sha256'] = v['sha256']
                        asset = stage / unquote(urlsplit(v['url']).path)
                        v['sha256'] = sha(asset)
                        if asset.suffix == '.mp4':
                            info = probe(asset)
                            v.update(width=info['width'], height=info['height'])
                        v['url'] += '?v=' + v['sha256'][:16]
                    for x in v.values():
                        fix_hashes(x)
                elif isinstance(v, list):
                    for x in v:
                        fix_hashes(x)
            fix_hashes(comparisons)
            dump(stage / 'comparisons.json', public_value(comparisons))
        gallery['publication'] = {'source_gallery_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
                                  'encoding': 'Same rendered frames, H.264 NVENC, up to 360 rows; camera views crop the stitched strip.'}
        dump(stage / 'gallery.json', public_value(gallery))
        now = datetime.now(timezone.utc).isoformat()
        hashes = {str(p.relative_to(stage)): sha(p) for p in stage.rglob('*') if p.is_file()}
        total = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())
        existing_size = sum(p.stat().st_size for p in website.rglob('*')
                            if p.is_file() and '.git' not in p.parts and not p.is_relative_to(target))
        if total + existing_size > 990_000_000:
            raise ValueError(f'Publication would exceed site size budget: {total + existing_size} bytes')
        if any(not Path(p).exists() or (Path(p).stat().st_size, Path(p).stat().st_mtime_ns) != st
               for p, st in inputs.items()):
            raise ValueError('Source changed during publication; staged output rejected')
        report = {'schema': 1, 'published_at': now, 'source_signature': signature,
                  'source_gallery_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
                  'source_comparisons_sha256': hashlib.sha256(comparison_bytes).hexdigest() if comparison_bytes else None,
                  'clips': len(clips), 'projects': gallery['project_count'],
                  'bytes': total, 'files': hashes,
                  'scope': 'Local gallery episodes, renders, comparisons and caveats; historical preview pages remain separately available.'}
        # Validate all relative manifest references before touching the destination.
        for c in clips:
            for url in [c['poster'], c['meta_url'], *[v['url'] for v in c['views']]]:
                if url:
                    local_path(stage, url)
        target.mkdir(exist_ok=True)
        for p in stage.rglob('*'):
            if p.is_file():
                dst = target / p.relative_to(stage)
                dst.parent.mkdir(parents=True, exist_ok=True)
                pending = dst.with_suffix(dst.suffix + '.pending')
                shutil.copyfile(p, pending)
                pending.replace(dst)
        # Only files created by earlier invocations may be pruned.
        if existing.exists():
            old = json.loads(existing.read_text())
            for rel in set(old.get('files', {})) - set(hashes):
                p = (target / rel).resolve()
                if p.is_relative_to(target) and p.is_file():
                    p.unlink()
        dump(existing, report)
        return report, True


def publish(website):
    """Commit only our generated paths, without staging other sessions' edits."""
    paths = ['gallery', 'data/gallery-sync.json']
    run(['git', 'fetch', 'origin', 'main'], cwd=website)
    head = run(['git', 'rev-parse', 'HEAD'], cwd=website)
    remote = run(['git', 'rev-parse', 'origin/main'], cwd=website)
    if head != remote:
        ancestor = subprocess.run(['git', 'merge-base', '--is-ancestor', head, remote], cwd=website)
        if ancestor.returncode == 0:
            run(['git', 'merge', '--ff-only', 'origin/main'], cwd=website)
    run(['git', 'merge-base', '--is-ancestor', 'origin/main', 'HEAD'], cwd=website)
    ahead = run(['git', 'diff', '--name-only', 'origin/main..HEAD'], cwd=website).splitlines()
    if any(not (p.startswith('gallery/') or p == 'data/gallery-sync.json') for p in ahead):
        raise ValueError('Unpublished commits contain unrelated changes; automatic publication deferred')
    run(['git', 'add', '--', *paths], cwd=website)
    changed = run(['git', 'diff', '--cached', '--name-only', '--', *paths], cwd=website)
    if changed:
        run(['git', 'commit', '--only', '-m', 'Sync projection gallery from verified local renders', '--', *paths], cwd=website)
    run(['git', 'push', 'origin', 'HEAD:main'], cwd=website)


def verify_live(base, report, timeout=480):
    deadline = time.monotonic() + timeout
    last = 'deployment pending'
    while time.monotonic() < deadline:
        try:
            stamp = '?v=' + report['source_signature'][:16]
            with urlopen(base.rstrip('/') + '/data/gallery-sync.json' + stamp, timeout=30) as r:
                live = json.load(r)
            if live.get('source_signature') != report['source_signature']:
                raise ValueError('Previous deployment is still served')
            with urlopen(base.rstrip('/') + '/gallery/gallery.json' + stamp, timeout=30) as r:
                content = r.read()
            if hashlib.sha256(content).hexdigest() != report['files']['gallery.json']:
                raise ValueError('Live gallery manifest does not match publication')
            return True
        except Exception as exc:
            last = str(exc)
            time.sleep(10)
    raise RuntimeError('Live verification timed out: ' + last)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--website', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--gpu', type=int, default=1)
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--quiet-seconds', type=int, default=60)
    p.add_argument('--push', action='store_true')
    p.add_argument('--verify-live', help='Base URL whose deployment must match after publication')
    a = p.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    with (a.work / 'publish.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report, changed = build(a.source, a.website, a.work, a.gpu, a.jobs, a.quiet_seconds)
        if a.push:
            publish(a.website)
        if a.verify_live:
            verify_live(a.verify_live, report)
        dump(a.work / 'status.json', {'checked_at': datetime.now(timezone.utc).isoformat(),
             'source_gallery_sha256': report['source_gallery_sha256'],
             'pushed': a.push, 'live_verified': bool(a.verify_live), 'changed': changed})
        print(json.dumps({'changed': changed, 'clips': report['clips'], 'projects': report['projects'],
                          'bytes': report['bytes'], 'source_gallery_sha256': report['source_gallery_sha256']}))


if __name__ == '__main__':
    main()
