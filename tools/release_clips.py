#!/usr/bin/env python3
"""Website example clips from a release-renderer output tree, with frame-matched raw companions.

The release renderer (camx_visualization/reproject.py --tree <samples> --out <render>) writes
``<render>/<family>/<project>/<dataset>/ep<N>/{stitched.mp4, <view>.mp4 ..., poster.png, meta.json, stitched.rerun.json}``.
This tool turns that tree plus the sample tree it was rendered from into the site's two-pane clips:

  videos/<key>__<slug>.mp4    the overlay pane: normalized to --height 480, --fps 10, --seconds 45 by default
  raw/<key>__<slug>.mp4       the raw pane: the same frames cut from the sample dataset's own videos, nothing drawn on
                              them -- same views in the same order, the renderer's per-tile widths and tile height
                              (renderer_summary.tile_w / tile_h; agibot_beta: 640 per view; the stitched width split
                              evenly otherwise), the same frame subsampling (meta.json clip.stride over clip.source_frames
                              source frames, seeking half a frame early as reproject.cut_raw) and the overlay pane's own
                              timebase before both panes receive identical final frame sampling and tile scaling;
                              ffprobe must report identical width, height, frame count and r_frame_rate
  posters/<key>__<slug>.jpg   the raw strip's middle frame
  records/<key>__<slug>.json  the clip record ``attach`` puts into data/datasets.json, plus encode facts

key = family_project (the project key with / -> _), slug = <dataset>__ep<N>. A ``raw`` route render (meta.json route
"raw": the release gives nothing to project a gripper through) is already the raw strip: only the raw pane is written and
the record says ``mode: "raw"`` with the renderer's reason in ``no_overlay``, as tools/raw_only_clips.py did.
Compression is per project: --cq-map is a JSON object {"family/project": cq, ...} (36 or 42 today); a project missing
from it is an error unless --default-cq is given. Encoder: h264_nvenc -preset p5 -cq <cq>; workers wait for an NVENC
slot (at most --nvenc-slots concurrent sessions). An encoder failure fails the clip; there is no CPU codec fallback.
``render_fingerprint`` hashes meta.json, stitched.rerun.json and the versioned output contract and versions the
media URLs on the site. The record fields come from the renderer's meta.json (route, views, clip budget, recipe:
overlay_mode / standin / own_only / calibration_warning -> review_note; renderer_summary: sides -> gripper profiles,
tile_w / tile_h, overlay_scope, calibration, source_export_id) and the sample's info.json / meta/episodes row (gripper
model or per-episode variant, fisheye flags, camx_export.export_id, the task string; attach re-reads the captions).

Usage:
  release_clips.py encode --render <render_root> --samples <samples_tree> --cq-map <json> --out <clips_out>
                          --codec-lib <renderer>/lib [--height 480] [--fps 10] [--seconds 45]
                          [--only SUBSTR[,SUBSTR]] [--jobs 4] [--nvenc-slots 4] [--default-cq N] [--force]
  release_clips.py plan   --records <clips_out>/records --out <plan.json> [--tag-prefix <unique-version>] [--max-assets 900]
                          [--repo camx-anonymous/camx-anonymous.github.io]
  release_clips.py attach --records <clips_out>/records --datasets data/datasets.json --out data/datasets.json
                          [--plan <plan.json>] [--root /data/camx_480p] [--overlay-base ../overlays/videos/]
                          [--raw-base ../overlays/raw/] [--poster-base ../overlays/posters/]

``plan`` assigns the mp4s to GitHub Release assets of the site repo, split over tags like the sample archives
(samples-v1-<family>, samples-v1-<family>-2, ...): clips in sorted name order, grouped by family, tags
<prefix>-<family>, <prefix>-<family>-2, ... with at most --max-assets assets each (an overlay pane and its raw pane always
share a tag; a raw-only clip is one asset). Asset names: <name>.mp4 (overlay) and raw__<name>.mp4 (raw). Writes
<plan.json> = {clip name: {tag, overlay_asset, raw_asset, overlay_url, raw_url}} with
https://github.com/<repo>/releases/download/<tag>/<asset> URLs, and <plan.json>.upload.sh, the idempotent gh script the
user runs (create missing releases, upload missing assets in batches of 50 with --clobber, verify every asset is listed).
``attach`` replaces projects[].overlays of every project that has records (projects without records are untouched),
re-reads the clip captions from --root (build_site_data.captions_pass), runs the standard tail passes of
tools/build_site_data.py, writes overlay_base / raw_base / poster_base (the page reads the raw mp4, the poster jpg and the
overlay mp4 from three independent bases, so the mp4s can live outside the Pages repo) and, with --plan, each record's
overlay_url / raw_url (the page prefers them over the bases; the bases stay as the fallback), and updates totals.overlays.
Needs pyarrow for episode metadata and caption tracks.
Encoding requires CAMX_GPU_CODECS=nvidia and CAMX_GPU_UUID; the renderer broker supplies NVDEC, GPU admission and
NVENC. A matching final-quality NVENC/p5/CQ receipt permits stream-copy only when the source already meets the output
contract. Container counts avoid CPU decode scans; newly written panes receive a brokered GPU decode check.
"""
import argparse
import datetime
import glob
import hashlib
import importlib.util
import json
import math
import multiprocessing
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

