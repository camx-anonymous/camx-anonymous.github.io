#!/usr/bin/env python3
"""Raw companion of every example clip: the same episode, camera views, tile order, frame sampling and frame size as
``overlays/videos/<key>__<slug>.mp4``, with nothing drawn on it. The dataset cards of the main page show the raw poster,
and the comparison viewer plays the raw clip next to the overlay clip, so the two must line up frame for frame.

Everything is read back from the overlay clip itself (size, frame count, frame rate) and from ``data/datasets.json``
(dataset, episode, views); the frames come from the dataset's own videos (LeRobot-v3: one packed file per camera, the
episode's start time in meta/episodes). Each view is scaled to a common height, the views are stacked left to right in
the overlay clip's order and the strip is scaled to the overlay clip's size.

Writes ``overlays/raw/<key>__<slug>.mp4`` and ``overlays/raw/<key>__<slug>.jpg`` (poster, mid-clip frame).

Usage:
  uv run --with pyarrow python tools/raw_clips.py [--only KEY] [--force] [--jobs 8]
Env:
  CAMX_ROOT  camx_480p tree (default /data/camx_480p)
"""
import argparse, glob, hashlib, json, os, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from overlay_sources import dataset_root

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ROOT = os.environ.get('CAMX_ROOT', '/data/camx_480p')
VIDEOS, RAW = os.path.join(REPO, 'overlays', 'videos'), os.path.join(REPO, 'overlays', 'raw')


def probe(mp4):
    """(width, height, frame rate as a Fraction, frame count) of a clip."""
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries',
                          'stream=width,height,r_frame_rate,nb_read_frames', '-of', 'json', mp4], capture_output=True, text=True, check=True).stdout
    s = json.loads(out)['streams'][0]
    return int(s['width']), int(s['height']), Fraction(s['r_frame_rate']), int(s['nb_read_frames'])


def episode_videos(dataset, ep, keys):
    """{video key: (packed file, start time of the episode in it)} from meta/episodes."""
    import pyarrow.parquet as pq
    root = dataset_root(ROOT, dataset); info = json.load(open(os.path.join(root, 'meta', 'info.json')))
    for f in sorted(glob.glob(os.path.join(root, 'meta', 'episodes', '**', '*.parquet'), recursive=True)):
        cols = ['episode_index'] + [f'videos/{k}/{c}' for k in keys for c in ('chunk_index', 'file_index', 'from_timestamp')]
        for r in pq.read_table(f, columns=cols).to_pylist():
            if int(r['episode_index']) != ep: continue
            return info, {k: (os.path.join(root, info['video_path'].format(video_key=k, chunk_index=r[f'videos/{k}/chunk_index'],
                                                                           file_index=r[f'videos/{k}/file_index'])),
                              float(r[f'videos/{k}/from_timestamp'])) for k in keys}
    raise SystemExit(f'{dataset}: episode {ep} not in meta/episodes')


def input_signature(o, overlay, info, videos):
    """A raw companion is current only for the same source files and sampling.

    Dataset backfills can replace packed video files without changing the
    published overlay or the dataset's _SUCCESS export marker.
    """
    def stat(path):
        st = os.stat(path)
        return [os.path.realpath(path), st.st_size, st.st_mtime_ns]
    payload = {'schema': 1, 'dataset': o['dataset'], 'episode': int(o['episode']),
               'views': o['views'], 'fps': info['fps'],
               'shapes': {k: info['features'][k]['shape'] for k in videos},
               'overlay': stat(overlay),
               'videos': {k: [stat(path), start] for k, (path, start) in videos.items()},
               'tool_sha256': hashlib.sha256(open(__file__, 'rb').read()).hexdigest()}
    return {'fingerprint': hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(), **payload}


def output_signatures(video, poster):
    result = {}
    for name, path in [('video', video), ('poster', poster)]:
        st = os.stat(path)
        if not os.path.isfile(path) or st.st_size == 0:
            raise ValueError(f'Missing or empty raw output: {path}')
        result[name] = [os.path.realpath(path), st.st_size, st.st_mtime_ns]
    return result


