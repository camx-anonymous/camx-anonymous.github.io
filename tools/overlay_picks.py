#!/usr/bin/env python3
"""Example overlay clips rendered here (every project of the training tree; the shared render tree is no longer used).

Two renderers of the camera-cross-embodiment checkout are driven:
  * ``bimanual``  = render_bimanual_urdf_overlay_video.py  (right main | left main, fisheye tools; the DataClaw / GenRobot picks)
  * ``multiview`` = render_multiview_overlay_video.py      (every camera stream of the dataset through the world trajectories:
                    wrist, head, third and attached cameras; URDF from the gripper registry or the primitive stand-in)
Rigs without a URDF use the primitive profile: two fingers (or a bar) spanning the recorded jaw width behind the
tool-centre point, the tool-centre frame as RGB = xyz axes, camera markers. Rigs with a URDF get the URDF anchored at
their camera link or at the dataset's eef pose.

The output tree has the layout ``tools/build_site_data.py`` reads (point ``CAMX_OVERLAYS_EXTRA`` at ``--out``):
``<project_key>/<slug>/{stitched.mp4, stitched.png, stitched.json, poster.jpg, meta.json, DONE.json, _render.log}``.

Usage:
  python3 tools/overlay_picks.py list   [--only KEY]
  python3 tools/overlay_picks.py render --out <clips dir> [--only KEY] [--jobs 4] [--quick]   # --quick: 1 pick, 90 frames
  python3 tools/overlay_picks.py pack   --out <clips dir> [--only KEY]                          # meta.json + poster.jpg
  python3 tools/overlay_picks.py encode --out <clips dir> [--only KEY]                          # 360p mp4 (overlays/videos) + site poster
Env:
  CAMX_ROOT  camx_480p tree                                   (default /data/camx_480p)
  CAMX_VIZ   camera-cross-embodiment/camx/visualization       (default ~/projects/camera-cross-embodiment/camx/visualization)
  CAMX_PY    python for the renderers: cv2 4.x (5.0 mis-spaces the frame label), pyarrow >= 20, trimesh, yourdfpy,
             scipy, rerun-sdk                                  (default: this interpreter)
"""
import argparse, datetime, json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ROOT = os.environ.get('CAMX_ROOT', '/data/camx_480p')
VIZ = os.path.expanduser(os.environ.get('CAMX_VIZ', '~/projects/camera-cross-embodiment/camx/visualization'))
PY = os.environ.get('CAMX_PY', sys.executable)
BIMANUAL, MULTIVIEW = 'render_bimanual_urdf_overlay_video.py', 'render_multiview_overlay_video.py'
STRIDE, MAX_SEC, MAX_VIEWS = 3, 45, 4      # same clip budget as the shared tree: 10 fps, 45 s; at most 4 tiles per clip
PRIMITIVE_KINDS = {'primitive', 'openneo', 'hifi_umi', 'dataclaw', 'umi_benchmark', 'freetacman', 'dataclaw_primitives',
                   'hifi_umi_primitives', 'openneo_primitives', 'umi_benchmark_primitives', 'generic_primitives'}
GOPRO = 'gopro_hero9_maxlens_2_7k_umi.json:crop'   # UMI GoPro Hero 9/10 + Max Lens Mod, 2.7k 4:3 basis, centre-cropped to the square video

# ── the DataClaw / GenRobot picks (bimanual tool, kept from the first pass) ────────────────────────────────────────────
# DataClaw: no CAD / URDF in the release and no camera-to-TCP calibration, so the tool-centre pose in the main camera is
# the candidate from the converter notes (pad centre 0.12 m from the lens, 12.5 deg below the optical axis; checked on
# two openings of device R000153). Fingers hinge L = 0.100 / (2 sin 0.51) = 102 mm behind the pads (the encoder is the
# hinge angle). Lens: the device's own 1080p intrinsics as a Kannala-Brandt model without distortion terms.
DATACLAW = dict(tool=BIMANUAL, profile='dataclaw', mode='primitive', calib_fit='stretch', cross='off',
                extra=['--theta-max-deg', '73'], eef='0,0.0260,0.1172,0.5,0.5,-0.5,0.5',
                overlay='primitive stand-in (no URDF in the release): fingers hinged 102 mm behind the fingertip centre '
                        'spanning the recorded jaw width, bar between the tips, tool-centre axes (x red / y green / z blue); '
                        'Kannala-Brandt projection with the device intrinsics, tool-centre pose = the converter-notes candidate')
