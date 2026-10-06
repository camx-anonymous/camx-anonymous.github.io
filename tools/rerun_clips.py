#!/usr/bin/env python3
"""Re-render the site's example clips in the look of the curation site: the gripper as the opaque light-grey CAD (URDF) mesh
of the headless Rerun viewer, projected through each dataset's own poses and intrinsics, nothing else drawn on the frame.

Every clip of data/datasets.json (same dataset, episode and camera views) takes one route (``plan`` prints them):
  reuse    the curation tree holds a current headless-Rerun export of the clip (DONE.json, source stamp unchanged): its
           per-view mp4s are stitched in the site's view order
  rerun    headless Rerun render (lerobot_rerun_viz.py -> mv_site/record_views.py) for clips the curation tree lacks or holds
           stale, including the OpenNeoData PiPER / ARX X5 / UMI rigs, drawn with the stock gripper CAD as a stand-in (STANDIN)
  fisheye  rigs the Rerun viewer cannot draw through (Kannala-Brandt / EUCM lenses): render_bimanual_urdf_overlay_video.py
           through tools/white_overlay.py (every mesh in the Rerun grey, opaque)
  keep     left as it is: pinhole rig without a gripper CAD, or no lens file / viz config in this checkout

Writes <out>/<key>/<slug>/{stitched.mp4, meta.json, DONE.json, poster.jpg} in the layout of the shared clip tree
(build_site_data.overlay_metas); ``encode`` makes the 360p site mp4 + poster, ``attach`` rewrites the clip records of
data/datasets.json from the tree (views, grippers, mode, seconds, bytes, caption track). Then run tools/raw_clips.py.

Usage (python of the camera-cross-embodiment env: rerun, pyarrow, cv2):
  rerun_clips.py plan   [--only X]
  rerun_clips.py render [--only X] [--jobs-rerun 2] [--jobs-fisheye 3] [--force]
  rerun_clips.py encode [--only X]
  rerun_clips.py attach
Env:
  CAMX_ROOT       camx_480p tree                              CAMX_VIZ   camera-cross-embodiment/camx/visualization
  CAMX_CURATION   the curation tree's mv_urdf/videos           CAMX_PY    python for the renderers (default: this one)
  CAMX_CLIPS_OUT  the clip tree written here                   MV_SITE_MESA  lavapipe env for the headless viewer
"""
import argparse, datetime, hashlib, json, os, queue, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
ROOT = os.environ.get('CAMX_ROOT', '/data/camx_480p')
VIZ = os.path.expanduser(os.environ.get('CAMX_VIZ', '~/video-gen/repositories/camera-cross-embodiment/camx/visualization'))
PY = os.environ.get('CAMX_PY', sys.executable)
CUR = os.environ.get('CAMX_CURATION', '/data/camx_480p_browser/mv_urdf/videos')
OUT = os.environ.get('CAMX_CLIPS_OUT', '/data/camx_clips')
os.environ.setdefault('MV_SITE_MESA', '/data/camx_clips/mesa_shim')
PRESSURE = '/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/memory.pressure'
MAX_SEC, OUT_FPS, MAX_VIEWS = 45, 10, 4      # the clip budget of the shared tree and of tools/overlay_picks.py
sys.path[:0] = [VIZ, os.path.join(VIZ, 'mv_site')]

# viz configs of the Rerun route for projects the curation planner (build_mv_site.config_for) does not cover
EXTRA_CONFIG = {'franka_hand/fmb': 'config/fmb.json', 'franka_hand/rh20t_cfg5': 'config/rh20t.json', 'robotiq/rh20t_cfg4': 'config/rh20t.json',
                # RH20T cfg1-3: the vendors' AG-95 / WSG-50 URDFs (grippers/dh_ag95, grippers/wsg50 of the checkout), hung behind the tcp
                'dahuan/rh20t_cfg1': 'config/rh20t.json', 'dahuan/rh20t_cfg2': 'config/rh20t.json', 'wsg50/rh20t_cfg3': 'config/rh20t.json',
                'robotiq/rh20t_cfg6': 'config/rh20t.json', 'robotiq/rh20t_cfg7': 'config/rh20t.json', 'robotiq/droid_lowres': 'config/droid.json',
                'robotiq/roboset_kinesthetic': 'config/roboset_kinesthetic.json', 'robotiq/roboset_teleop': 'config/roboset_teleop.json',
                'stretch/dobbe': 'config/dobbe.json',
                # OpenNeoData publishes no gripper CAD: the stock gripper of each rig stands in (the wrist lens of the aloha rig is
                # the fx-306 assumption of camx/data_processing/openneo, as in tools/overlay_picks.py)
                'aloha/openneo_aloha': os.path.join(HERE, 'configs', 'openneo_aloha_fx306.json'), 'aloha/openneo_arx5': 'config/openneo.json',
                'aloha/openneo_arx5_single': 'config/openneo_single.json', 'umi/openneo_umi': 'config/openneo_umi.json',
                'umi/openneo_umi_single': 'config/openneo_umi_single.json'}
# the dataset names another gripper than the rig carries: drawn with this registry profile instead (AIST: ALOHA 1 arms, ALOHA-2-style fingers)
MODEL_OVERRIDE = {'aloha/aist_bimanip': 'aloha2'}
STANDIN = {'aloha/openneo_aloha': 'piper', 'aloha/openneo_arx5': 'arx x5', 'aloha/openneo_arx5_single': 'arx x5',
           'umi/openneo_umi': 'umi', 'umi/openneo_umi_single': 'umi'}   # the ARX X5 / UMI ones are in KEEP, see there
