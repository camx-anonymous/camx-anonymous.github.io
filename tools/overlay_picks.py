#!/usr/bin/env python3
"""Example overlay clips that the shared render tree does not carry (rigs without a URDF, re-renders).

The clips are rendered by ``render_bimanual_urdf_overlay_video.py`` of the camera-cross-embodiment checkout and packed
in the layout that ``tools/build_site_data.py`` reads (``<project_key>/<slug>/{stitched.mp4, poster.jpg, meta.json}``;
point ``CAMX_OVERLAYS_EXTRA`` at ``--out`` when building ``data/datasets.json``). Rigs without a URDF use the renderer's
primitive profile: two fingers hinged behind the tool-centre point that open and close with the recorded jaw width, a
bar between the fingertips, and the tool-centre frame drawn as RGB = xyz axes (the same stand-in as the HiFi-UMI
converter check). Rigs with a URDF get the URDF anchored at the camera link.

Usage:
  python3 tools/overlay_picks.py render --out <clips dir> [--only <project_key>] [--jobs 3]
  python3 tools/overlay_picks.py pack   --out <clips dir>          # meta.json + poster.jpg from the renders
  python3 tools/overlay_picks.py encode --out <clips dir>          # 360p mp4 for the release (_build/videos) + site posters
Env:
  CAMX_ROOT  camx_480p tree                                   (default /data/camx_480p)
  CAMX_VIZ   camera-cross-embodiment/camx/visualization       (default ~/projects/camera-cross-embodiment/camx/visualization)
  CAMX_PY    python for the renderer: cv2 4.x (5.0 mis-spaces the frame label), pyarrow >= 20, trimesh, yourdfpy,
             scipy, rerun-sdk                                  (default: this interpreter)
"""
import argparse, datetime, json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ROOT = os.environ.get('CAMX_ROOT', '/data/camx_480p')
VIZ = os.path.expanduser(os.environ.get('CAMX_VIZ', '~/projects/camera-cross-embodiment/camx/visualization'))
PY = os.environ.get('CAMX_PY', sys.executable)
RENDERER = 'render_bimanual_urdf_overlay_video.py'
STRIDE, MAX_SEC = 3, 45            # same clip budget as the shared tree: 10 fps, 45 s

# DataClaw: no CAD / URDF in the release and no camera-to-TCP calibration, so the tool-centre pose in the main camera is
# the candidate from the converter notes (pad centre 0.12 m from the lens, 12.5 deg below the optical axis; checked on
# two openings of device R000153). Fingers hinge L = 0.100 / (2 sin 0.51) = 102 mm behind the pads (the encoder is the
# hinge angle). Lens: the device's own 1080p intrinsics as a Kannala-Brandt model without distortion terms.
DATACLAW = dict(profile='dataclaw', mode='primitive', calib_fit='stretch', cross='off',
                extra=['--theta-max-deg', '73'], eef='0,0.0260,0.1172,0.5,0.5,-0.5,0.5',
                overlay='primitive stand-in (no URDF in the release): fingers hinged 102 mm behind the fingertip centre '
                        'spanning the recorded jaw width, bar between the tips, tool-centre axes (x red / y green / z blue); '
                        'Kannala-Brandt projection with the device intrinsics, tool-centre pose = the converter-notes candidate')
# GenRobot Gripper V4 collections: the DAS Gripper V4 URDF anchored at its camera link (the same profile as the 10Kh
# clips). The raw MCAP camera_info of these episodes is not at hand, so the lens is the rig-level mean of the 2026
# single-arm DAS unit (fx 247.5 in the 640 basis); the 10Kh lens (fx 299.5) does not fit these videos.
GENROBOT_V4 = dict(profile='genrobot', mode='urdf', calib='genrobot_das_camera0_sewing_mean.json', calib_fit='stretch',
                   urdf='DAS_Gripper_V4/urdf/DAS_Gripper_V4.urdf', gripper_profile='genrobot_das_v4',
                   extra=['--own-exclude-visuals', 'base_link,link_imu,link_ca1,link_ca2,link_ca3', '--alpha', '0.45'],
                   overlay='DAS Gripper V4 URDF anchored at its camera link (own gripper; the other gripper through the two '
                           'world trajectories), Kannala-Brandt projection with the rig-level intrinsics of the 2026 '
                           'single-arm DAS unit')

