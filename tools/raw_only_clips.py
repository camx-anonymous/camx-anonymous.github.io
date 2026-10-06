#!/usr/bin/env python3
"""Raw-only example clips: datasets whose release gives nothing to project a gripper through still get an example clip on
their page -- the raw camera views, no overlay pane (clip record ``mode: 'raw'``, the reason in ``no_overlay``).

Why these rigs get no overlay (2026-10-06):
  dexwild/dexwild          no camera intrinsics and no camera-to-hand transform for the palm cameras (the release has only the
                           wrist tracker's pose in the exterior camera), and no LEAP Hand V2 CAD in this checkout
  manipforce/manipforce    the fitted camera_in_eef has NO translation (unknown; the lens sits ~0.2 m behind the jaw tips),
                           no gripper width (a binary open flag only) and no CAD
  dexumi/dexumi            inspire_*: no Inspire RH56 hand model or CAD and no fingertip width in the release; xhand_*: the XHAND1
                           CAD at the UR5 flange pose of the DexUMI calibration through the nominal 150 deg lens lands right of
                           the replayed hand (tried 2026-10-06, tools/overlay_picks.py) -- withheld until the transform is fitted
  widowx/bridge_v2         the camera-to-flange transform of config/bridge.json is a prior, never fit: the WidowX CAD lands at the
                           bottom of the frame while the real fingers are at the top, and the flange frame itself sits at the bottom
                           edge of the image (axes profile: 2 of 24 axis vertices in frame), so there is nothing honest to draw

Writes ``<out>/<key>/<slug>/{stitched.mp4, meta.json, DONE.json, poster.jpg}`` in the clip-tree layout of tools/overlay_picks.py
(stitched.mp4 = the raw views tiled left to right at a common height, 10 fps, at most 45 s); ``encode`` makes
``overlays/videos/<key>__<slug>.mp4`` (360p) + ``overlays/posters/<key>__<slug>.jpg`` like every other clip. Then
``build_site_data.py --clips-only <projects>`` (CAMX_OVERLAYS_EXTRA = the clip tree) and ``raw_clips.py --only <key>``.

Usage:
  raw_only_clips.py list|render|encode --out <clips dir> [--only KEY] [--force]
Env:
  CAMX_ROOT  camx_480p tree (default /data/camx_480p); CAMX_BRIDGE_V2_ROOT see overlay_sources.py
"""
import argparse, datetime, json, os, subprocess, sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import overlay_picks as OP                 # noqa: E402  (info_of, episode_row, views_for, clip_dir, slug_of, key_of, flat_tasks, encode_one)
from raw_clips import episode_videos       # noqa: E402  (the episode's packed video files + start times, through overlay_sources.dataset_root)

OUT_FPS, MAX_SEC = 10, 45
REASONS = {
    'dexwild/dexwild': 'the release publishes no camera intrinsics and no camera-to-hand transform for the palm cameras, '
                       'and the LEAP Hand V2 has no CAD here',
    'manipforce/manipforce': 'the release publishes no camera-to-tool translation (the fitted camera_in_eef has zero translation), '
                             'no gripper width and no CAD',
    'dexumi/dexumi': 'the Inspire RH56 hand model and CAD are not published and the release records no fingertip width',
    'dexumi/dexumi/xhand': 'the XHAND1 CAD placed at the UR5 flange pose of the DexUMI calibration through the nominal OAK-1 W lens '
                           'does not land on the replayed hand; the camera-to-flange transform needs a fit first',
    'widowx/bridge_v2': 'the wrist camera-to-flange transform is a prior, never fitted: the WidowX 250 S CAD does not land on the real '
                        'gripper and the flange frame itself falls at the bottom edge of the image; withheld until it is fitted',
}
def reason_of(project, dataset): return REASONS.get(f'{project}/{dataset.split("_")[0]}') or REASONS[project]
# (project, dataset, episode): the first episode of at least ~5 s (longer where the dataset has one in its first 30), one per dataset
PICKS = [(p, ds, ep) for p, picks in [
    ('dexwild/dexwild', [('clothes_human', 0), ('clothes_robot', 0), ('florist_human', 0), ('florist_robot', 0), ('pour_human', 0),
                         ('pour_robot', 0), ('spray_human', 0), ('spray_robot', 0), ('toy_human', 0), ('toy_robot', 1)]),
    ('manipforce/manipforce', [('battery_insertion', 14), ('box_flipping', 0), ('gear_assembly', 8)]),
    ('dexumi/dexumi', [('inspire_cube_picking', 1), ('inspire_egg_carton', 0), ('inspire_tool_use', 1), ('xhand_kitchen', 0), ('xhand_tool_use', 1)]),
    ('widowx/bridge_v2', [('bridge_v2', 6)]),
] for ds, ep in picks]