# fisheye route: arguments of render_bimanual_urdf_overlay_video.py (tiles: right main | left main)
GOPRO = dict(profile='umi', calib='gopro_hero9_maxlens_2_7k_umi.json', fit='crop')   # GoPro Hero 9/10 + Max Lens Mod, centre crop
FISHEYE = {p: GOPRO for p in ('fastumi/fastumi', 'fastumi/fastumi_100k_single_arm', 'umi/data_scaling_laws', 'umi/exumi', 'umi/humi',
                               'umi/maniwav', 'umi/mvumi', 'umi/touch_in_the_wild', 'umi/umi', 'umi/umi_on_legs', 'umi/vitamin', 'umi/vitamin_b')}
for p in ('fastumi/fastumi', 'fastumi/fastumi_100k_single_arm', 'fastumi/fastumi_100k_dual_arm'): FISHEYE[p] = dict(GOPRO, profile='fastumi')   # UMI mesh at the rig's own TCP (camera-to-tip 145 mm, not UMI's 220)
FISHEYE['umi/exumi'] = dict(GOPRO, profile='exumi')   # grippers/exumi: the exUMI 9DTact fingertips fitted to the wrist frames (2026-10-03)
# grippers/vitamin_b: DuoTact fingers fitted to the wrist frames; the release's GoPro lens through the 2028-square crop -> 224 (crop chain assumed);
# theta-max = the circular image mask, so the other hand is not drawn into the black surround
FISHEYE['umi/vitamin_b'] = dict(profile='vitamin_b', calib='vitamin_b_gopro_webcam_224.json', fit='crop', extra=['--theta-max-deg', '55'])
FISHEYE['genrobot/10kh'] = dict(profile='genrobot', fit='stretch', calib_episode='genrobot_episodes/{ds}_ep{ep}_{side}.json',   # per-episode MCAP camera_info
                                extra=['--cross', 'on', '--own-exclude-visuals', 'base_link,link_imu,link_ca1,link_ca2,link_ca3',
                                       '--anchor-delta-xyz=0.0067,-0.0204,0.0142', '--anchor-delta-rpy=0,0,0.042', '--width-scale', '0.94'])
FISHEYE['daimon/dataclaw'] = dict(profile='dataclaw', fit='stretch', calib_device='daimon_dataclaw_{device}.json', calib='daimon_dataclaw_fleet_fallback.json',
                                  extra=['--cross', 'off', '--theta-max-deg', '73'], eef='0,0.0260,0.1172,0.5,0.5,-0.5,0.5', mode='primitive')
FISHEYE['umi/umi_benchmark'] = dict(profile='umi_benchmark', calib='umi_benchmark_fastumi_pro_seucm.json', fit='crop', mode='primitive')
# Vista-UMI: the same Lumos FastUMI Pro handheld as UMI-Benchmark (swing gripper, no CAD), so the same stand-in, lens file and
# gripper label; its info.json carries a placeholder eef_pose_in_main (identity rotation) and labels the gripper `fastumi`, which
# would draw the GoPro UMI model where the real swing fingers are not (2026-10-03): the UMI-Benchmark calibration of the tcp in the
# main camera (its info.json, one constant for both hands) is passed instead
FISHEYE['umi/vista_umi'] = dict(FISHEYE['umi/umi_benchmark'], model='lumos swing gripper',
                                eef='0.001071,0.067511,0.076303,-0.499159,-0.502619,0.506589,-0.491509')
# left as they are: pinhole rigs without a gripper CAD (the Rerun viewer draws URDFs only), and rigs whose lens file or viz config
# is not in this checkout (umi3d / aetherock lens files, robomind_ur5 config, the gripper_v4 DAS lens, hifi_umi's attached cameras)
# multiview route: rigs the headless Rerun viewer cannot do, drawn by render_multiview_overlay_video.py (or, for GenRobot V4, the
# bimanual fisheye tool) through tools/white_multiview.py / white_overlay.py with the arguments of tools/overlay_picks.py (SPECS and
# its explicit picks): pinhole rigs without a gripper CAD (primitive stand-in: the OpenNeoData Flexiv / UR / ARX X5 /
# UMI rigs, whose stock-CAD stand-in does not land on the fingers), fisheye rigs with their own lens file (UMI-3D, AetheRock,
# HiFi-UMI, GenRobot V4), RoboMIND UR5 (no-mimic Robotiq URDF) and the 180p DROID twin (the viewer draws nothing at 320x180).
# Their renderer, configs and lens files are on camera-cross-embodiment origin/main: CAMX_VIZ_MV names that checkout's visualization dir.
MULTIVIEW = {'flexiv/openneo_flexiv', 'ur/openneo_ur', 'robotiq/robomind_ur5',
             'umi/umi3d', 'umi/aetherock', 'hifi_umi/hifi_umi', 'genrobot/gripper_v4', 'aloha/openneo_arx5', 'aloha/openneo_arx5_single',
             'umi/openneo_umi', 'umi/openneo_umi_single', 'robotiq/droid_lowres'}