# GenRobot Gripper V4 collections: the DAS Gripper V4 URDF anchored at its camera link (the same profile as the 10Kh
# clips). The raw MCAP camera_info of these episodes is not at hand, so the lens is the rig-level mean of the 2026
# single-arm DAS unit (fx 247.5 in the 640 basis); the 10Kh lens (fx 299.5) does not fit these videos.
GENROBOT_V4 = dict(tool=BIMANUAL, profile='genrobot', mode='urdf', calib='genrobot_das_camera0_sewing_mean.json', calib_fit='stretch',
                   urdf='DAS_Gripper_V4/urdf/DAS_Gripper_V4.urdf', gripper_profile='genrobot_das_v4',
                   extra=['--own-exclude-visuals', 'base_link,link_imu,link_ca1,link_ca2,link_ca3', '--alpha', '0.45'],
                   overlay='DAS Gripper V4 URDF anchored at its camera link (own gripper; the other gripper through the two '
                           'world trajectories), Kannala-Brandt projection with the rig-level intrinsics of the 2026 '
                           'single-arm DAS unit')
EXPLICIT_PICKS = [  # (project, dataset, episode, spec)
    ('daimon/dataclaw', 'dag911262r000153_0325_185837', 0, dict(DATACLAW, calib='daimon_dataclaw_dag911262r000153.json')),
    ('daimon/dataclaw', 'dag911262r00207e_0324_214037', 0, dict(DATACLAW, calib='daimon_dataclaw_fleet_fallback.json')),
    ('daimon/dataclaw', 'dag911262r00207e_0324_214037', 400, dict(DATACLAW, calib='daimon_dataclaw_fleet_fallback.json')),
    ('genrobot/gripper_v4', 'cup_in_box', 7, dict(GENROBOT_V4, cross='off')),
    ('genrobot/gripper_v4', 'sewing_kit_assembly', 2, dict(GENROBOT_V4, cross='off')),
    ('genrobot/gripper_v4', 'jacket_folding', 3, dict(GENROBOT_V4, cross='on')),
]

# ── every other project without a clip: multi-view tool, 3 auto picks (3 datasets spread over the project, episode 0) ──
# spec keys: config (viz config in <VIZ>/config), calib {view-or-'main'-or-'all': 'file[:crop|stretch]'}, profile,
# hfov {view: deg}, eef {side: 'x,y,z,qw,qx,qy,qz'} (constant tool-centre pose in the main camera), eef_tcp {side: pose7 of the
# renderer TCP in the dataset eef frame: composed per episode with the dataset's <side>_eef_pose_in_main}, extra [args],
# views [names] (default: wrists first, then the rest, MAX_VIEWS)
def MV(**kw):
    return {'tool': MULTIVIEW, 'profile': 'auto', **kw}

RH20T = MV(config='rh20t.json')                       # per-episode intrinsics + per-episode eef in meta/episodes
OPENNEO = 'primitive stand-in (OpenNeoData publishes no gripper CAD): jaw bar + pads at the recorded width, tool-centre axes'
# OpenNeoData: the datasets' eef frames follow each arm's own convention (approach / camera-side axes differ per arm, ur and
# aloha eef = the flange), so the renderer's TCP frame (x approach, y jaw, z camera side) is passed explicitly: the values are
# inv(inv(T_eef_renderTCP) @ camera_in_eef) from camx/data_processing/openneo/scripts/render_wrist_overlay.py (checked on the
# wrist posters 2026-09-28: pads on the fingertips; arx5 needs no remap). Wrist lens = that script's assumed D405 / fx-306 models.
# flexiv / ur pass `eef_tcp` = T_eef_renderTCP (that script's FRAMES) instead of a constant: the tool-centre pose is then
# composed PER EPISODE from the dataset's own <side>_eef_pose_in_main (meta/episodes row or info.json). Flexiv needs that
# since 2026-09-28 (export openneo_4e8e8ac7): the wrist camera was re-mounted between recording sessions, so the eef pose
# is a per-episode column now; ur keeps a static info.json value (third_0 dropped the same day, wrist stream only).
NEO_D405 = {'main': 'openneo_wrist_d405_640x480_assumed.json:stretch'}
def NEO(config, eef, calib=NEO_D405, eef_tcp=None):
    return MV(config=config, profile='openneo', overlay=OPENNEO, calib=calib, eef=eef, eef_tcp=eef_tcp, extra=['--parallel-jaw'])