def raw_one(o, force=False):
    name = f"{o['key']}__{o['slug']}"; src = os.path.join(VIDEOS, name + '.mp4'); dst = os.path.join(RAW, name + '.mp4')
    if not os.path.isfile(src): return f'{name}: no overlay clip, skipped'
    keys = [f'observation.image.{v}' for v in o['views']]
    info, vids = episode_videos(o['dataset'], int(o['episode']), keys)
    signature = input_signature(o, src, info, vids)
    sidecar = os.path.join(RAW, name + '.json')
    jpg = os.path.join(RAW, name + '.jpg')
    if os.path.isfile(dst) and not force:
        try:
            cached = json.load(open(sidecar))
            if (cached.get('fingerprint') == signature['fingerprint']
                    and cached.get('outputs') == output_signatures(dst, jpg)): return None
        except (OSError, ValueError): pass
    # A failed forced refresh must not leave an old receipt blessing a partial
    # output. Stage both files and write their receipt only after validation.
    try: os.unlink(sidecar)
    except FileNotFoundError: pass
    W, H, rate, n = probe(src)
    fps = Fraction(info['fps']).limit_denominator(100000); step = max(1, round(fps / rate))   # every step-th frame, like the overlay
    shapes = [info['features'][k]['shape'] for k in keys]; hc = max(int(s[0]) for s in shapes)
    cmd = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y']
    for k in keys:   # half a frame early: the first decoded frame is the episode's first, whatever the rounding of its timestamp
        cmd += ['-ss', f'{max(0.0, vids[k][1] - 0.5 / float(fps)):.6f}', '-i', vids[k][0]]
    tiles = ''.join(f"[{i}:v]select='not(mod(n\\,{step}))',scale=-2:{hc},setsar=1[v{i}];" for i in range(len(keys)))
    stack = ''.join(f'[v{i}]' for i in range(len(keys))) + (f'hstack=inputs={len(keys)},' if len(keys) > 1 else 'null,')
    # setsar after the final scale: it would otherwise keep the strip's display aspect and the clip would show 1-4 px wider than the overlay
    cmd += ['-filter_complex', f'{tiles}{stack}scale={W}:{H},setsar=1,setpts=N/({rate.numerator}/{rate.denominator})/TB[o]', '-map', '[o]',
            '-frames:v', str(n), '-r', f'{rate.numerator}/{rate.denominator}', '-c:v', 'libx264', '-preset', 'slow', '-crf', '28',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an']
    # the strip before the final scale: a different aspect than the overlay clip means the tiles do not line up
    strip = sum(int(s[1]) * hc / int(s[0]) for s in shapes) / hc
    note = '' if abs(strip / (W / H) - 1) < 0.02 else f'  <-- tile layout differs (strip {strip:.3f} vs clip {W / H:.3f})'
    with tempfile.TemporaryDirectory(prefix='.raw-', dir=RAW) as staging:
        staged_mp4, staged_jpg = os.path.join(staging, 'clip.mp4'), os.path.join(staging, 'poster.jpg')
        r = subprocess.run(cmd + [staged_mp4], capture_output=True, text=True)
        if r.returncode != 0: return f'{name}: ffmpeg failed: {r.stderr.strip()[-300:]}'
        _, _, rate2, n2 = probe(staged_mp4)
        note += '' if n2 == n else f'  <-- {n2} frames, the overlay clip has {n}'
        note += '' if rate2 == rate else f'  <-- frame rate {rate2}, the overlay clip has {rate}'
        if note: return f'{name}: raw export rejected{note}'
        subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{n2 / float(rate2) / 2:.3f}', '-i', staged_mp4, '-frames:v', '1',
                        '-vf', 'scale=-2:180', '-q:v', '6', staged_jpg], check=True)
        output_signatures(staged_mp4, staged_jpg)
        latest_info, latest_vids = episode_videos(o['dataset'], int(o['episode']), keys)
        if input_signature(o, src, latest_info, latest_vids)['fingerprint'] != signature['fingerprint']:
            return f'{name}: failed: source changed during raw export; rerun this clip'
        os.replace(staged_mp4, dst); os.replace(staged_jpg, jpg)
        signature['outputs'] = output_signatures(dst, jpg)
        staged_sidecar = os.path.join(staging, 'receipt.json')
        with open(staged_sidecar, 'w') as f: json.dump(signature, f, indent=1)
        os.replace(staged_sidecar, sidecar)
    return f'{name}: {n2} frames, {len(keys)} view(s), every {step}. frame, {os.path.getsize(dst) // 1024} KB{note}'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--only', default=None, help='project key or slug substring (comma-separated alternatives)')
    ap.add_argument('--force', action='store_true', help='redo clips whose raw companion is newer than the overlay clip')
    ap.add_argument('--jobs', type=int, default=8)
    a = ap.parse_args()
    site = json.load(open(os.path.join(REPO, 'data', 'datasets.json')))
    ovs = [o for p in site['projects'] for o in p['overlays']]
    if a.only:
        alts = [x.strip() for x in a.only.split(',') if x.strip()]
        ovs = [o for o in ovs if any(x in f"{o['key']}__{o['slug']}" for x in alts)]
    os.makedirs(RAW, exist_ok=True)
    with ThreadPoolExecutor(a.jobs) as ex:
        res = [m for m in ex.map(lambda o: raw_one(o, a.force), ovs) if m]
    for m in res: print(m)
    print(f'{len(ovs)} clips, {len(res)} written or reported', file=sys.stderr)
    if any('<--' in m or 'failed' in m for m in res): sys.exit(1)


if __name__ == '__main__':
    main()