VIZ_MV = os.path.expanduser(os.environ.get('CAMX_VIZ_MV', '/data/camx/visualization'))
KEEP = set()
# bimanual rigs whose two hands are NOT in one world frame (build_site_data.WORLD_FRAME_NOTES): each view draws its own gripper only
# (fisheye route: --cross off; multiview route: --own-only); the clip record carries own_only for the viewers' note
OWN_ONLY = {'umi/vista_umi', 'fastumi/fastumi_100k_dual_arm', 'umi/openneo_umi'}


def log(msg): print(f'{datetime.datetime.now():%H:%M:%S} {msg}', flush=True)
def is_done(d):
    """finish() ran: DONE.json AND a meta.json with the tool (record_views.py writes a DONE.json of its own after the per-view mp4s)."""
    try: return os.path.isfile(os.path.join(d, 'DONE.json')) and 'tool' in json.load(open(os.path.join(d, 'meta.json')))
    except (OSError, ValueError): return False
def proj_of(o): return '/'.join(o['dataset'].split('/')[:2])
def feat(name): return name.split('observation.image.', 1)[1] if name.startswith('observation.image.') else name
def info_of(rel): return json.load(open(os.path.join(ROOT, rel, 'meta', 'info.json')))
def stamp(rel):
    m = os.path.join(ROOT, rel, 'meta', '_SUCCESS')
    return time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(os.stat(m).st_mtime)) if os.path.isfile(m) else None


def render_provenance(o):
    """Invalidate old videos when source files, calibration, CAD or render code change.

    _SUCCESS is an export marker, not a content version: in-place pose/video
    backfills intentionally retain it. Old caches lacking this record must be
    rendered once before they can be trusted again.
    """
    import pyarrow.parquet as pq
    root = Path(ROOT, o['dataset']).resolve()
    info = info_of(o['dataset'])
    ep = int(o['episode'])
    keys = [f'observation.image.{v}' for v in o['views']]
    source = [root / 'meta' / 'info.json']
    row = None
    for f in sorted((root / 'meta' / 'episodes').rglob('*.parquet')):
        source.append(f)
        cols = ['episode_index'] + [f'videos/{k}/{c}' for k in keys
                                   for c in ('chunk_index', 'file_index', 'from_timestamp')]
        for candidate in pq.read_table(f, columns=cols).to_pylist():
            if int(candidate['episode_index']) == ep:
                row = candidate
                break
        if row is not None:
            break
    if row is None:
        raise ValueError(f'{root}: episode {ep} not in meta/episodes')
    for key in keys:
        source.append(root / info['video_path'].format(video_key=key,
            chunk_index=row[f'videos/{key}/chunk_index'], file_index=row[f'videos/{key}/file_index']))
    # A pose backfill can replace any shard without touching info/_SUCCESS.
    source.extend(sorted((root / 'data').rglob('*.parquet')))
    # Per-episode EEF/camera calibration may live in metadata sidecars.
    source.extend(sorted((root / 'meta').glob('*.parquet')))

    def signature(path, content=False):
        st = path.stat()
        rec = [str(path.resolve()), st.st_size, st.st_mtime_ns]
        if content:
            rec.append(hashlib.sha256(path.read_bytes()).hexdigest())
        return rec

    renderer = []
    seen = set()
    for base in (Path(VIZ), Path(VIZ_MV), Path(HERE)):
        if not base.is_dir():
            continue
        for p in sorted(base.rglob('*')):
            if not p.is_file() or p.suffix.lower() not in {'.py', '.json', '.urdf', '.stl', '.dae', '.obj', '.mtl'}:
                continue
            if base == Path(HERE) and p.parent == base and p.name not in {'rerun_clips.py', 'white_overlay.py', 'white_multiview.py', 'overlay_picks.py'}:
                continue
            if '__pycache__' in p.parts or p.resolve() in seen:
                continue
            seen.add(p.resolve())
            renderer.append(signature(p, content=True))
    # Path.rglob does not traverse symlinked gripper directories. Follow the
    # selected profiles and every mesh/texture referenced by their URDFs, even
    # when assets live under data_processing or another external directory.
    import xml.etree.ElementTree as ET
    urdfs = {Path(rec[0]) for rec in renderer if Path(rec[0]).suffix.lower() == '.urdf'}
    models = {info.get(f'{side}_gripper_model') for side in ('left', 'right')}
    models.update(g.get('model') for g in o.get('grippers', {}).values())
    proj = proj_of(o)
    models.update((STANDIN.get(proj), MODEL_OVERRIDE.get(proj), FISHEYE.get(proj, {}).get('profile')))
    if any(models):
        import gripper_registry
        for model in filter(None, models):
            profile = gripper_registry.lookup(model)
            if profile is None:
                continue
            for side in ('left', 'right'):
                relative = profile.urdf_path(side).relative_to(gripper_registry.GRIPPERS_ROOT)
                for base in (Path(VIZ), Path(VIZ_MV)):
                    if base.is_dir(): urdfs.add(base / 'grippers' / relative)

    def dependency(path):
        path = path.resolve()
        if path not in seen:
            seen.add(path)
            renderer.append(signature(path, content=True) if path.is_file() else [str(path), 'missing'])

    for urdf in sorted(urdfs):
        dependency(urdf)
        if not urdf.is_file():
            continue
        for node in ET.parse(urdf).getroot().iter():
            raw = node.get('filename')
            if not raw:
                continue
            if raw.startswith('package://'):
                body = raw[len('package://'):]
                rel = body.split('/', 1)[1] if '/' in body else ''
                candidate = urdf.parent.parent / rel
                beside = urdf.parent / body
                path = candidate if candidate.is_file() or not beside.is_file() else beside
            else:
                path = urdf.parent / raw.removeprefix('file://')
            dependency(path)
    renderer.sort(key=lambda rec: rec[0])
    payload = {'schema': 1, 'renderer_python': os.path.realpath(PY), 'dataset': str(root), 'episode': ep, 'views': list(o['views']),
               'max_seconds': MAX_SEC, 'output_fps': OUT_FPS,
               'source': [signature(p, content=p.suffix == '.json') for p in source],
               'renderer': renderer}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'fingerprint': digest, **payload}