NEO_FLEXIV_TCP = {'right': '0,0,0,-0.707107,0,0.707107,0'}   # approach = eef z, camera side = -eef x, flange = TCP
NEO_UR_TCP = {'right': '0,0,0.105,0.5,0.5,-0.5,0.5'}         # approach = eef z, camera side = -eef y, TCP 105 mm past the flange
NEO_ALOHA_EEF = '0.008353,0.037243,0.106504,0.401352,0.604170,-0.592538,0.350419'
NEO_UMI_EEF = '0,0.010179,0.092753,0.346392,0.616452,-0.616452,0.346392'
SPECS = {
    'agibot/agibot_world_beta': MV(config='agibot_g1_beta.json'),                     # agibot g1 URDF, per-episode K + eef
    'aloha/aist_bimanip': MV(config='aist_bimanip.json'),                            # aloha1 URDF, config FOVs
    'aloha/aloha_lerobot': MV(config='aloha.json'),
    'aloha/openneo_aloha': NEO('openneo_aloha.json', {'left': NEO_ALOHA_EEF, 'right': NEO_ALOHA_EEF},
                               calib={'main': 'openneo_wrist_aloha_fx306_assumed.json:stretch'}),
    'aloha/openneo_arx5': NEO('openneo.json', None),
    'aloha/openneo_arx5_single': NEO('openneo_single.json', None),
    'aloha/robodojo': MV(config='robodojo.json'),                                    # piper x / arx x5 per dataset
    # RH20T cfg1-3: this tool's checkout has no AG-95 / WSG-50 profile, so it draws the primitive; the site clips come from
    # tools/rerun_clips.py (rerun route) with the vendor URDFs (grippers/dh_ag95, grippers/wsg50) since 2026-10-03
    'dahuan/rh20t_cfg1': dict(RH20T, profile='primitive'),
    'dahuan/rh20t_cfg2': dict(RH20T, profile='primitive'),
    'fastumi/fastumi': MV(calib={'main': GOPRO}, profile='umi'),                      # UMI gripper on an xArm, GoPro
    'fastumi/fastumi_100k_single_arm': MV(calib={'main': GOPRO}, profile='umi'),
    'flexiv/openneo_flexiv': NEO('openneo_flexiv.json', None, eef_tcp=NEO_FLEXIV_TCP),   # per-episode eef (re-mounted wrist camera)
    'franka_hand/fmb': MV(config='fmb.json'),                                        # franka hand URDF, anamorphic 256x256
    'franka_hand/rh20t_cfg5': RH20T,
    'hifi_umi/hifi_umi': MV(calib={'all': 'hifi_umi_hand_fisheye.json:stretch'}, profile='hifi_umi',
                            overlay='primitive stand-in (no CAD): hinged fingers spanning the recorded tip gap, tool-centre axes, '
                                    'camera markers; Kannala-Brandt hand-camera calibration'),
    'realman/realsource': MV(config='realsource.json'),                              # ctag2f90d URDF, per-episode K
    'robotiq/droid_lowres': MV(config='droid.json', hfov={'right_stereo_camera_left_rgb': 82.4, 'right_stereo_camera_right_rgb': 82.4,
                                                          'third_0_stereo_camera_left_rgb': 101.4, 'third_1_stereo_camera_left_rgb': 100.6}),
    'robotiq/rh20t_cfg4': RH20T, 'robotiq/rh20t_cfg6': RH20T, 'robotiq/rh20t_cfg7': RH20T,
    'robotiq/robomind_ur5': MV(config='robomind_ur5.json'),
    'robotiq/roboset_kinesthetic': MV(config='roboset_kinesthetic.json'),
    'robotiq/roboset_teleop': MV(config='roboset_teleop.json'),
    'stretch/dobbe': MV(config='dobbe.json'),                                        # dobbe stick URDF, calibrated iPhone FOV
    # AetheRock: no gripper CAD, no published lens and no camera-to-TCP lever arm (the release pose is the camera itself).
    # Lens = the fitted image circle read as a 190 deg equidistant fisheye; the tool centre is a CANDIDATE picked on the
    # wrist video (pads land on the orange fingertip rings at 45 mm ahead / 55 mm below the lens, 2026-09-28), not a fit.
    'umi/aetherock': MV(profile='primitive', calib={'main': 'aetherock_wrist_fisheye_assumed.json:stretch'},
                        eef={'right': '0,0.055,0.045,0.5,0.5,-0.5,0.5'},
                        overlay='primitive stand-in (no CAD): jaw bar + pads at the recorded width, tool-centre axes; assumed 190 deg '
                                'equidistant lens from the image circle, tool-centre pose = a candidate picked on the video'),
    'umi/data_scaling_laws': MV(calib={'main': GOPRO}),
    'umi/exumi': MV(calib={'main': GOPRO}),
    'umi/humi': MV(calib={'main': 'gopro_hero9_maxlens_2_7k_humi_g1_masked.json:crop'}),
    'umi/maniwav': MV(calib={'main': GOPRO}),
    'umi/openneo_umi': NEO('openneo_umi.json', {'left': NEO_UMI_EEF, 'right': NEO_UMI_EEF}),
    'umi/openneo_umi_single': NEO('openneo_umi_single.json', {'right': '0,0.006180,0.093105,0.333054,0.623759,-0.623759,0.333054'}),
    'umi/touch_in_the_wild': MV(calib={'main': GOPRO}),
    'umi/umi': MV(calib={'main': GOPRO}),
    # UMI-3D: its own URDF at the fisheye lens; the release's KB4 model (f 395.6 @1280x1024) scaled to the 224 crop; the
    # body meshes sit on the lens and would blanket the own view, so only the finger holders / soft fingers are drawn there
    'umi/umi3d': MV(calib={'main': 'umi3d_fisheye_kb4_release_crop_masked.json:stretch'}, profile='registry:umi3d',
                    extra=['--own-exclude-visuals', 'top_cover,fisheye_lens,bottom_plate,handle,battery,grip,gear_left,gear_right,linkage_left,linkage_right']),
    'umi/umi_benchmark': MV(calib={'main': 'umi_benchmark_fastumi_pro_seucm.json:crop'}, profile='umi_benchmark',
                            overlay='primitive stand-in (swing gripper, no CAD): bar spanning the recorded tip gap at the jaw midpoint, '
                                    'tool-centre axes; EUCM fisheye calibration'),
    'umi/umi_on_legs': MV(calib={'main': GOPRO}),
    'umi/vitamin': MV(calib={'main': 'gopro_hero9_maxlens_2_7k_umi_gripper_masked.json:crop'}, profile='umi'),
    # ViTaMIn-B: GoPro (webcam mode) masked to a circle; the 2.7k Max-Lens calibration centre-cropped to the square frame gives
    # f 88 px at 224 (the same focal the 1080p->224 resize implies), UMI paper-figure URDF hung from the GoPro lens
    'umi/vitamin_b': MV(calib={'main': GOPRO}, profile='umi'),
    'ur/openneo_ur': NEO('openneo_ur.json', None, eef_tcp=NEO_UR_TCP),                  # wrist stream only (third_0 dropped)
    'wsg50/rh20t_cfg3': dict(RH20T, profile='primitive'),                            # see dahuan/rh20t_cfg1
}