DEFAULT_ROOT = os.environ.get('CAMX_ROOT', '/data/camx_480p')
FF = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y']
RECEIPT = 'stitched.rerun.json'
SITE_FIELDS = ('key', 'slug', 'dataset', 'episode', 'task', 'views', 'grippers', 'mode', 'fisheye', 'accept', 'export_id',
               'rendered_from', 'seconds', 'bytes', 'render_fingerprint', 'render_built', 'no_overlay', 'standin', 'standin_note',
               'own_only', 'overlay_label', 'overlay_scope', 'calibration', 'review_note', 'tile_w', 'tile_h')

_NVENC = None   # the NVENC session semaphore of this worker (set by _init)
_CODECS = None
_CODEC_ENV = None
OUTPUT_VERSION = 2


def log(msg):
    print(f'{datetime.datetime.now():%H:%M:%S} {msg}', flush=True)


def key_of(project):
    return project.replace('/', '_')


def probe(mp4):
    """Read container facts only; never silently decode an entire video on the CPU."""
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                          'stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,duration,start_time,codec_name', '-of', 'json', mp4],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)['streams'][0]
    frames = int(s.get('nb_frames') or 0)
    if frames < 1:
        raise ValueError(f'container frame count unavailable: {mp4}')
    return {'width': int(s['width']), 'height': int(s['height']), 'nb_frames': frames, 'frames': frames,
            'rate': s['r_frame_rate'], 'avg_rate': s.get('avg_frame_rate', s['r_frame_rate']),
            'duration': float(s['duration']), 'start': float(s.get('start_time', 0)), 'codec': s['codec_name']}


def ff(*args, route=True):
    try:
        if _CODECS is not None:
            r = _CODECS.run([*FF, *args], env=_CODEC_ENV, route=route, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        else:
            raise RuntimeError('GPU broker is not configured; pass --codec-lib with NVIDIA environment settings')
    except subprocess.CalledProcessError as exc:
        raise RuntimeError((exc.stderr or '').strip()[-400:] or f'ffmpeg rc={exc.returncode}') from exc
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-400:] or f'ffmpeg rc={r.returncode}')
    return r.stdout


def verify_decoded_frames(path, expected):
    progress = ff('-xerror', '-progress', 'pipe:1', '-i', path, '-map', '0:v:0', '-an', '-vsync', '0', '-f', 'null', '-')
    counts = [int(line.split('=', 1)[1]) for line in progress.splitlines() if line.startswith('frame=')]
    if not counts or counts[-1] != expected or 'progress=end' not in progress.splitlines():
        raise RuntimeError(f'full GPU decode frame count {counts[-1] if counts else None} != {expected}: {path}')
    return counts[-1]