def current_cache(d, provenance):
    if provenance is None or not is_done(d):
        return False
    try:
        m = json.load(open(os.path.join(d, 'meta.json')))
        return m.get('render_provenance', {}).get('fingerprint') == provenance['fingerprint']
    except (OSError, ValueError):
        return False


def probe(mp4):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries', 'stream=width,height,r_frame_rate,nb_read_frames',
                          '-of', 'json', mp4], capture_output=True, text=True, check=True).stdout
    s = json.loads(out)['streams'][0]; num, den = s['r_frame_rate'].split('/')
    return int(s['width']), int(s['height']), float(num) / float(den), int(s['nb_read_frames'])


def pick_views(available, site_views):
    """The site's current view order when every one of its views was rendered, else wrists first, then the other main cameras."""
    if all(v in available for v in site_views): return list(site_views)
    pri = lambda n: (0 if n.startswith('right_main') else 1 if n.startswith('left_main') else 2 if 'main_camera' in n else 3)  # noqa: E731
    return sorted(available, key=lambda n: (pri(n), available.index(n)))[:MAX_VIEWS]


def stitch(parts, dst):
    """parts = [(view name, mp4)] left to right; every view scaled to the tallest one's height (the layout tools/raw_clips.py repeats)."""
    if len(parts) == 1: shutil.copy2(parts[0][1], dst); return
    hs = [probe(p)[1] for _, p in parts]; hc = max(hs)
    cmd = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y']
    for _, p in parts: cmd += ['-i', p]
    fc = ''.join(f'[{i}:v]scale=-2:{hc},setsar=1[v{i}];' for i in range(len(parts))) + ''.join(f'[v{i}]' for i in range(len(parts))) + f'hstack=inputs={len(parts)}[o]'
    subprocess.run(cmd + ['-filter_complex', fc, '-map', '[o]', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', dst], check=True)


def poster(mp4, jpg):
    _, _, rate, n = probe(mp4)
    subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{n / rate / 2:.3f}', '-i', mp4, '-frames:v', '1', '-q:v', '4', jpg], check=True)


def finish(d, meta, views, mode, tool, t0):
    """meta.json + DONE.json + poster.jpg of a rendered clip; n_frames / out_fps read back from stitched.mp4."""
    _, _, rate, n = probe(os.path.join(d, 'stitched.mp4'))
    meta.update(views=views, n_frames=n, out_fps=round(rate, 3), overlay_mode=mode, tool=tool, render_seconds=round(time.time() - t0),
                built=datetime.datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z'))
    json.dump(meta, open(os.path.join(d, 'meta.json'), 'w'), indent=1)
    json.dump({'views': [v['name'] for v in views], 'n_frames': n, 'out_fps': meta['out_fps'], 'fisheye': meta.get('fisheye', False), 'tool': tool, 'overlay_mode': mode},
              open(os.path.join(d, 'DONE.json'), 'w'))
    poster(os.path.join(d, 'stitched.mp4'), os.path.join(d, 'poster.jpg'))
    return f"{len(views)} view(s), {n} frames, {meta['render_seconds']}s"


# ── plan ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def route_of(o):
    proj = proj_of(o)
    if not os.path.isfile(os.path.join(ROOT, o['dataset'], 'meta', 'info.json')): return 'keep', 'dataset not in this tree'
    if proj in FISHEYE: return 'fisheye', None
    if proj in MULTIVIEW: return 'multiview', None
    if proj in KEEP: return 'keep', None
    cd = os.path.join(CUR, o['key'], o['slug'])
    if os.path.isfile(os.path.join(cd, 'DONE.json')):
        m = json.load(open(os.path.join(cd, 'meta.json')))
        have = [feat(v['video_key']) for v in m['views']]
        if m.get('render_provenance', {}).get('fingerprint') == render_provenance(o)['fingerprint'] and all(v in have for v in o['views']) \
                and all(os.path.isfile(os.path.join(cd, v['name'] + '.mp4')) for v in m['views']): return 'reuse', cd
    import build_mv_site as B
    info = info_of(o['dataset']); keys = [k for k, f in info['features'].items() if f.get('dtype') == 'video']
    cfg = B.config_for(proj, str(info.get('robot_type')), len(keys), keys, o['dataset'])
    if cfg is None and proj in EXTRA_CONFIG: cfg = EXTRA_CONFIG[proj] if os.path.isabs(EXTRA_CONFIG[proj]) else os.path.join(VIZ, EXTRA_CONFIG[proj])
    if cfg is None or not os.path.isfile(str(cfg)): return 'keep', f'no viz config ({cfg})'
    return 'rerun', str(cfg)


def plan(ovs):
    rows = [(o, *route_of(o)) for o in ovs]
    for o, r, x in rows: print(f"{r:8s} {o['key']}/{o['slug']}  {('' if x is None else x).replace(VIZ + '/', '')}")
    from collections import Counter
    print(dict(Counter(r for _, r, _ in rows)), file=sys.stderr)
    return rows


# ── routes ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def reuse_one(o, cd, d, t0):
    m = json.load(open(os.path.join(cd, 'meta.json'))); by = {feat(v['video_key']): v for v in m['views']}
    names = pick_views(list(by), o['views'])
    stitch([(n, os.path.join(cd, by[n]['name'] + '.mp4')) for n in names], os.path.join(d, 'stitched.mp4'))
    views = [dict(by[n], name=n) for n in names]
    meta = {k: m[k] for k in m if k not in ('render_seconds', 'views')}; meta['reused_from'] = cd
    return finish(d, meta, views, 'urdf', 'rerun', t0)


def rerun_one(o, cfg, d, slot, t0):
    import build_mv_site as B, gripper_registry
    proj, rel, ep = proj_of(o), o['dataset'], int(o['episode']); root = Path(ROOT) / rel
    as_py = lambda v: v.as_py() if hasattr(v, 'as_py') else v  # noqa: E731
    row = next(r for r in B.episodes_table(root) if int(as_py(r['episode_index'])) == ep)
    # the clip's own copy of the viz config, without the camera streams this dataset lacks (rh20t.json lists every camera of
    # the RH20T rigs as a fallback, droid.json both ZED eyes): the viz exits on a video_key missing from the features
    cfg_src = cfg; c = json.load(open(cfg)); feats = info_of(rel)['features']
    c['videos'] = [v for v in c.get('videos', []) if v.get('video_key') in feats]
    if not c['videos']: raise SystemExit(f'{cfg_src}: none of its camera streams is in {rel}')
    cfg = os.path.join(d, 'viz_config.json'); json.dump(c, open(cfg, 'w'), indent=1)
    info, vids, grip = B.resolve_videos(root, Path(cfg), ep); fps = float(info['fps'])
    step = max(1, int(round(fps / OUT_FPS))); start = int(as_py(row['dataset_from_index'])); n_cap = min(int(as_py(row['length'])), int(MAX_SEC * fps))
    frames = list(range(start, start + n_cap, step))
    by = {feat(v2.video_key): (v2, ent) for v2, ent in vids}; names = pick_views(list(by), o['views']); views = []
    for n in names:
        v2, ent = by[n]; shape = info['features'][v2.video_key]['shape']; H, W = int(shape[0]), int(shape[1])
        focal = v2.seed_intrinsics[0] if v2.seed_intrinsics else (v2.focal_px(W) if (v2.fx is not None or v2.hfov_deg is not None) else None)
        views.append({'name': n, 'video_key': v2.video_key, 'entity': ent, 'w': W, 'h': H, 'focal_px': focal, 'pinhole': bool(v2.has_pinhole)})
    extra = list(B.RRD_EXTRA_ARGS.get(proj, []))
    if proj in STANDIN:
        prof = gripper_registry.lookup(STANDIN[proj])
        for side in grip:
            extra += ['--gripper-profile-override', f'{side}={STANDIN[proj]}']
            grip[side] = dict(grip[side], profile=prof.name, urdf=str(prof.urdf_path(side)), urdf_present=prof.urdf_path(side).is_file(), standin=True)
    if proj in MODEL_OVERRIDE:
        prof = gripper_registry.lookup(MODEL_OVERRIDE[proj])
        for side in grip:
            extra += ['--gripper-profile-override', f'{side}={MODEL_OVERRIDE[proj]}']
            grip[side] = dict(grip[side], profile=prof.name, urdf=str(prof.urdf_path(side)), urdf_present=prof.urdf_path(side).is_file())
    for f in Path(d).glob('*.mp4'): f.unlink()   # record_views keeps a view whose mp4 exists
    rrd = Path(d) / 'episode.rrd'
    with open(os.path.join(d, '_render.log'), 'w') as lg:
        cmd = [PY, os.path.join(VIZ, 'lerobot_rerun_viz.py'), '--dataset-root', str(root), '--viz-config', cfg, '--mode', 'download', '--episode', str(ep),
               '--gripper', 'auto', '--rrd-path', str(rrd)] + extra
        lg.write(' '.join(cmd) + '\n'); lg.flush(); subprocess.run(cmd, stdout=lg, stderr=subprocess.STDOUT, check=True)
        job = {'rrd': str(rrd), 'fps': fps, 'frames': frames, 'out_dir': d, 'gpu': '1', 'port_base': 9700 + 40 * slot, 'out_fps': round(fps / step, 3),
               'app_id': Path(rel).name, 'contents': ['+ /world/grippers/**'], 'settle_s': 0.3,
               'views': [{'name': v['name'], 'entity': v['entity'], 'w': v['w'], 'h': v['h'], 'focal_px': v['focal_px'] or v['w'] * 0.8} for v in views]}
        json.dump(job, open(os.path.join(d, 'job.json'), 'w'))
        subprocess.run([PY, os.path.join(VIZ, 'mv_site', 'record_views.py'), os.path.join(d, 'job.json')], stdout=lg, stderr=subprocess.STDOUT, check=True)
    rrd.unlink(missing_ok=True)
    stitch([(n, os.path.join(d, n + '.mp4')) for n in names], os.path.join(d, 'stitched.mp4'))
    tasks = as_py(row['tasks']); tasks = tasks if isinstance(tasks, list) else [tasks]
    meta = {'dataset': rel, 'robot_type': info.get('robot_type'), 'fps': fps, 'config': cfg_src, 'episode_index': ep, 'length': int(as_py(row['length'])), 'step': step,
            'tasks': json.dumps(tasks), 'grippers': grip, 'slug': o['slug'], 'project': proj, 'fisheye': False, 'args': extra,
            'source_export_id': (info.get('camx_export') or {}).get('export_id'), 'source_success_mtime': stamp(rel), 'source_realpath': str(root.resolve())}
    return finish(d, meta, views, 'urdf', 'rerun', t0)


def fisheye_one(o, d, t0):
    proj, rel, ep = proj_of(o), o['dataset'], int(o['episode']); spec = FISHEYE[proj]; info = info_of(rel); fps = float(info['fps'])
    step = max(1, int(round(fps / OUT_FPS))); ds = rel.split('/')[-1]
    sides = [s for s in ('right', 'left') if f'observation.image.{s}_main_camera_rgb' in info['features']]   # the renderer's tile order
    cmd = [PY, os.path.join(HERE, 'white_overlay.py'), '--dataset-root', os.path.join(ROOT, rel), '--episode', str(ep), '--profile', spec['profile'],
           '--calib-fit', spec['fit'], '--stride', str(step), '--max-seconds', str(MAX_SEC), '--alpha', '1.0', '--output', os.path.join(d, 'stitched.mp4')] + spec.get('extra', [])
    if proj in OWN_ONLY: cmd += ['--cross', 'off']
    if 'calib_episode' in spec:
        for s in sides: cmd += [f'--calib-{s}', os.path.join(VIZ, 'calib', spec['calib_episode'].format(ds=ds, ep=ep, side=s))]
    else:
        c = spec.get('calib_device', '').format(device=ds.split('_')[0]) if spec.get('calib_device') else ''
        cmd += ['--calib', os.path.join(VIZ, 'calib', c if c and os.path.isfile(os.path.join(VIZ, 'calib', c)) else spec['calib'])]
    for s in sides if spec.get('eef') else []: cmd += ['--eef-pose-in-main', f"{s}={spec['eef']}"]
    with open(os.path.join(d, '_render.log'), 'w') as lg:
        lg.write(' '.join(cmd) + '\n'); lg.flush(); subprocess.run(cmd, cwd=VIZ, stdout=lg, stderr=subprocess.STDOUT, check=True)
    import gripper_registry
    views, grip = [], {}
    for s in sides:
        key = f'observation.image.{s}_main_camera_rgb'; shape = info['features'][key]['shape']
        views.append({'name': f'{s}_main_camera_rgb', 'video_key': key, 'entity': None, 'w': int(shape[1]), 'h': int(shape[0]), 'focal_px': None, 'pinhole': False, 'fisheye': True})
        model = info.get(f'{s}_gripper_model'); prof = None if spec.get('mode') == 'primitive' else (gripper_registry.lookup(model) or gripper_registry.lookup(spec['profile']))
        model = spec.get('model') or model   # the spec's label when the dataset's does not name the rig's gripper (Vista-UMI)
        grip[s] = {'model': model or spec['profile'], 'profile': prof.name if prof else spec['profile'], 'urdf': str(prof.urdf_path(s)) if prof else None,
                   'urdf_present': bool(prof and prof.urdf_path(s).is_file()), 'primitive': prof is None}
    import glob, pyarrow.parquet as pq
    row = next(r for f in sorted(glob.glob(os.path.join(ROOT, rel, 'meta', 'episodes', '**', '*.parquet'), recursive=True))
               for r in pq.read_table(f, columns=['episode_index', 'length', 'tasks']).to_pylist() if int(r['episode_index']) == ep)
    tasks = row['tasks'] if isinstance(row['tasks'], list) else [row['tasks']]
    meta = {'dataset': rel, 'robot_type': info.get('robot_type'), 'fps': fps, 'config': 'render_bimanual_urdf_overlay_video.py', 'episode_index': ep, 'length': int(row['length']),
            'step': step, 'tasks': json.dumps(tasks), 'grippers': grip, 'slug': o['slug'], 'project': proj, 'fisheye': True,
            'args': [a.replace(VIZ + '/', '') for a in cmd[2:]], 'source_export_id': (info.get('camx_export') or {}).get('export_id'),
            'source_success_mtime': stamp(rel), 'source_realpath': str(Path(ROOT, rel).resolve())}
    return finish(d, meta, views, spec.get('mode', 'urdf'), 'render_bimanual_urdf_overlay_video.py', t0)


# ── commands ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
_OP_LOCK = __import__('threading').Lock()
def multiview_one(o, d, t0):
    sys.path.insert(0, HERE); import overlay_picks as OP
    OP.ROOT, OP.VIZ = ROOT, VIZ_MV
    proj = proj_of(o); ds = o['dataset'].split('/', 2)[2]; ep = int(o['episode'])
    spec = next((p[3] for p in OP.EXPLICIT_PICKS + OP.REPLACE_PICKS if p[:3] == (proj, ds, ep)), None) or OP.SPECS[proj]
    spec = dict(spec, views=list(o['views'])) if spec['tool'] == OP.MULTIVIEW else dict(spec)
    stride = max(1, round(float(info_of(o['dataset'])['fps']) / OUT_FPS))   # overlay_picks samples every 3rd frame whatever the rate
    with _OP_LOCK: OP.STRIDE = stride; cmd = OP.render_cmd(proj, ds, ep, spec, OUT)
    cmd[1] = os.path.join(HERE, 'white_multiview.py' if spec['tool'] == OP.MULTIVIEW else 'white_overlay.py')
    while '--alpha' in cmd: i = cmd.index('--alpha'); del cmd[i:i + 2]
    cmd += ['--alpha', '1.0']
    if proj in OWN_ONLY and spec['tool'] == OP.MULTIVIEW: cmd += ['--own-only']
    with open(os.path.join(d, '_render.log'), 'w') as lg:
        lg.write(' '.join(cmd) + '\n'); lg.flush()
        subprocess.run(cmd, cwd=VIZ_MV, env=dict(os.environ, CAMX_VIZ=VIZ_MV), stdout=lg, stderr=subprocess.STDOUT, check=True)
    with _OP_LOCK: OP.STRIDE = stride; OP.pack_one(proj, ds, ep, spec, OUT)
    m = json.load(open(os.path.join(d, 'meta.json'))); m.update(source_success_mtime=stamp(o['dataset']), render_seconds=round(time.time() - t0))
    json.dump(m, open(os.path.join(d, 'meta.json'), 'w'), indent=1)
    return f"{len(m['views'])} view(s), {m['n_frames']} frames, {m['render_seconds']}s"


def wait_pressure(limit=20.0):
    while True:
        try: some = float(open(PRESSURE).read().split('avg10=')[1].split()[0])
        except (OSError, IndexError, ValueError): return
        if some <= limit: return
        log(f'memory pressure some avg10={some:.1f} > {limit}: waiting'); time.sleep(30)


def render(rows, a):
    slots = queue.Queue()
    for i in range(a.jobs_rerun): slots.put(i + a.slot_offset)

    def run(o, r, x):
        d = os.path.join(OUT, o['key'], o['slug']); name = f"{o['key']}/{o['slug']}"
        try: provenance = render_provenance(o)
        except (OSError, ValueError, KeyError) as e:
            log(f'{r:8s} {name}: FAILED source provenance: {e!r}')
            return
        if current_cache(d, provenance) and not a.force: return
        os.makedirs(d, exist_ok=True)
        try: os.close(os.open(os.path.join(d, '_RENDERING'), os.O_CREAT | os.O_EXCL | os.O_WRONLY))   # another render process has it
        except FileExistsError: return
        Path(d, 'DONE.json').unlink(missing_ok=True); wait_pressure(); t0 = time.time()
        try:
            if r == 'reuse': msg = reuse_one(o, x, d, t0)
            elif r == 'fisheye': msg = fisheye_one(o, d, t0)
            elif r == 'multiview': msg = multiview_one(o, d, t0)
            else:
                slot = slots.get()
                try: msg = rerun_one(o, x, d, slot, t0)
                finally: slots.put(slot)
            # Do not bless a clip if another process changed an input mid-render.
            if render_provenance(o)['fingerprint'] != provenance['fingerprint']:
                Path(d, 'DONE.json').unlink(missing_ok=True)
                raise RuntimeError('render inputs changed during export; rerun this clip')
            meta_path = Path(d, 'meta.json')
            meta = json.loads(meta_path.read_text())
            meta['render_provenance'] = provenance
            meta_path.write_text(json.dumps(meta, indent=1))
            log(f'{r:8s} {name}: {msg}')
        except KeyboardInterrupt: raise
        except BaseException as e:  # noqa: BLE001 -- one failed clip must not stop the batch; the log names it (the viz helpers raise SystemExit)
            Path(d, 'DONE.json').unlink(missing_ok=True)
            log(f'{r:8s} {name}: FAILED {e!r}  (see {d}/_render.log)')
        finally: Path(d, '_RENDERING').unlink(missing_ok=True)

    todo = [(o, r, x) for o, r, x in rows if r != 'keep' and r in a.routes.split(',')]
    with ThreadPoolExecutor(a.jobs_rerun) as ex_r, ThreadPoolExecutor(a.jobs_fisheye) as ex_f:
        for o, r, x in todo: (ex_f if r in ('fisheye', 'multiview') else ex_r).submit(run, o, r, x)
    done = 0
    for o, _, _ in todo:
        try: done += current_cache(os.path.join(OUT, o['key'], o['slug']), render_provenance(o))
        except (OSError, ValueError, KeyError): pass
    log(f'{done}/{len(todo)} current clips in {OUT}')
    if done != len(todo): raise SystemExit(1)


def encode(rows):
    vdir, pdir = os.path.join(REPO, 'overlays', 'videos'), os.path.join(REPO, 'overlays', 'posters')
    for o, r, _ in rows:
        d = os.path.join(OUT, o['key'], o['slug']); name = f"{o['key']}__{o['slug']}"
        if r == 'keep': continue
        try: provenance = render_provenance(o)
        except (OSError, ValueError, KeyError) as e:
            log(f"skip encode {o['key']}/{o['slug']}: source unavailable: {e!r}")
            continue
        if not current_cache(d, provenance): continue
        mp4 = os.path.join(vdir, name + '.mp4'); src = os.path.join(d, 'stitched.mp4')
        if os.path.isfile(mp4) and os.path.getmtime(mp4) >= os.path.getmtime(src) and os.path.isfile(os.path.join(pdir, name + '.jpg')): continue
        subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', os.path.join(d, 'stitched.mp4'), '-vf', 'scale=-2:360', '-c:v', 'libx264',
                        '-preset', 'slow', '-crf', '28', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', mp4], check=True)
        _, _, rate, n = probe(mp4)
        subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{n / rate / 2:.3f}', '-i', mp4, '-frames:v', '1', '-vf', 'scale=-2:180', '-q:v', '6',
                        os.path.join(pdir, name + '.jpg')], check=True)
        log(f'{name}: {os.path.getsize(mp4) // 1024} KB, {n} frames')


def attach():
    """Rewrite the clip records of data/datasets.json from the tree, as tools/build_site_data.py builds them, plus the caption track."""
    sys.path.insert(0, HERE); import build_site_data as S
    path = os.path.join(REPO, 'data', 'datasets.json'); site = json.load(open(path)); n = 0
    for p in site['projects']:
        for i, o in enumerate(p['overlays']):
            d = os.path.join(OUT, o['key'], o['slug'])
            if proj_of(o) in KEEP: continue
            try: provenance = render_provenance(o)
            except (OSError, ValueError, KeyError) as e:
                log(f"skip attach {o['key']}/{o['slug']}: source unavailable: {e!r}")
                continue
            if not current_cache(d, provenance): continue
            m = json.load(open(os.path.join(d, 'meta.json'))); mp4 = os.path.join(REPO, 'overlays', 'videos', f"{o['key']}__{o['slug']}.mp4")
            grips = {s: {'model': g.get('model'), 'profile': g.get('profile'), 'urdf': bool(g.get('urdf_present'))} for s, g in (m.get('grippers') or {}).items() if g.get('model')}
            try: tasks = json.loads(m.get('tasks') or '[]')
            except ValueError: tasks = [m.get('tasks')]
            rec = {'key': o['key'], 'slug': o['slug'], 'dataset': m['dataset'], 'episode': m['episode_index'], 'task': (tasks or [''])[0],
                   'views': [v['name'] for v in m['views']], 'grippers': grips, 'mode': m.get('overlay_mode') or 'urdf', 'fisheye': bool(m.get('fisheye')),
                   'accept': m.get('accept') or 'unmeasured', 'export_id': m.get('source_export_id'), 'rendered_from': m.get('source_success_mtime'),
                   'render_fingerprint': m['render_provenance']['fingerprint'], 'render_built': m.get('built'),
                   'seconds': round((m.get('n_frames') or 0) / (m.get('out_fps') or OUT_FPS), 1),
                   'bytes': os.path.getsize(mp4) if os.path.isfile(mp4) else os.path.getsize(os.path.join(d, 'stitched.mp4'))}
            if any(g.get('standin') for g in (m.get('grippers') or {}).values()): rec['standin'] = sorted({g['profile'] for g in m['grippers'].values() if g.get('standin')})
            if proj_of(o) in OWN_ONLY: rec['own_only'] = True
            # the captions from the dataset's current data, as build_site_data.captions_pass: meta.json's `tasks` is a snapshot
            # from render time (stale once an annotation bank is re-expanded) and only stands in when the dataset cannot be read
            try: track = S.clip_captions(ROOT, rec['dataset'], int(rec['episode']), rec['seconds'])
            except (OSError, KeyError, ImportError) as e: track = o.get('captions'); print(f"warning: {rec['dataset']}: captions kept from the render tree ({e!r})", file=sys.stderr)
            else: rec['task'] = track[0][1]
            if track and len(track) > 1: rec['captions'] = track
            p['overlays'][i] = rec; n += 1
    json.dump(site, open(path, 'w'), separators=(',', ':'))
    log(f'{n} clip records rewritten in {path}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['plan', 'render', 'encode', 'attach'])
    ap.add_argument('--only', default=None, help='project key or slug substring (comma-separated alternatives)')
    ap.add_argument('--force', action='store_true', help='render: redo clips that have a DONE.json')
    ap.add_argument('--jobs-rerun', type=int, default=2, help='headless Rerun clips in parallel (each: 1 viewer per view, lavapipe)')
    ap.add_argument('--jobs-fisheye', type=int, default=3, help='OpenCV fisheye renders in parallel')
    ap.add_argument('--routes', default='reuse,rerun,fisheye,multiview', help='render: only clips of these routes')
    ap.add_argument('--slot-offset', type=int, default=0, help='render: first Rerun slot (viewer ports 9700 + 40 * slot); a second render process needs its own')
    a = ap.parse_args()
    if a.cmd == 'attach': attach(); return
    site = json.load(open(os.path.join(REPO, 'data', 'datasets.json')))
    ovs = [o for p in site['projects'] for o in p['overlays']]
    if a.only:
        alts = [x.strip() for x in a.only.split(',') if x.strip()]
        ovs = [o for o in ovs if any(x in f"{o['key']}__{o['slug']}" for x in alts)]
    rows = plan(ovs)
    if a.cmd == 'render': render(rows, a)
    elif a.cmd == 'encode': encode(rows)


if __name__ == '__main__':
    main()