def render_one(project, dataset, ep, out, force=False):
    d = OP.clip_dir(out, project, dataset, ep); mp4 = os.path.join(d, 'stitched.mp4'); name = f'{OP.key_of(project)}/{OP.slug_of(dataset, ep)}'
    if os.path.isfile(os.path.join(d, 'DONE.json')) and not force: print(f'{name}: done (use --force to redo)'); return
    info = OP.info_of(project, dataset); row = OP.episode_row(project, dataset, ep)
    views = OP.views_for(info, {}); keys = [f'observation.image.{v}' for v in views]
    _, vids = episode_videos(f'{project}/{dataset}', ep, keys)
    fps = Fraction(str(info['fps'])).limit_denominator(100000); stride = max(1, round(float(fps) / OUT_FPS)); rate = fps / stride
    n = len(range(0, min(int(row['length']), int(MAX_SEC * float(fps))), stride))
    shapes = [info['features'][k]['shape'] for k in keys]; hc = max(int(s[0]) for s in shapes)
    os.makedirs(d, exist_ok=True)
    cmd = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y']
    for k in keys:   # half a frame early: the first decoded frame is the episode's first, whatever the rounding of its timestamp
        cmd += ['-ss', f'{max(0.0, vids[k][1] - 0.5 / float(fps)):.6f}', '-i', vids[k][0]]
    tiles = ''.join(f"[{i}:v]select='not(mod(n\\,{stride}))',scale=-2:{hc},setsar=1[v{i}];" for i in range(len(keys)))
    stack = ''.join(f'[v{i}]' for i in range(len(keys))) + (f'hstack=inputs={len(keys)},' if len(keys) > 1 else 'null,')
    cmd += ['-filter_complex', f'{tiles}{stack}setpts=N/({rate.numerator}/{rate.denominator})/TB[o]', '-map', '[o]', '-frames:v', str(n),
            '-r', f'{rate.numerator}/{rate.denominator}', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-an', mp4]
    subprocess.run(cmd, check=True)
    n_out = OP.n_frames_of(mp4); reason = reason_of(project, dataset)
    vinfo = []
    for v, k in zip(views, keys):
        shape = info['features'][k]['shape']
        vinfo.append({'name': v, 'video_key': k, 'entity': None, 'w': int(shape[1]), 'h': int(shape[0]), 'focal_px': None, 'pinhole': None,
                      'fisheye': bool(info.get(v[:-4] + '_is_fisheye')) if v.endswith('_rgb') else False, 'calib_source': None,
                      'overlay': 'none (raw video only): ' + reason})
    grips = {s: {'model': info[f'{s}_gripper_model'], 'profile': 'none', 'urdf': None, 'urdf_present': False, 'primitive': False}
             for s in ('left', 'right') if info.get(f'{s}_gripper_model')}
    meta = {'dataset': f'{project}/{dataset}', 'robot_type': info.get('robot_type'), 'fps': float(fps), 'config': None,
            'episode_index': ep, 'length': int(row['length']), 'n_frames': n_out, 'step': stride, 'out_fps': round(float(rate), 3),
            'tasks': json.dumps(OP.flat_tasks(row['tasks'])), 'views': vinfo, 'grippers': grips, 'slug': OP.slug_of(dataset, ep), 'project': project,
            'fisheye': any(v['fisheye'] for v in vinfo), 'overlay_mode': 'raw', 'no_overlay': reason, 'tool': os.path.basename(__file__),
            'args': cmd[1:], 'source_export_id': (info.get('camx_export') or {}).get('export_id'), 'source_success_mtime': None,
            'built': datetime.datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')}
    json.dump(meta, open(os.path.join(d, 'meta.json'), 'w'), indent=1)
    json.dump({'views': views, 'n_frames': n_out, 'out_fps': meta['out_fps'], 'fisheye': meta['fisheye'], 'tool': meta['tool'], 'overlay_mode': 'raw'},
              open(os.path.join(d, 'DONE.json'), 'w'))
    subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{n_out / float(rate) / 2:.3f}', '-i', mp4, '-frames:v', '1',
                    '-q:v', '4', os.path.join(d, 'poster.jpg')], check=True)
    print(f'{name}: {n_out} frames at {float(rate):g} fps, {len(views)} view(s) x {hc}p, {os.path.getsize(mp4) // 1024} KB')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['list', 'render', 'encode'])
    ap.add_argument('--out', default=os.environ.get('CAMX_OVERLAYS_EXTRA', '').split(':')[0] or None, help='clip tree (default: the first CAMX_OVERLAYS_EXTRA dir)')
    ap.add_argument('--only', default=None, help='project key or slug substring (comma-separated alternatives)')
    ap.add_argument('--force', action='store_true', help='render: redo picks that have a DONE.json')
    a = ap.parse_args()
    picks = PICKS
    if a.only:
        alts = [x.strip() for x in a.only.split(',') if x.strip()]
        picks = [p for p in picks if any(x in OP.key_of(p[0]) or x in OP.slug_of(p[1], p[2]) for x in alts)]
    if a.cmd == 'list':
        for p in picks: print(f'{OP.key_of(p[0]):32s} {OP.slug_of(p[1], p[2]):70s} raw-only')
        print(len(picks), 'picks,', len({p[0] for p in picks}), 'projects'); return
    if not a.out: sys.exit('--out (or CAMX_OVERLAYS_EXTRA) is required')
    for p in picks:
        if a.cmd == 'render': render_one(*p, a.out, force=a.force)
        else: OP.encode_one(*p, None, a.out)


if __name__ == '__main__':
    main()