def key_of(project): return project.replace('/', '_')
def slug_of(dataset, ep): return f'{dataset}__ep{ep}'
def clip_dir(out, project, dataset, ep): return os.path.join(out, key_of(project), slug_of(dataset, ep))


def info_of(project, dataset):
    return json.load(open(os.path.join(ROOT, project, dataset, 'meta', 'info.json')))


def sides_of(info):  # renderer order: right main | left main
    return [s for s in ('right', 'left') if f'observation.image.{s}_main_camera_rgb' in info['features']]


MIN_SEC = 2.0   # auto picks skip episodes shorter than this (umi/vitamin_b cube_storage ep0 is 18 frames)


def episode_lengths(project, dataset):
    import glob
    import pyarrow.parquet as pq
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, project, dataset, 'meta', 'episodes', '**', '*.parquet'), recursive=True)):
        for r in pq.read_table(f, columns=['episode_index', 'length']).to_pylist():
            out[int(r['episode_index'])] = int(r['length'])
    return out


def long_episodes(project, dataset, min_sec=MIN_SEC):
    """Episode indices (ascending) at least min_sec long."""
    fps = float(info_of(project, dataset)['fps'])
    return [e for e, n in sorted(episode_lengths(project, dataset).items()) if n / fps >= min_sec]


def auto_picks(n=3):
    """Three (dataset, episode) picks per SPECS project: datasets spread over the project's sorted list, the first episode of
    each that is at least MIN_SEC long; projects with fewer datasets take further episodes of the first one."""
    site = json.load(open(os.path.join(REPO, 'data', 'datasets.json')))
    by_proj = {}
    for r in site['datasets']:
        by_proj.setdefault(r['project'], []).append(r)
    out = []
    for proj, spec in SPECS.items():
        rows = sorted((r for r in by_proj.get(proj, []) if os.path.isfile(os.path.join(ROOT, r['id'], 'meta', 'info.json'))), key=lambda r: r['id'])
        if not rows:
            print(f'[picks] {proj}: no dataset on disk', file=sys.stderr); continue
        idx = sorted({0, len(rows) // 2, len(rows) - 1})[:n]
        picks = []
        for i in idx:
            ds = rows[i]['id'].split('/', 2)[2]; eps = long_episodes(proj, ds)
            if eps: picks.append((ds, eps[0]))
        ds0 = rows[0]['id'].split('/', 2)[2]
        for e in long_episodes(proj, ds0)[1:]:
            if len(picks) >= n: break
            picks.append((ds0, e))
        out += [(proj, ds, e, spec) for ds, e in picks]
    return out


# ── the clips the shared render tree carried (2026-09-28: opaque grey Rerun meshes that hide the real gripper) ─────────
# Same datasets / episodes / slugs as that tree, re-rendered here with the translucent tinted meshes + tool-centre axes of
# every other clip. Lens sources as the shared tree used them: per-episode intrinsics from meta/episodes where the export
# carries them (agibot 2026, abc, robomind, iphumi, openarm, rby1, droid), else the viz config FOVs.
GENROBOT_10KH = dict(tool=BIMANUAL, profile='genrobot', mode='urdf', calib_fit='stretch', cross='on',
                     urdf='DAS_Gripper_V4/urdf/DAS_Gripper_V4.urdf', gripper_profile='genrobot_das_v4',
                     extra=['--own-exclude-visuals', 'base_link,link_imu,link_ca1,link_ca2,link_ca3', '--anchor-delta-xyz=0.0067,-0.0204,0.0142',
                            '--anchor-delta-rpy=0,0,0.042', '--width-scale', '0.94', '--alpha', '0.45'],
                     overlay='DAS Gripper V4 URDF anchored at its camera link (own gripper; the other gripper through the two world '
                             'trajectories), Kannala-Brandt projection with the per-episode camera_info of the 10Kh MCAPs')
def G10K(ds):   # the per-episode lens files of the 10Kh picks (calib/genrobot_episodes, from the MCAP camera_info)
    return dict(GENROBOT_10KH, calib_left=f'genrobot_episodes/{ds}_ep0_left.json', calib_right=f'genrobot_episodes/{ds}_ep0_right.json')
IPHUMI = MV(config='iphumi_bimanual.json')                     # per-episode K for the phone + attached streams; single-arm sets skip the absent side
UMIFT = MV(config='iphumi_bimanual.json', profile='umift')      # UMI-FT gripper (the info.json model string is the rig's, iPhUMI)
ROBOCOIN_CM, ROBOCOIN_GX = MV(config='robocoin_cobot_magic.json'), MV(config='robocoin_galaxea_r1_stereo.json')
# MV-UMI: the gripper GoPro only. The release also carries a second GoPro stream (right_third_camera_rgb) but its
# right_third_camera_pose_in_main is a constant identity-rotation placeholder 22 cm ahead of the lens, not a calibration
# (the view is a third-person camera looking at the gripper), so that view cannot be drawn and is left out.
MVUMI = MV(calib={'main': GOPRO}, views=['right_main_camera_rgb'])
# AgiBot G2: the registry anchors the gripper at its hand-eye-calibrated `camera_optical` link, which only the URDF copy in
# camx/data_processing/agibot/assets has (the tracked grippers/agibot_g2 tree is the 0906 rebuild without that link)
AGIBOT_G2_ASSETS = os.path.join(VIZ, '..', 'data_processing', 'agibot', 'assets')
AGIBOT_G2 = MV(config='agibot_g2.json', extra=[a for side in ('left', 'right')
                                                for a in ('--gripper-urdf', f'{side}={AGIBOT_G2_ASSETS}/agibot_g2_gripper_{side}.urdf')],
               overlay='AgiBot G2 90 mm gripper URDF (GenieSimAssets) anchored at its hand-eye-calibrated wrist-camera optical frame; '
                       'per-episode intrinsics of the release')
REPLACE_PICKS = [(p, ds, ep, spec) for p, spec, picks in [
    ('agibot/agibot_world_2026', AGIBOT_G2, [('il_3400', 9), ('ri_4560', 4), ('rl_7093', 3)]),
    # ABC: no gripper model string in the export; the YAM jaw type differs per task (i2rt flexible vs crank 4310), eef per episode
    ('aloha/abc', MV(config='abc_realsense.json', profile='registry:flexible'), [('assemble_a_carrot_with_lego_realsense', 11)]),
    ('aloha/abc', MV(config='abc_realsense.json', profile='registry:crank'), [('place_the_shirt_on_the_hanger_realsense', 6),
                                                                              ('zip_up_the_jacket_realsense', 11)]),
    ('aloha/biplay', MV(config='biplay.json'), [('dough_cut', 10), ('pick_place', 3), ('sushi_cut_full', 8)]),
    ('aloha/cosmos_policy', MV(config='aloha_cosmos_policy.json'), [('fold_shirt', 6), ('put_candies_in_bowl', 6), ('put_purple_eggplant_on_plate', 6)]),
    ('aloha/galaxea', MV(config='galaxea.json'), [('adjust_the_air_conditioner_temperature', 11), ('organize_trays', 2),
                                                  ('wipe_the_sewage_stains_with_a_ground_cloth', 11)]),
    ('aloha/molmoact_yam', MV(config='molmoact2_yam.json'), [('clean_dirty_plates_on_tray_and_stack_at_the_side', 2), ('rotate_4_blocks', 1),
                                                             ('untangle_cables', 5)]),
    ('aloha/rdt', MV(config='rdt.json'), [('airpods_on_second_layer', 8), ('pull_wet_wipe', 4), ('zip_the_bag', 2)]),
    ('aloha/robocoin', ROBOCOIN_GX, [('arrange_baai_then_brain_galaxea_r1_stereo', 4)]),
    ('aloha/robocoin', ROBOCOIN_CM, [('classify_objects_eight_cobot_magic', 11), ('water_bottle_storage_cobot_magic', 6)]),
    # RoboMIND: the export carries no gripper model string, so the registry key is given (Cobot Magic v2 = ARX5 jaws), eef per episode
    ('aloha/robomind', MV(config='robomind.json', profile='registry:cobot magic v2'), [('arrange_blocks_and_place_orange_in_center_with_arms', 3),
                                                    ('pour_seasoning_into_cup_on_scale_with_both_arms', 7), ('write_number_9_on_whiteboard', 3)]),
    ('aloha/xvla_softfold', MV(config='xvla_softfold.json'), [('fold_the_cloth', 1)]),
    ('iphumi/behavior_prompting', IPHUMI, [('fold_up', 6), ('left_arm_across_error_correction', 2), ('right_arm_across_error_correction', 4)]),
    ('iphumi/gated_memory_policy', IPHUMI, [('pick_and_place_back_all', 9), ('pick_and_place_back_and_correction', 4),
                                            ('pick_and_place_back_correction_all', 11)]),
    ('iphumi/hommi', IPHUMI, [('delivery', 10), ('laundry', 4), ('tablescape', 7)]),
    ('iphumi/mofpo', MV(config='iphumi_bimanual_and_head.json'), [('pouring', 12), ('pouring', 168), ('pouring', 5), ('serving', 7)]),
    ('iphumi/umift', UMIFT, [('lightbulb_insertion_clean_release', 10), ('whiteboard_wiping_addition', 9), ('whiteboard_wiping_wrist_overshoot', 0)]),
    ('openarm/openarm', MV(config='openarm.json'), [('full_folding', 7), ('high_quality_folding', 9)]),
    ('rby1/modpack', MV(config='rby1_modpack.json'), [('box_placing_together', 0), ('box_placing_together', 101), ('box_placing_together', 50)]),
    ('robotiq/droid', MV(config='droid.json'), [('AUTOLab_failure', 4), ('PennPAL_success', 1), ('WEIRD_success', 0)]),
    ('umi/mvumi', MVUMI, [('bottles_rack', 7), ('markers_placement', 6)]),
] for ds, ep in picks] + [('genrobot/10kh', ds, 0, G10K(ds)) for ds in ('clean_bowl', 'drawer_to_place_items', 'drawer_to_take_items')]


def all_picks():
    return EXPLICIT_PICKS + REPLACE_PICKS + auto_picks()


def views_for(info, spec):
    if spec.get('views'): return spec['views']
    cams = [k.split('observation.image.', 1)[1] for k, f in info['features'].items() if f.get('dtype') == 'video']
    pri = lambda n: (0 if n.startswith('right_main') else 1 if n.startswith('left_main') else 2 if 'main_camera' in n else 3)  # noqa: E731
    return sorted(cams, key=lambda n: (pri(n), cams.index(n)))[:MAX_VIEWS]


def render_cmd(project, dataset, ep, spec, out):
    info = info_of(project, dataset)
    d = clip_dir(out, project, dataset, ep)
    root = os.path.join(ROOT, project, dataset)
    if spec['tool'] == BIMANUAL:
        cmd = [PY, os.path.join(VIZ, BIMANUAL), '--dataset-root', root, '--episode', str(ep), '--profile', spec['profile'],
               '--calib-fit', spec['calib_fit'], '--cross', spec['cross'],
               '--stride', str(STRIDE), '--max-seconds', str(MAX_SEC), '--output', os.path.join(d, 'stitched.mp4')] + spec.get('extra', [])
        if spec.get('calib'): cmd += ['--calib', os.path.join(VIZ, 'calib', spec['calib'])]
        for side in ('left', 'right'):   # per-side (per-episode) lens files
            if spec.get(f'calib_{side}'): cmd += [f'--calib-{side}', os.path.join(VIZ, 'calib', spec[f'calib_{side}'])]
        if spec.get('eef'):
            for s in sides_of(info):
                cmd += ['--eef-pose-in-main', f'{s}={spec["eef"]}']
        return cmd
    cmd = [PY, os.path.join(VIZ, MULTIVIEW), '--dataset-root', root, '--episode', str(ep), '--profile', spec['profile'],
           '--views', ','.join(views_for(info, spec)), '--stride', str(STRIDE), '--max-seconds', str(MAX_SEC),
           '--output', os.path.join(d, 'stitched.mp4')]
    if spec.get('config'): cmd += ['--viz-config', os.path.join(VIZ, 'config', spec['config'])]
    for name, c in (spec.get('calib') or {}).items():
        path, _, fit = c.partition(':')
        cmd += ['--calib', f'{name}={os.path.join(VIZ, "calib", path)}' + (f':{fit}' if fit else '')]
    for name, deg in (spec.get('hfov') or {}).items(): cmd += ['--hfov', f'{name}={deg}']
    for side, pose in (spec.get('eef') or {}).items(): cmd += ['--eef-pose-in-main', f'{side}={pose}']
    for side, tcp in (spec.get('eef_tcp') or {}).items():   # dataset eef pose (per episode) remapped to the renderer's TCP frame
        pose = compose_pose7(episode_eef(project, dataset, ep, side), [float(v) for v in tcp.split(',')])
        cmd += ['--eef-pose-in-main', f'{side}=' + ','.join(f'{v:.6f}' for v in pose)]
    return cmd + spec.get('extra', [])


def render_one(project, dataset, ep, spec, out, quick=False):
    d = clip_dir(out, project, dataset, ep); os.makedirs(d, exist_ok=True)
    cmd = render_cmd(project, dataset, ep, spec, out)
    if quick: cmd += ['--max-frames', '90']
    with open(os.path.join(d, '_render.log'), 'w') as log:
        log.write(' '.join(cmd) + '\n'); log.flush()
        rc = subprocess.run(cmd, cwd=VIZ, stdout=log, stderr=subprocess.STDOUT).returncode
    lines = open(os.path.join(d, '_render.log')).read().strip().splitlines()
    tail = next((l for l in reversed(lines) if l.startswith('[done]') or 'Error' in l or 'SystemExit' in l), lines[-1] if lines else '')
    print(f'{key_of(project)}/{slug_of(dataset, ep)}: rc={rc} {tail[:140]}', flush=True)
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


def episode_eef(project, dataset, ep, side):
    """<side>_eef_pose_in_main_xyz_wxyz of one episode: info.json (static rigs) or the meta/episodes row (per-episode rigs)."""
    import glob
    import pyarrow.parquet as pq
    col = f'{side}_eef_pose_in_main_xyz_wxyz'
    info = info_of(project, dataset)
    if info.get(col): return [float(v) for v in info[col]]
    for f in sorted(glob.glob(os.path.join(ROOT, project, dataset, 'meta', 'episodes', '**', '*.parquet'), recursive=True)):
        t = pq.read_table(f)
        if col not in t.column_names: continue
        for r in t.select(['episode_index', col]).to_pylist():
            if int(r['episode_index']) == ep and r[col] is not None: return [float(v) for v in r[col]]
    raise SystemExit(f'{project}/{dataset} ep {ep}: no {col} in info.json or meta/episodes')


def compose_pose7(a, b):
    """pose7 (x,y,z,qw,qx,qy,qz) of T_a @ T_b (b expressed in a's frame)."""
    (ax, ay, az, aw, ai, aj, ak), (bx, by, bz, bw, bi, bj, bk) = a, b
    # rotate b's translation by a's quaternion: v' = v + 2 q_vec x (q_vec x v + w v)
    tx, ty, tz = aj * bz - ak * by + aw * bx, ak * bx - ai * bz + aw * by, ai * by - aj * bx + aw * bz
    rx, ry, rz = bx + 2 * (aj * tz - ak * ty), by + 2 * (ak * tx - ai * tz), bz + 2 * (ai * ty - aj * tx)
    qw = aw * bw - ai * bi - aj * bj - ak * bk
    qi = aw * bi + ai * bw + aj * bk - ak * bj
    qj = aw * bj - ai * bk + aj * bw + ak * bi
    qk = aw * bk + ai * bj - aj * bi + ak * bw
    return [ax + rx, ay + ry, az + rz, qw, qi, qj, qk]


def flat_tasks(v):
    """meta/episodes `tasks` as a flat list of strings (some converters store a JSON-encoded list inside the cell)."""
    out = []
    for t in (v if isinstance(v, list) else [v]):
        if isinstance(t, str) and t.startswith('['):
            try: t = json.loads(t)
            except ValueError: pass
        out += t if isinstance(t, list) else [t]
    return out


def pack_one(project, dataset, ep, spec, out, **_):
    d = clip_dir(out, project, dataset, ep); mp4 = os.path.join(d, 'stitched.mp4')
    if not os.path.isfile(mp4): print(f'{d}: no stitched.mp4 (render first)'); return
    info = info_of(project, dataset); row = episode_row(project, dataset, ep); fps = float(info['fps'])
    sides = sides_of(info); n = n_frames_of(mp4)
    summary = json.load(open(os.path.join(d, 'stitched.json'))) if os.path.isfile(os.path.join(d, 'stitched.json')) else {}
    view_names = summary.get('views') or [f'{s}_main_camera_rgb' for s in sides]
    kinds = summary.get('sides') or {s: spec.get('gripper_profile') or spec['profile'] for s in sides}
    sides = list(kinds)   # the renderer's sides (DROID's views are stereo eyes, not *_main_camera_rgb)
    prim_all = all(k in PRIMITIVE_KINDS for k in kinds.values())
    overlay = spec.get('overlay') or ('primitive stand-in (no URDF): jaw bar + pads at the recorded width, tool-centre axes, camera markers'
                                      if prim_all else ', '.join(sorted(set(kinds.values()))) + ' URDF anchored at its mount link or at the eef pose')
    calibs = summary.get('calib') or {}
    views = []; grips = {}
    for vn in view_names:
        key = f'observation.image.{vn}'; shape = info['features'][key]['shape']; c = calibs.get(vn, {})
        views.append({'name': vn, 'video_key': key, 'entity': None, 'w': int(shape[1]), 'h': int(shape[0]),
                      'focal_px': c.get('fx'), 'pinhole': c.get('model', 'kb4') == 'pinhole', 'fisheye': c.get('model', 'kb4') != 'pinhole',
                      'calib_source': c.get('source'), 'overlay': overlay})
    for s in sides:
        kind = kinds.get(s, spec['profile']); prim = kind in PRIMITIVE_KINDS
        grips[s] = {'model': info.get(f'{s}_gripper_model') or kind,   # ABC / RoboMIND exports carry no model string
                    'profile': kind, 'urdf': None if prim else spec.get('urdf') or kind,
                    'urdf_present': not prim, 'primitive': prim}
    mode = spec.get('mode') or ('primitive' if all(g['primitive'] for g in grips.values()) else 'urdf')
    tasks = flat_tasks(row['tasks'])
    cmd = render_cmd(project, dataset, ep, spec, out)
    meta = {'dataset': f'{project}/{dataset}', 'robot_type': info.get('robot_type'), 'fps': fps, 'config': spec['tool'],
            'episode_index': ep, 'length': int(row['length']), 'n_frames': n, 'step': STRIDE, 'out_fps': round(fps / STRIDE, 3),
            'tasks': json.dumps(tasks), 'views': views, 'grippers': grips, 'slug': slug_of(dataset, ep), 'project': project,
            'fisheye': any(v['fisheye'] for v in views), 'overlay_mode': mode, 'tool': spec['tool'],
            'args': [os.path.relpath(a, VIZ) if a.startswith(VIZ) else a for a in cmd[2:]],
            'source_export_id': None, 'source_success_mtime': None,
            'built': datetime.datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')}
    json.dump(meta, open(os.path.join(d, 'meta.json'), 'w'), indent=1)
    json.dump({'views': view_names, 'n_frames': n, 'out_fps': meta['out_fps'], 'fisheye': meta['fisheye'], 'tool': spec['tool'],
               'overlay_mode': mode}, open(os.path.join(d, 'DONE.json'), 'w'))
    png = os.path.join(d, 'stitched.png')  # the renderer's mid-clip poster (gripper in view); else frame 0
    src = ['-i', png] if os.path.isfile(png) else ['-ss', '0', '-i', mp4]
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error'] + src + ['-frames:v', '1', '-q:v', '4', os.path.join(d, 'poster.jpg')], check=True)
    print(f'{key_of(project)}/{slug_of(dataset, ep)}: {n} frames, {len(views)} view(s), mode {mode}, sides {kinds}')


def encode_one(project, dataset, ep, spec, out, **_):
    d = clip_dir(out, project, dataset, ep); name = f'{key_of(project)}__{slug_of(dataset, ep)}'
    if not os.path.isfile(os.path.join(d, 'poster.jpg')): print(f'{name}: not packed, skipped'); return
    vid_dir = os.path.join(REPO, 'overlays', 'videos'); os.makedirs(vid_dir, exist_ok=True)  # tracked: Pages serves them as video/mp4
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
    ap.add_argument('--only', default=None, help='project key or slug substring (comma-separated alternatives)')
    ap.add_argument('--skip', default=None, help='project key or slug substrings to leave out (comma-separated)')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--quick', action='store_true', help='render: first pick per project only, 90 frames')
    ap.add_argument('--force', action='store_true', help='render: redo picks that already have a [done] log')
    a = ap.parse_args()
    picks = all_picks()
    if a.only:
        alts = [x.strip() for x in a.only.split(',') if x.strip()]
        picks = [p for p in picks if any(x in key_of(p[0]) or x in slug_of(p[1], p[2]) for x in alts)]
    if a.skip:
        skips = [x.strip() for x in a.skip.split(',') if x.strip()]
        picks = [p for p in picks if not any(x in key_of(p[0]) or x in slug_of(p[1], p[2]) for x in skips)]
    if a.quick:
        seen = set(); picks = [p for p in picks if not (p[0] in seen or seen.add(p[0]))]
    if a.cmd == 'list':
        for p in picks: print(f'{key_of(p[0]):32s} {slug_of(p[1], p[2]):70s} {p[3]["tool"][:6]} {p[3]["profile"]}')
        print(len(picks), 'picks,', len({p[0] for p in picks}), 'projects'); return
    if not a.out: sys.exit('--out (or CAMX_OVERLAYS_EXTRA) is required')
    if a.cmd == 'render':
        if not a.force:
            def done(p):
                log = os.path.join(clip_dir(a.out, p[0], p[1], p[2]), '_render.log')
                return os.path.isfile(log) and '[done]' in open(log).read()[-3000:]
            skipped = [p for p in picks if done(p)]; picks = [p for p in picks if not done(p)]
            if skipped: print(f'{len(skipped)} picks already rendered (use --force to redo)')
        with ThreadPoolExecutor(a.jobs) as ex:
            list(ex.map(lambda p: render_one(*p, a.out, quick=a.quick), picks))
        return
    fn = {'pack': pack_one, 'encode': encode_one}[a.cmd]
    for p in picks: fn(*p, a.out)


if __name__ == '__main__':
    main()