def encoder_args(encoder, cq):
    if encoder != 'h264_nvenc':
        raise ValueError(f'unsupported encoder: {encoder}; NVENC is required')
    return ['-c:v', 'h264_nvenc', '-gpu', '0', '-preset', 'p5', '-rc', 'vbr', '-cq', str(cq), '-b:v', '0',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an']


# ── the render tree ──────────────────────────────────────────────────────────────────────────────────────────────────
def find_renders(render_root):
    """[(project, dataset, episode, ep_dir)] of every <family>/<project>/<dataset>/ep<N>/meta.json."""
    out = []
    for m in sorted(glob.glob(os.path.join(render_root, '*', '*', '*', 'ep*', 'meta.json'))):
        d = os.path.dirname(m)
        family, project, dataset, ep = d.split(os.sep)[-4:]
        if not ep[2:].isdigit():
            continue
        out.append((f'{family}/{project}', dataset, int(ep[2:]), d))
    return out


def output_contract(height=480, fps=10, seconds=45):
    if not isinstance(height, int) or height < 2 or height % 2:
        raise ValueError('--height must be a positive even integer')
    if not math.isfinite(float(fps)) or fps <= 0 or not math.isfinite(float(seconds)) or seconds <= 0:
        raise ValueError('--fps and --seconds must be finite and positive')
    if Fraction(str(fps)) * Fraction(str(seconds)) < 1:
        raise ValueError('--fps * --seconds must allow at least one complete output frame')
    return {'version': OUTPUT_VERSION, 'height': height, 'fps': str(Fraction(str(fps))), 'seconds': float(seconds),
            'sampling': 'renderer-index-fps-near-v1'}


def fingerprint(ep_dir, contract=None):
    with open(os.path.join(ep_dir, 'meta.json'), 'rb') as src:
        h = hashlib.sha256(src.read())
    receipt = os.path.join(ep_dir, RECEIPT)
    if os.path.isfile(receipt):
        with open(receipt, 'rb') as src:
            h.update(src.read())
    h.update(json.dumps(contract or output_contract(), sort_keys=True).encode())
    return h.hexdigest()[:16]


def output_layout(widths, source_height, contract):
    """Keep renderer widths exactly at native height; scale each recorded tile otherwise."""
    height = contract['height']
    scaled = list(widths) if height == source_height else [max(2, 2 * round(w * height / source_height / 2)) for w in widths]
    if sum(scaled) % 2:
        raise ValueError('stitched output width must be even for H.264 yuv420p')
    return scaled, height


def output_frames(source, contract):
    fps = Fraction(contract['fps'])
    frames = min(math.floor(Fraction(str(contract['seconds'])) * fps),
                 math.floor(source['frames'] * fps / Fraction(source['rate'])))
    if frames < 1:
        raise ValueError('source is shorter than one complete output frame')
    return frames


def final_sampling(source_rate, contract, frames):
    """The identical timestamp and fps filter used by both panes after renderer stride selection."""
    fps = contract['fps']
    return (f'settb=expr=1/({source_rate}),setpts=N,fps=fps={fps}:start_time=0:round=near:eof_action=pass,'
            f'trim=end_frame={frames},setpts=N/({fps}*TB)')


def conforms(media, contract, widths, frames):
    fps = Fraction(contract['fps'])
    return (media['codec'] == 'h264' and media['width'] == sum(widths) and media['height'] == contract['height']
            and media['frames'] == frames and media['nb_frames'] == frames
            and Fraction(media['rate']) == fps and Fraction(media['avg_rate']) == fps
            and abs(media['start']) <= 1e-6
            and 0 < media['duration'] <= contract['seconds'] + 1e-6
            and abs(media['duration'] - frames / float(fps)) <= 1e-4)


def copy_eligible(meta, source, contract, widths, frames, cq):
    receipt = meta.get('stitched_encode') or {}
    return (receipt.get('encoder') == 'h264_nvenc' and receipt.get('preset') == 'p5'
            and receipt.get('cq') == cq and cq in (36, 42) and receipt.get('final_quality') is True
            and conforms(source, contract, widths, frames))


def cached_record(paths, fp, cq, contract, widths, frames, raw_only):
    try:
        with open(paths['record']) as src:
            old = json.load(src)
        if (old.get('render_fingerprint') != fp or old.get('cq') != cq or old.get('encoder') != 'h264_nvenc'
                or old.get('output_contract') != contract or old.get('tile_w') != widths
                or old.get('tile_h') != contract['height'] or old.get('width') != sum(widths)
                or old.get('height') != contract['height'] or old.get('frames') != frames
                or old.get('fps') != round(float(Fraction(contract['fps'])), 4) or not os.path.isfile(paths['poster'])):
            return None
        for pane in ('raw',) if raw_only else ('raw', 'video'):
            if old.get('decoded_frames', {}).get(pane) != frames:
                return None
            if not conforms(probe(paths[pane]), contract, widths, frames):
                return None
        return old
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        return None


def overlay_filter(source, source_widths, widths, height, contract, frames):
    temporal = final_sampling(source['rate'], contract, frames)
    if source['height'] == height and source_widths == widths:
        return f'[0:v]{temporal},setsar=1[o]'
    count = len(widths)
    filters = [f'[0:v]{temporal},split={count}' + ''.join(f'[s{i}]' for i in range(count))]
    x = 0
    for i, (before, after) in enumerate(zip(source_widths, widths)):
        filters.append(f'[s{i}]crop={before}:{source["height"]}:{x}:0:exact=1,scale={after}:{height},setsar=1[v{i}]')
        x += before
    filters.append(''.join(f'[v{i}]' for i in range(count)) + (f'hstack=inputs={count}[o]' if count > 1 else 'null[o]'))
    return ';'.join(filters)


def sample_root(samples, meta):
    d = os.path.join(samples, meta['dataset'])
    if os.path.isfile(os.path.join(d, 'meta', 'info.json')):
        return d
    alt = meta.get('dataset_root')
    if alt and os.path.isfile(os.path.join(alt, 'meta', 'info.json')):
        return alt
    raise FileNotFoundError(f'sample dataset not under --samples: {d}')


def episode_row(root, ep):
    import pyarrow.parquet as pq
    for f in sorted(glob.glob(os.path.join(root, 'meta', 'episodes', '**', '*.parquet'), recursive=True)):
        for r in pq.read_table(f).to_pylist():
            if int(r['episode_index']) == ep:
                return r
    raise LookupError(f'episode {ep} not in {root}/meta/episodes')


def tile_layout(meta, stitched):
    """(tile widths, tile height) of the overlay strip: the renderer's table, else agibot's 640 per view, else an even split."""
    views = meta['views']
    rs = meta.get('renderer_summary') or {}
    tile_w = rs.get('tile_w') or ([640] * len(views) if meta.get('route') == 'agibot_beta' else None)
    if not tile_w:
        if stitched['width'] % len(views):
            raise ValueError(f"stitched width {stitched['width']} does not split into {len(views)} equal tiles and the renderer wrote no tile table")
        tile_w = [stitched['width'] // len(views)] * len(views)
    tile_h = int(rs.get('tile_h') or stitched['height'])
    if len(tile_w) != len(views) or sum(tile_w) != stitched['width'] or tile_h != stitched['height']:
        raise ValueError(f"tile table {tile_w} x {tile_h} does not match the stitched {stitched['width']}x{stitched['height']} for views {views}")
    return [int(w) for w in tile_w], tile_h


def view_fisheye(info, view):
    base = view[:-4] if view.endswith('_rgb') else view
    for cand in (base, base.rsplit('_', 1)[0] if base.endswith(('_left', '_right')) else None):
        if cand and f'{cand}_is_fisheye' in info:
            return bool(info[f'{cand}_is_fisheye'])
    return False


def record_of(project, dataset, ep, meta, info, row, root, fp, frames, rate, size, raw_size, encoder, cq, width, height, tile_w, tile_h, ep_dir):
    recipe = meta.get('recipe') or {}
    rs = meta.get('renderer_summary') or {}
    route = meta.get('route')
    mode = 'raw' if route == 'raw' else (recipe.get('overlay_mode') or 'urdf')
    sides = list((rs.get('sides') or {}).keys()) or [s for s in ('right', 'left') if info.get(f'{s}_gripper_model')]
    grippers = {}
    for s in sides:
        model = row.get(f'{s}_gripper_variant') or info.get(f'{s}_gripper_model') or (rs.get('sides') or {}).get(s)
        if model:
            grippers[s] = {'model': model, 'profile': (rs.get('sides') or {}).get(s) or ('none' if mode == 'raw' else recipe.get('profile_resolved')),
                           'urdf': mode == 'urdf'}
    tasks = row.get('tasks') or []
    if isinstance(tasks, str):
        try:
            tasks = json.loads(tasks)
        except ValueError:
            tasks = [tasks]
    if not isinstance(tasks, list):
        tasks = [tasks]
    success = os.path.join(root, 'meta', '_SUCCESS')
    rendered_from = (datetime.datetime.fromtimestamp(os.path.getmtime(success)).astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')
                     if os.path.isfile(success) else None)
    out_fps = float(Fraction(rate))
    rec = {'key': key_of(project), 'slug': f'{dataset}__ep{ep}', 'dataset': meta['dataset'], 'episode': ep,
           'task': str((tasks or [''])[0] or ''), 'views': list(meta['views']), 'grippers': grippers, 'mode': mode,
           'fisheye': route == 'bimanual_fisheye' or any(view_fisheye(info, v) for v in meta['views']),
           'accept': recipe.get('accept') or 'unmeasured',
           'export_id': rs.get('source_export_id') or (info.get('camx_export') or {}).get('export_id'),
           'rendered_from': rendered_from, 'seconds': round(frames / out_fps, 1), 'bytes': size, 'raw_bytes': raw_size,
           'render_fingerprint': fp, 'render_built': meta.get('timestamp')}
    if mode == 'raw':
        rec['no_overlay'] = meta.get('no_overlay') or recipe.get('no_overlay') or 'recipe route raw'
    standin = recipe.get('standin')
    if isinstance(standin, dict) and standin.get('profile'):
        rec['standin'] = [standin['profile']]
        if standin.get('note'):
            rec['standin_note'] = standin['note']
    if recipe.get('own_only'):
        rec['own_only'] = True
    for field in ('overlay_label', 'overlay_scope', 'calibration', 'review_note'):
        value = rs.get(field, recipe.get(field))
        if value not in (None, '', [], {}):
            rec[field] = value
    if 'calibration' not in rec and recipe.get('calibration_warning'):
        rec['review_note'] = rec.get('review_note') or recipe['calibration_warning']
    rec.update({'project': project, 'route': route, 'encoder': encoder, 'cq': cq, 'width': width, 'height': height, 'frames': frames,
                'fps': round(out_fps, 4), 'tile_w': tile_w, 'tile_h': tile_h, 'render_dir': ep_dir,
                'encoded': datetime.datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')})
    return rec


# ── one clip ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _init(sem):
    global _NVENC
    _NVENC = sem


def configure_codecs(path):
    """Load the renderer's host-wide broker and fail closed unless NVIDIA mode is configured."""
    global _CODECS, _CODEC_ENV
    if not path:
        raise ValueError('--codec-lib (or CAMX_CODEC_LIB) must name the renderer lib directory or gpu_codecs.py')
    filename = os.path.join(path, 'gpu_codecs.py') if os.path.isdir(path) else path
    spec = importlib.util.spec_from_file_location('_release_gpu_codecs', filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    env = module.environment()
    if module.config(env) is None:
        raise ValueError('release encoding requires CAMX_GPU_CODECS=nvidia and CAMX_GPU_UUID; no CPU fallback')
    _CODECS, _CODEC_ENV = module, env


def encode_with(dst, encoders, cq, *inputs_and_filters):
    """Run the required NVENC encoder; errors never select a software encoder."""
    errors = []
    for enc in encoders:
        try:
            ff(*inputs_and_filters, *encoder_args(enc, cq), dst)
            return enc, errors
        except RuntimeError as e:
            errors.append(f'{enc}: {e}')
            try:
                os.unlink(dst)
            except FileNotFoundError:
                pass
    raise RuntimeError('; '.join(errors))


def cut_raw_pane(root, info, row, views, tile_w, tile_h, stride, n_src, rate, dst, encoders, cq, contract, frames):
    """The raw strip: every view's frames 0, stride, 2*stride ... below n_src, scaled to its tile, stacked left to right."""
    fps = float(info['fps'])
    half = 0.5 / fps        # seek half a frame early, as the renderers' reader and reproject.cut_raw: packed timestamps can sit just after the frame PTS
    args, filters = [], []
    for i, v in enumerate(views):
        key = f'observation.image.{v}'
        src = os.path.join(root, info['video_path'].format(video_key=key, chunk_index=int(row[f'videos/{key}/chunk_index']),
                                                            file_index=int(row[f'videos/{key}/file_index'])))
        if not os.path.isfile(src):
            raise FileNotFoundError(f'{v}: {src}')
        t0 = float(row[f'videos/{key}/from_timestamp'])
        args += ['-ss', f'{max(0.0, t0 - half):.6f}', '-i', src]
        filters.append(f'[{i}:v]trim=end_frame={n_src},select=not(mod(n\\,{stride})),{final_sampling(rate, contract, frames)},'
                       f'scale={tile_w[i]}:{tile_h},setsar=1[v{i}]')
    stack = ''.join(f'[v{i}]' for i in range(len(views))) + (f'hstack=inputs={len(views)}[o]' if len(views) > 1 else 'null[o]')
    fc = ';'.join(filters + [stack])
    return encode_with(dst, encoders, cq, *args, '-filter_complex', fc, '-map', '[o]', '-frames:v', str(frames), '-r', contract['fps'])


def encode_one(job):
    """One render directory -> overlay pane, raw pane, poster, record. Returns a status dict (never raises)."""
    project, dataset, ep, ep_dir, samples, out, cq, force = (job[k] for k in ('project', 'dataset', 'ep', 'ep_dir', 'samples', 'out', 'cq', 'force'))
    name = f'{key_of(project)}__{dataset}__ep{ep}'
    paths = {k: os.path.join(out, d, name + ext) for k, d, ext in
             (('video', 'videos', '.mp4'), ('raw', 'raw', '.mp4'), ('poster', 'posters', '.jpg'), ('record', 'records', '.json'))}
    t0 = time.time()
    held = False
    try:
        with open(os.path.join(ep_dir, 'meta.json')) as src:
            meta = json.load(src)
        if meta.get('error'):
            return {'name': name, 'status': 'render-error', 'error': meta['error']}
        route = meta.get('route')
        raw_only = route == 'raw'
        contract = job.get('contract') or output_contract()
        fp = fingerprint(ep_dir, contract)
        stitched = os.path.join(ep_dir, 'stitched.mp4')
        if not os.path.isfile(stitched):
            raise FileNotFoundError('no stitched.mp4')
        src_probe = probe(stitched)
        source_widths, source_height = tile_layout(meta, src_probe)
        tile_w, tile_h = output_layout(source_widths, source_height, contract)
        target_frames = output_frames(src_probe, contract)
        if not force and os.path.isfile(paths['record']):
            old = cached_record(paths, fp, cq, contract, tile_w, target_frames, raw_only)
            if old is not None:
                return {'name': name, 'status': 'current', 'record': old}
        root = sample_root(samples, meta)
        with open(os.path.join(root, 'meta', 'info.json')) as src:
            info = json.load(src)
        row = episode_row(root, ep)
        clip = meta.get('clip') or {}
        stride = int(clip.get('stride') or 1)
        n_src = int(clip.get('source_frames') or 0)
        if n_src < 1 or stride < 1:
            raise ValueError('meta.json clip.source_frames and stride must be positive')
        if src_probe['frames'] != math.ceil(n_src / stride):
            raise ValueError(f"renderer strip has {src_probe['frames']} frames; metadata gives {math.ceil(n_src / stride)}")
        if Fraction(src_probe['rate']) != Fraction(src_probe['avg_rate']):
            raise ValueError('renderer strip must have a constant frame rate')
        held = _NVENC is not None and _NVENC.acquire()
        encoders = ('h264_nvenc',)
        notes = []
        for p in paths.values():
            os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = {k: os.path.join(os.path.dirname(v), name + '.tmp' + os.path.splitext(v)[1]) for k, v in paths.items()}
        copied = copy_eligible(meta, src_probe, contract, tile_w, target_frames, cq)
        pane = 'raw' if raw_only else 'video'
        if copied:
            ff('-i', stitched, '-map', '0:v:0', '-c:v', 'copy', '-an', '-movflags', '+faststart', tmp[pane], route=False)
            encoder = 'h264_nvenc'
        else:
            fc = overlay_filter(src_probe, source_widths, tile_w, tile_h, contract, target_frames)
            encoder, errs = encode_with(tmp[pane], encoders, cq, '-i', stitched, '-filter_complex', fc, '-map', '[o]',
                                       '-frames:v', str(target_frames), '-r', contract['fps'])
            notes += errs
        ov_probe = probe(tmp[pane])
        if not conforms(ov_probe, contract, tile_w, target_frames):
            raise RuntimeError(f'{pane} does not satisfy the requested output contract: {ov_probe}')
        if raw_only:
            raw_probe, size = ov_probe, 0
        else:
            _, errs = cut_raw_pane(root, info, row, meta['views'], tile_w, tile_h, stride, n_src, src_probe['rate'], tmp['raw'],
                                  encoders, cq, contract, target_frames)
            notes += errs
            raw_probe = probe(tmp['raw'])
            if not conforms(raw_probe, contract, tile_w, target_frames):
                raise RuntimeError(f'raw pane does not satisfy the requested output contract: {raw_probe}')
            diff = [k for k in ('width', 'height', 'frames', 'nb_frames') if raw_probe[k] != ov_probe[k]]
            if diff:
                raise RuntimeError('raw/overlay parity: ' + ', '.join(f"{k} {raw_probe[k]} vs {ov_probe[k]}" for k in diff))
            size = os.path.getsize(tmp['video'])
        rate = raw_probe['rate']; frames = raw_probe['frames']
        decoded_frames = {pane: verify_decoded_frames(tmp[pane], frames)
                          for pane in (('raw',) if raw_only else ('raw', 'video'))}
        ff('-ss', f'{frames / float(Fraction(rate)) / 2:.3f}', '-i', tmp['raw'], '-frames:v', '1', '-q:v', '4', tmp['poster'])
        raw_size = os.path.getsize(tmp['raw'])
        rec = record_of(project, dataset, ep, meta, info, row, root, fp, frames, rate, size or raw_size, raw_size, encoder, cq,
                        raw_probe['width'], raw_probe['height'], tile_w, tile_h, ep_dir)
        rec['output_contract'] = contract
        rec['stitched_stream_copy'] = copied
        rec['decoded_frames'] = decoded_frames
        if notes:
            rec['encoder_notes'] = notes
        with open(tmp['record'], 'w') as dst:
            json.dump(rec, dst, indent=1)
        for k in ('raw', 'poster', 'record') + (() if raw_only else ('video',)):
            os.replace(tmp[k], paths[k])
        if raw_only:
            for p in (paths['video'], tmp['video']):
                try:
                    os.unlink(p)
                except FileNotFoundError:
                    pass
        return {'name': name, 'status': 'encoded', 'record': rec, 'seconds': round(time.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001 -- one clip never stops the batch
        for p in glob.glob(os.path.join(out, '*', name + '.tmp.*')):
            try:
                os.unlink(p)
            except OSError:
                pass
        return {'name': name, 'status': 'failed', 'error': f'{type(e).__name__}: {e}'}
    finally:
        if held:
            _NVENC.release()


# ── commands ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def cmd_encode(a):
    if a.jobs < 1 or not 1 <= a.nvenc_slots <= 6:
        sys.exit('--jobs must be positive and --nvenc-slots must be between 1 and 6; reserve capacity for other jobs')
    try:
        contract = output_contract(a.height, a.fps, a.seconds)
        configure_codecs(a.codec_lib)
    except (ValueError, OSError, ImportError) as exc:
        sys.exit(str(exc))
    cq_map = json.load(open(a.cq_map))
    renders = find_renders(a.render)
    if a.only:
        alts = [x.strip() for x in a.only.split(',') if x.strip()]
        renders = [r for r in renders if any(x in f'{key_of(r[0])}__{r[1]}__ep{r[2]}' or x in f'{r[0]}/{r[1]}' for x in alts)]
    if not renders:
        sys.exit(f'no render directories under {a.render}' + (f' matching {a.only}' if a.only else ''))
    missing_cq = sorted({p for p, _, _, _ in renders if p not in cq_map and a.default_cq is None})
    jobs = [{'project': p, 'dataset': ds, 'ep': ep, 'ep_dir': d, 'samples': a.samples, 'out': a.out, 'force': a.force,
             'cq': int(cq_map.get(p, a.default_cq)), 'contract': contract} for p, ds, ep, d in renders if p in cq_map or a.default_cq is not None]
    log(f'{len(jobs)} clips from {a.render} ({len(missing_cq)} projects without a cq), {a.jobs} workers, {a.nvenc_slots} NVENC slots')
    os.makedirs(a.out, exist_ok=True)
    ctx = multiprocessing.get_context('fork')
    sem = ctx.Semaphore(a.nvenc_slots)
    results = []
    with ProcessPoolExecutor(max_workers=a.jobs, mp_context=ctx, initializer=_init, initargs=(sem,)) as ex:
        for r in ex.map(encode_one, jobs):
            results.append(r)
            if r['status'] == 'encoded':
                rec = r['record']
                log(f"{r['name']}: {rec['width']}x{rec['height']}, {rec['frames']} frames @ {rec['fps']:g} fps, "
                    f"overlay {rec['bytes'] // 1024} KB, raw {rec['raw_bytes'] // 1024} KB, {rec['encoder']} cq {rec['cq']}"
                    f"{' (raw only)' if rec['mode'] == 'raw' else ''}, {r['seconds']} s")
            elif r['status'] == 'current':
                log(f"{r['name']}: current (use --force to redo)")
            elif r['status'] == 'failed':
                log(f"{r['name']}: FAILED {r['error']}")
    by = {}
    for r in results:
        by.setdefault(r['status'], []).append(r)
    print(f"\n{len(by.get('encoded', []))} encoded, {len(by.get('current', []))} current, {len(by.get('failed', []))} failed, "
          f"{len(by.get('render-error', []))} renderer errors, {len(missing_cq)} projects without a cq", file=sys.stderr)
    for r in by.get('render-error', []):
        print(f"  renderer error  {r['name']}: {r['error'][:160]}", file=sys.stderr)
    for r in by.get('failed', []):
        print(f"  failed          {r['name']}: {r['error'][:300]}", file=sys.stderr)
    for p in missing_cq:
        print(f'  no cq           {p} (add it to {a.cq_map} or pass --default-cq)', file=sys.stderr)
    if by.get('failed') or by.get('render-error') or missing_cq:
        sys.exit(1)


def load_records(records_dir):
    records = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(records_dir, '*.json')))]
    if not records:
        sys.exit(f'no records under {records_dir}')
    return records


def clip_name(rec):
    return f"{rec['key']}__{rec['slug']}"


def sq(s):
    """s single-quoted for bash."""
    return "'" + str(s).replace("'", "'\\''") + "'"


UPLOAD_SH = r'''#!/usr/bin/env bash
# Upload the website example clips to GitHub Release assets of the site repo. Generated by tools/release_clips.py plan
# from {plan}. Re-runnable: releases that exist are kept, assets a release already lists are skipped
# (FORCE=1 re-uploads them, always with --clobber), nothing else is touched. Needs `gh` logged in as the repo owner.
set -euo pipefail
REPO="{repo}"
VIDEOS_DIR="${{VIDEOS_DIR:-{videos_dir}}}"   # <clips_out>/videos: the overlay panes, asset <name>.mp4
RAW_DIR="${{RAW_DIR:-{raw_dir}}}"            # <clips_out>/raw: the raw panes, asset raw__<name>.mp4
BATCH="${{BATCH:-50}}"
FORCE="${{FORCE:-0}}"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

upload_tag() {{   # $1 tag, $2 title, $3 notes; stdin: "<asset name><TAB><source file>" lines
  local tag="$1" title="$2" notes="$3" have="$WORK/$1.have" todo="$WORK/$1.todo" expected="$WORK/$1.expected" name src
  if ! gh release view "$tag" --repo "$REPO" >/dev/null 2>&1; then
    gh release create "$tag" --repo "$REPO" --title "$title" --notes "$notes" --latest=false
  fi
  gh release view "$tag" --repo "$REPO" --json assets --jq '.assets[].name' | sort > "$have"
  : > "$todo"; : > "$expected"
  while IFS=$'\t' read -r name src; do
    echo "$name" >> "$expected"
    if [ "$FORCE" = 1 ] || ! grep -qxF "$name" "$have"; then
      [ -f "$src" ] || {{ echo "missing source file: $src" >&2; exit 1; }}
      if [ "$(basename "$src")" = "$name" ]; then echo "$src" >> "$todo"
      else mkdir -p "$WORK/$tag"; ln -sfn "$src" "$WORK/$tag/$name"; echo "$WORK/$tag/$name" >> "$todo"; fi   # gh names the asset after the file
    fi
  done
  local n; n=$(wc -l < "$todo")
  echo "== $tag: $(wc -l < "$expected") assets expected, $(wc -l < "$have") present, $n to upload"
  if [ "$n" -gt 0 ]; then xargs -a "$todo" -d '\n' -n "$BATCH" gh release upload "$tag" --repo "$REPO" --clobber; fi
}}

verify_tag() {{   # $1 tag: every expected asset must be listed by the release
  local tag="$1" listing="$WORK/$1.verify" missing
  gh release view "$tag" --repo "$REPO" --json assets --jq '.assets[].name' | sort > "$listing"
  missing=$(sort "$WORK/$1.expected" | comm -23 - "$listing")
  if [ -n "$missing" ]; then echo "!! $tag is missing assets:" >&2; echo "$missing" >&2; return 1; fi
  echo "ok $tag: $(wc -l < "$WORK/$1.expected") assets verified"
}}

{tag_calls}
status=0
{verify_calls}
exit $status
'''


def cmd_plan(a):
    if a.max_assets < 2:
        sys.exit('--max-assets must be at least 2 (an overlay pane and its raw pane share a tag)')
    records = sorted(load_records(a.records), key=clip_name)
    prefix = a.tag_prefix or 'clips-' + hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()[:16]
    by_family = {}
    for r in records:
        by_family.setdefault(r['project'].split('/')[0], []).append(r)
    plan, tags = {}, {}      # tags: tag -> (family, part, [(asset name, source file)])
    for family in sorted(by_family):
        part = used = 0
        for r in by_family[family]:
            name = clip_name(r)
            raw_only = r.get('mode') == 'raw'
            assets = [(f'raw__{name}.mp4', f'$RAW_DIR/{name}.mp4')] + ([] if raw_only else [(f'{name}.mp4', f'$VIDEOS_DIR/{name}.mp4')])
            if part == 0 or used + len(assets) > a.max_assets:
                part += 1; used = 0
            tag = f'{prefix}-{family}' + ('' if part == 1 else f'-{part}')
            tags.setdefault(tag, (family, part, []))[2].extend(assets); used += len(assets)
            url = f'https://github.com/{a.repo}/releases/download/{tag}/'
            entry = {'tag': tag, 'raw_asset': f'raw__{name}.mp4', 'raw_url': url + f'raw__{name}.mp4'}
            if not raw_only:
                entry.update(overlay_asset=f'{name}.mp4', overlay_url=url + f'{name}.mp4')
            plan[name] = entry
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(plan, open(a.out, 'w'), indent=1, sort_keys=True)
    clips_out = os.path.dirname(os.path.abspath(a.records))
    tag_calls, verify_calls = [], []
    for i, (tag, (family, part, assets)) in enumerate(tags.items()):
        title = f'Example clips: {family}' + (f' ({part})' if part > 1 else '')
        notes = (f'Example clips of the `{family}/*` datasets for the dataset browser (https://camx-anonymous.github.io/camx-dataset/): '
                 '`<project>__<dataset>__ep<N>.mp4` is the gripper-projection overlay pane, `raw__<same>.mp4` the same frames with '
                 "nothing drawn on them, as the site's two-pane viewer plays them."
                 + (f' Part {part}: at most {a.max_assets} assets per release.' if part > 1 else ''))
        body = ''.join(f'{n}\t{src}\n' for n, src in assets)     # an unquoted heredoc: $RAW_DIR / $VIDEOS_DIR expand, names are [A-Za-z0-9_.-]
        tag_calls.append(f"upload_tag {sq(tag)} {sq(title)} {sq(notes)} <<EOF_{i}\n{body}EOF_{i}\n")
        verify_calls.append(f'verify_tag {sq(tag)} || status=1')
    script = UPLOAD_SH.format(plan=os.path.abspath(a.out), repo=a.repo, videos_dir=os.path.join(clips_out, 'videos'),
                              raw_dir=os.path.join(clips_out, 'raw'), tag_calls='\n'.join(tag_calls), verify_calls='\n'.join(verify_calls))
    sh = a.out + '.upload.sh'
    open(sh, 'w').write(script); os.chmod(sh, 0o755)
    n_assets = sum(len(v[2]) for v in tags.values())
    print(f'{len(plan)} clips, {n_assets} assets over {len(tags)} tags -> {a.out}; upload script {sh}', file=sys.stderr)
    for tag, (_, _, assets) in tags.items():
        print(f'  {tag:40s} {len(assets):5d} assets', file=sys.stderr)


def cmd_attach(a):
    import build_site_data as S
    records = load_records(a.records)
    plan = json.load(open(a.plan)) if a.plan else None
    by_proj = {}
    for r in records:
        proj = S.PROJECT_MERGE.get(r['project'], r['project'])
        rec = {k: r[k] for k in SITE_FIELDS if k in r and (r[k] is not None or k in ('export_id', 'rendered_from'))}
        rec['dataset'] = S.ID_RENAMES.get(rec['dataset'], rec['dataset'])
        if plan is not None:
            entry = plan.get(clip_name(r))
            if not entry:
                print(f'warning: {clip_name(r)} is not in {a.plan}; the record keeps the base URLs', file=sys.stderr)
            else:
                rec['raw_url'] = entry['raw_url']
                if entry.get('overlay_url') and rec.get('mode') != 'raw':
                    rec['overlay_url'] = entry['overlay_url']
        by_proj.setdefault(proj, []).append(S.scrub(rec))
    out = json.load(open(a.datasets))
    have = {p['key'] for p in out['projects']}
    for proj in sorted(by_proj):
        if proj not in have:
            print(f'warning: {proj}: {len(by_proj[proj])} records but no such project in {a.datasets}; records dropped', file=sys.stderr)
    n = 0
    for p in out['projects']:
        if p['key'] in by_proj:
            merged = {(o['key'], o['slug']): o for o in p.get('overlays', [])}
            merged.update({(o['key'], o['slug']): o for o in by_proj[p['key']]})
            p['overlays'] = sorted(merged.values(), key=lambda o: (o['key'], o['slug']))
            n += len(by_proj[p['key']])
    out = S.captions_pass(out, a.root)
    out = S.same_task_pass(S.sources_pass(S.pending_pass(S.align_paper(S.anonymise(S.merge_projects(out)))), write_bib=False))
    out['overlay_base'], out['raw_base'], out['poster_base'] = a.overlay_base, a.raw_base, a.poster_base
    out['totals']['overlays'] = sum(len(p['overlays']) for p in out['projects'])
    out['clips_updated'] = datetime.datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(out, open(a.out, 'w'), separators=(',', ':'))
    with_captions = sum(1 for p in out['projects'] for o in p['overlays'] if o.get('captions'))
    print(f"{n} clip records attached to {len([k for k in by_proj if k in have])} projects, {out['totals']['overlays']} clips in total, "
          f"{with_captions} with a caption track -> {a.out}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('encode', help='overlay + raw panes, posters and records from a render tree')
    e.add_argument('--render', required=True, help="the renderer's --out: <family>/<project>/<dataset>/ep<N>/")
    e.add_argument('--samples', required=True, help='the sample tree the renderer read: <family>/<project>/<dataset>/{meta,data,videos}')
    e.add_argument('--cq-map', required=True, help='JSON {"family/project": cq, ...}')
    e.add_argument('--out', required=True, help='clip output: videos/ raw/ posters/ records/')
    e.add_argument('--only', default=None, help='substring(s) of <key>__<slug> or family/project/dataset, comma-separated')
    e.add_argument('--jobs', type=int, default=4, help='clips in parallel (default 4)')
    e.add_argument('--nvenc-slots', type=int, default=4, help='concurrent NVENC encodes (1–6); workers wait for capacity (default 4)')
    e.add_argument('--default-cq', type=int, default=None, help='cq for projects missing from --cq-map (an error without it)')
    e.add_argument('--force', action='store_true', help='redo clips whose record matches the render fingerprint and cq')
    e.add_argument('--height', type=int, default=480, help='final tile height, positive and even (default 480)')
    e.add_argument('--fps', type=float, default=10, help='final frame rate (default 10)')
    e.add_argument('--seconds', type=float, default=45, help='maximum duration in seconds (default 45)')
    e.add_argument('--codec-lib', default=os.environ.get('CAMX_CODEC_LIB'),
                   help='renderer lib directory or gpu_codecs.py; requires CAMX_GPU_CODECS=nvidia and CAMX_GPU_UUID')
    p = sub.add_parser('plan', help='assign the mp4s to GitHub Release tags/assets; write plan.json + the upload script')
    p.add_argument('--records', required=True, help='<clips_out>/records (videos/ and raw/ are its siblings)')
    p.add_argument('--out', required=True, help='plan.json; <out>.upload.sh is written beside it')
    p.add_argument('--tag-prefix', help='release tags <prefix>-<family>[-N]; default is a digest of the release records')
    p.add_argument('--max-assets', type=int, default=900, help='assets per release tag (GitHub caps a release at 1,000; default 900)')
    p.add_argument('--repo', default='camx-anonymous/camx-anonymous.github.io')
    t = sub.add_parser('attach', help='put the records into the site data')
    t.add_argument('--records', required=True, help='<clips_out>/records')
    t.add_argument('--datasets', required=True, help='the data/datasets.json to start from')
    t.add_argument('--out', required=True, help='where to write the result (may be the same file)')
    t.add_argument('--plan', default=None, help='plan.json from `plan`: per-record overlay_url / raw_url')
    t.add_argument('--root', default=DEFAULT_ROOT, help=f'camx_480p root for the clip captions (default {DEFAULT_ROOT})')
    t.add_argument('--overlay-base', default='../overlays/videos/')
    t.add_argument('--raw-base', default='../overlays/raw/')
    t.add_argument('--poster-base', default='../overlays/posters/')
    a = ap.parse_args()
    {'encode': cmd_encode, 'plan': cmd_plan, 'attach': cmd_attach}[a.cmd](a)


if __name__ == '__main__':
    main()