PICKS = [  # (project, dataset, episode, spec)
    ('daimon/dataclaw', 'dag911262r000153_0325_185837', 0, dict(DATACLAW, calib='daimon_dataclaw_dag911262r000153.json')),
    ('daimon/dataclaw', 'dag911262r00207e_0324_214037', 0, dict(DATACLAW, calib='daimon_dataclaw_fleet_fallback.json')),
    ('daimon/dataclaw', 'dag911262r00207e_0324_214037', 400, dict(DATACLAW, calib='daimon_dataclaw_fleet_fallback.json')),
    ('genrobot/gripper_v4', 'cup_in_box', 7, dict(GENROBOT_V4, cross='off')),
    ('genrobot/gripper_v4', 'sewing_kit_assembly', 2, dict(GENROBOT_V4, cross='off')),
    ('genrobot/gripper_v4', 'jacket_folding', 3, dict(GENROBOT_V4, cross='on')),
]


def key_of(project): return project.replace('/', '_')
def slug_of(dataset, ep): return f'{dataset}__ep{ep}'
def clip_dir(out, project, dataset, ep): return os.path.join(out, key_of(project), slug_of(dataset, ep))


def info_of(project, dataset):
    return json.load(open(os.path.join(ROOT, project, dataset, 'meta', 'info.json')))


def sides_of(info):  # renderer order: right main | left main
    return [s for s in ('right', 'left') if f'observation.image.{s}_main_camera_rgb' in info['features']]


def render_cmd(project, dataset, ep, spec, out):
    info = info_of(project, dataset)
    d = clip_dir(out, project, dataset, ep)
    cmd = [PY, os.path.join(VIZ, RENDERER), '--dataset-root', os.path.join(ROOT, project, dataset), '--episode', str(ep),
           '--profile', spec['profile'], '--calib', os.path.join(VIZ, 'calib', spec['calib']), '--calib-fit', spec['calib_fit'],
           '--cross', spec['cross'], '--stride', str(STRIDE), '--max-seconds', str(MAX_SEC),
           '--output', os.path.join(d, 'stitched.mp4')] + spec.get('extra', [])
    if spec.get('eef'):
        for s in sides_of(info):
            cmd += ['--eef-pose-in-main', f'{s}={spec["eef"]}']
    return cmd


def render_one(project, dataset, ep, spec, out):
    d = clip_dir(out, project, dataset, ep); os.makedirs(d, exist_ok=True)
    cmd = render_cmd(project, dataset, ep, spec, out)
    with open(os.path.join(d, '_render.log'), 'w') as log:
        log.write(' '.join(cmd) + '\n'); log.flush()
        rc = subprocess.run(cmd, cwd=VIZ, stdout=log, stderr=subprocess.STDOUT).returncode
    tail = open(os.path.join(d, '_render.log')).read().strip().splitlines()[-1]
    print(f'{key_of(project)}/{slug_of(dataset, ep)}: rc={rc} {tail[:120]}', flush=True)
    return rc


def n_frames_of(mp4):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries',
                          'stream=nb_read_frames', '-of', 'csv=p=0', mp4], capture_output=True, text=True).stdout
    return int(out.strip() or 0)


def episode_row(project, dataset, ep):
    import glob
    import pyarrow.parquet as pq
    for f in sorted(glob.glob(os.path.join(ROOT, project, dataset, 'meta', 'episodes', '**', '*.parquet'), recursive=True)):
        for r in pq.read_table(f, columns=['episode_index', 'length', 'tasks']).to_pylist():
            if int(r['episode_index']) == ep: return r
    raise SystemExit(f'episode {ep} not in meta/episodes of {project}/{dataset}')


def flat_tasks(v):
    """meta/episodes `tasks` as a flat list of strings (some converters store a JSON-encoded list inside the cell)."""
    out = []
    for t in (v if isinstance(v, list) else [v]):
        if isinstance(t, str) and t.startswith('['):
            try: t = json.loads(t)
            except ValueError: pass
        out += t if isinstance(t, list) else [t]
    return out


def pack_one(project, dataset, ep, spec, out):
    d = clip_dir(out, project, dataset, ep); mp4 = os.path.join(d, 'stitched.mp4')
    if not os.path.isfile(mp4): print(f'{d}: no stitched.mp4 (render first)'); return
    info = info_of(project, dataset); row = episode_row(project, dataset, ep); fps = float(info['fps'])
    sides = sides_of(info); n = n_frames_of(mp4)
    views = []; grips = {}
    for s in sides:
        key = f'observation.image.{s}_main_camera_rgb'; shape = info['features'][key]['shape']
        views.append({'name': f'{s}_main_camera_rgb', 'video_key': key, 'entity': None, 'w': int(shape[1]), 'h': int(shape[0]),
                      'focal_px': None, 'pinhole': False, 'fisheye': True, 'overlay': spec['overlay']})
        grips[s] = {'model': info.get(f'{s}_gripper_model'), 'profile': spec.get('gripper_profile', spec['profile'] + '_primitives'),
                    'urdf': spec.get('urdf'), 'urdf_present': bool(spec.get('urdf')), 'primitive': spec['mode'] == 'primitive'}
    tasks = flat_tasks(row['tasks'])
    cmd = render_cmd(project, dataset, ep, spec, out)
    meta = {'dataset': f'{project}/{dataset}', 'robot_type': info.get('robot_type'), 'fps': fps, 'config': RENDERER,
            'episode_index': ep, 'length': int(row['length']), 'n_frames': n, 'step': STRIDE, 'out_fps': round(fps / STRIDE, 3),
            'tasks': json.dumps(tasks), 'views': views, 'grippers': grips, 'slug': slug_of(dataset, ep), 'project': project,
            'fisheye': {'calib': {s: spec['calib'] for s in sides}}, 'overlay_mode': spec['mode'], 'tool': RENDERER,
            'args': [os.path.relpath(a, VIZ) if a.startswith(VIZ) else a for a in cmd[2:]],
            'source_export_id': None, 'source_success_mtime': None,
            'built': datetime.datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')}
    json.dump(meta, open(os.path.join(d, 'meta.json'), 'w'), indent=1)
    json.dump({'views': [v['name'] for v in views], 'n_frames': n, 'out_fps': meta['out_fps'], 'fisheye': True, 'tool': RENDERER,
               'overlay_mode': spec['mode']}, open(os.path.join(d, 'DONE.json'), 'w'))
    png = os.path.join(d, 'stitched.png')  # the renderer's mid-clip poster (gripper in view); else frame 0
    src = ['-i', png] if os.path.isfile(png) else ['-ss', '0', '-i', mp4]
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error'] + src + ['-frames:v', '1', '-q:v', '4', os.path.join(d, 'poster.jpg')], check=True)
    print(f'{key_of(project)}/{slug_of(dataset, ep)}: {n} frames, {len(views)} view(s), mode {spec["mode"]}')


def encode_one(project, dataset, ep, spec, out):
    d = clip_dir(out, project, dataset, ep); name = f'{key_of(project)}__{slug_of(dataset, ep)}'
    vid_dir = os.path.join(REPO, '_build', 'videos'); os.makedirs(vid_dir, exist_ok=True)
    mp4 = os.path.join(vid_dir, name + '.mp4'); poster = os.path.join(REPO, 'overlays', 'posters', name + '.jpg')
    base = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', os.path.join(d, 'stitched.mp4'), '-vf', 'scale=-2:360']
    tail = ['-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', mp4]
    rc = subprocess.run(base + ['-c:v', 'h264_nvenc', '-preset', 'p5', '-cq', '31'] + tail).returncode
    if rc != 0:
        subprocess.run(base + ['-c:v', 'libx264', '-preset', 'slow', '-crf', '28'] + tail, check=True)
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', os.path.join(d, 'poster.jpg'), '-vf', 'scale=-2:180',
                    '-q:v', '6', poster], check=True)
    print(f'{name}: {os.path.getsize(mp4) // 1024} KB -> {os.path.relpath(mp4, REPO)}, poster {os.path.relpath(poster, REPO)}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['render', 'pack', 'encode', 'list'])
    ap.add_argument('--out', default=os.environ.get('CAMX_OVERLAYS_EXTRA', '').split(':')[0] or None,
                    help='clip tree (default: the first CAMX_OVERLAYS_EXTRA dir)')
    ap.add_argument('--only', default=None, help='project key or slug substring')
    ap.add_argument('--jobs', type=int, default=3)
    a = ap.parse_args()
    picks = [p for p in PICKS if not a.only or a.only in key_of(p[0]) or a.only in slug_of(p[1], p[2])]
    if a.cmd == 'list':
        for p in picks: print(key_of(p[0]), slug_of(p[1], p[2]), p[3]['mode'], p[3]['calib'])
        return
    if not a.out: sys.exit('--out (or CAMX_OVERLAYS_EXTRA) is required')
    fn = {'render': render_one, 'pack': pack_one, 'encode': encode_one}[a.cmd]
    if a.cmd == 'render' and a.jobs > 1:
        with ThreadPoolExecutor(a.jobs) as ex:
            list(ex.map(lambda p: fn(*p, a.out), picks))
    else:
        for p in picks: fn(*p, a.out)


if __name__ == '__main__':
    main()
