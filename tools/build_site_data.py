#!/usr/bin/env python3
"""Build data/datasets.json for the CAMX data manager site.

Sources (desktop001 only):
  * every LeRobot-v3 leaf under the canonical camx_480p namespace (meta/info.json)
  * camera-cross-embodiment/camx/figures/dataset_inventory.json  (embodiment / source / form factor / notes / 480p bytes)
  * camx_480p_browser/stats/stats.json                            (skills, episode-duration histogram, #instructions)
  * camx_480p_browser/mv_urdf/videos/<project>/<slug>/meta.json   (projection overlay clips)
  * data/pending.json (hand-maintained, in the repo): the sources of the paper's appendix tables with no converted data yet

Usage: python3 tools/build_site_data.py [--root /data/camx_480p]
       python3 tools/build_site_data.py --scrub-only   # re-run the anonymisation pass over data/datasets.json
       python3 tools/build_site_data.py --attach-samples-only   # merge the published one-episode samples
                                                                # ($CAMX_SAMPLES/{index,published}.jsonl) into it
       python3 tools/build_site_data.py --captions-only   # re-read the captions (--root): the caption tracks of the
                                                          # example clips, and data/captions.json for the records
       python3 tools/build_site_data.py --tasks-only      # re-read the task mix of every dataset (--root): rows' tm / title
The captions and the task mix need pyarrow (uv run --with pyarrow python tools/build_site_data.py); without it they are left out.
"""
import argparse, collections, glob, json, os, re, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
INVENTORY = os.path.expanduser(os.environ.get('CAMX_INVENTORY', '~/projects/camera-cross-embodiment/camx/figures/dataset_inventory.json'))
BROWSER = os.environ.get('CAMX_BROWSER', '/data/camx_480p_browser')
STATS = os.path.join(BROWSER, 'stats', 'stats.json')
OVERLAYS = os.path.join(BROWSER, 'mv_urdf', 'videos')
# Extra clip trees (colon-separated dirs laid out as <project_key>/<slug>/meta.json, e.g. the output of
# tools/overlay_picks.py): a project present in an extra tree REPLACES that project's clips from OVERLAYS.
OVERLAYS_EXTRA = [d for d in os.environ.get('CAMX_OVERLAYS_EXTRA', '').split(':') if d]

# --- anonymisation ---------------------------------------------------------------------------------------------
# The site is published anonymously: no author names, no institutions. Every string that reaches datasets.json goes
# through scrub_text(); dataset ids in ID_RENAMES are renamed (the HF download layout must use the same names).
# The term list is deliberately kept out of the repo: $CAMX_SCRUB (default .claude/scrub.json, gitignored) holds
#   {"replace": [[regex, replacement], ...], "renames": {"old/dataset/id": "new/dataset/id"}, "forbidden": regex}
SCRUB_FILE = os.environ.get('CAMX_SCRUB', os.path.join(REPO, '.claude', 'scrub.json'))
if os.path.isfile(SCRUB_FILE):
    _sc = json.load(open(SCRUB_FILE))
else:
    print(f'warning: {SCRUB_FILE} not found, anonymisation pass is a no-op', file=sys.stderr); _sc = {}
SCRUB = [tuple(x) for x in _sc.get('replace', [])]
ID_RENAMES = _sc.get('renames', {})
FORBIDDEN = re.compile(_sc.get('forbidden') or r'(?!x)x', re.I)


# Label fixes applied to every string (before the anonymisation pass): upstream metadata (inventory, info.json
# robot_type, stats platforms) still carries these spellings, so a rebuild must not bring them back.
LABEL_FIXES = [(r'RB-Y1m', 'RB-Y1'), (r'GenRobot DAS handheld gripper \(bimanual\)', 'GenRobot (bimanual)'),
               (r'real\.stanford\.edu/dexumi, ', '')]   # a lab domain in DexUMI's source_dataset: no institution names on the site


def scrub_text(s):
    for pat, rep in LABEL_FIXES: s = re.sub(pat, rep, s)
    for pat, rep in SCRUB: s = re.sub(pat, rep, s, flags=re.I)
    return s


def scrub(obj):
    if isinstance(obj, str): return scrub_text(obj)
    if isinstance(obj, list): return [scrub(x) for x in obj]
    if isinstance(obj, dict): return {scrub(k): scrub(v) for k, v in obj.items()}  # keys hold labels too (embodiments, platforms)
    return obj


def anonymise(out):
    out = scrub(out)
    out['root'] = os.path.basename(out.get('root', '').rstrip('/')) or 'camx_480p'
    for r in out['datasets']:
        if r['id'] in ID_RENAMES:
            r['id'] = ID_RENAMES[r['id']]; r['name'] = '/'.join(r['id'].split('/')[2:])
    hits = sorted({m.group(0).lower() for m in FORBIDDEN.finditer(json.dumps(out))})
    if hits: sys.exit(f'anonymisation failed, still present: {hits}')
    return out

# project (family/project) -> inventory "source"; projects spanning two embodiments resolve per leaf robot_type
SOURCE_OF = {
    'agibot/agibot_world_2026': 'AgiBot World 2026', 'agibot/agibot_world_beta': 'AgiBot World Beta',
    'aloha/abc': 'ABC', 'aloha/aist_bimanip': 'AIST Bimanual Manipulation', 'aloha/aloha_lerobot': 'ALOHA',
    'aloha/biplay': 'BiPlay', 'aloha/cosmos_policy': 'Cosmos Policy ALOHA', 'aloha/galaxea': 'Galaxea Open-World',
    'aloha/molmoact_yam': 'MolmoAct2 Bimanual YAM', 'aloha/openneo_aloha': 'OpenNeoData', 'aloha/openneo_arx5': 'OpenNeoData',
    'aloha/openneo_arx5_single': 'OpenNeoData', 'aloha/rdt': 'RDT', 'aloha/robocoin': 'RoboCOIN', 'aloha/robodojo': 'RoboDojo',
    'aloha/robomind': 'RoboMIND', 'aloha/xvla_softfold': 'XVLA-Soft-Fold',
    'dahuan/rh20t_cfg1': 'RH20T', 'dahuan/rh20t_cfg2': 'RH20T', 'daimon/dataclaw': 'DM-DataClaw',
    'fastumi/fastumi': 'FastUMI', 'fastumi/fastumi_100k_single_arm': 'FastUMI', 'flexiv/openneo_flexiv': 'OpenNeoData',
    'franka_hand/fmb': 'FMB', 'franka_hand/rh20t_cfg5': 'RH20T', 'genrobot/10kh': 'GenRobot 10Kh',
    'genrobot/gripper_v4': 'GenRobot Gripper V4 tasks', 'hifi_umi/hifi_umi': 'HiFi-UMI-2K',
    'iphumi/behavior_prompting': 'Behavior Prompting', 'iphumi/gated_memory_policy': 'Gated Memory Policy',
    'iphumi/hommi': 'HoMMI', 'iphumi/mofpo': 'MoFPO', 'iphumi/umift': 'UMIFT', 'openarm/openarm': 'OpenArm',
    'rby1/modpack': 'ModPack', 'realman/realsource': 'RealSource-World', 'robotiq/droid': 'DROID',
    'robotiq/droid_lowres': 'DROID', 'robotiq/rh20t_cfg4': 'RH20T', 'robotiq/rh20t_cfg6': 'RH20T', 'robotiq/rh20t_cfg7': 'RH20T',
    'robotiq/robomind_ur5': 'RoboMIND 2.0 UR', 'robotiq/roboset_kinesthetic': 'RoboSet', 'robotiq/roboset_teleop': 'RoboSet',
    'stretch/dobbe': 'Dobb-E Homes of New York', 'umi/aetherock': 'AetheRock', 'umi/data_scaling_laws': 'Data Scaling Laws',
    'umi/exumi': 'exUMI', 'umi/humi': 'HuMI', 'umi/maniwav': 'ManiWAV', 'umi/mvumi': 'MV-UMI', 'umi/openneo_umi': 'OpenNeoData',
    'umi/openneo_umi_single': 'OpenNeoData', 'umi/touch_in_the_wild': 'Touch in the Wild', 'umi/umi': 'UMI', 'umi/umi3d': 'UMI-3D',
    'umi/umi_benchmark': 'UMI-Benchmark', 'umi/umi_on_legs': 'UMI-on-Legs', 'umi/vitamin': 'ViTaMIn', 'umi/vitamin_b': 'ViTaMIn-B',
    'ur/openneo_ur': 'OpenNeoData', 'wsg50/rh20t_cfg3': 'RH20T',
    # the 2026-10-03 conversion pass of the sources the paper lists that had no data on the site (data/pending.json)
    'xarm/mint_xarm': 'Evo-1 xArm6', 'umi/vista_umi': 'Vista-UMI', 'aloha/aloha_lerobot_mobile': 'Mobile ALOHA',
    'fastumi/fastumi_100k_dual_arm': 'FastUMI-100K (dual-arm)', 'freetacman/freetacman': 'FreeTacMan', 'iphumi/muse': 'MuSe',
    'dexumi/dexumi': 'DexUMI', 'umi/tamen': 'TAMEn', 'xhand/dexora': 'Dexora', 'widowx/bridge_v2': 'Bridge V2',
    'franka_hand/molmoact': 'MolmoAct (Franka)', 'dexwild/dexwild': 'DexWild',
}
# dataset id -> source, where one collection spans two paper rows: openarm/openarm holds the three OpenArm datasets of the
# training mix (full_folding, high_quality_folding, pickplace) and the eight community uploads the paper lists as their
# own row (coordinating conversion session, 2026-10-03)
SOURCE_OF_DATASET = {f'openarm/openarm/{d}': 'OpenArm community' for d in (
    'blue_cube_to_bin', 'box_pick', 'grab_sth', 'mini_dual_camera_blue_sponge', 'pick_and_place', 'pick_and_place_clean',
    'tablewares_sort_merged', 'tape_to_box')}

# projects shown as one on the site: the leaf ids (and so the sample archives) keep their own path, but rows, the
# browse tree's source level, the overlays page and the project totals all fold the first into the second
PROJECT_MERGE = {'genrobot/gripper_v4': 'genrobot/10kh'}


def merge_projects(out):
    for r in out['datasets']:
        t = PROJECT_MERGE.get(r['project'])
        if t: r['project'] = t; r['source'] = SOURCE_OF.get(t, t.split('/')[1])
    by_key = {p['key']: p for p in out['projects']}
    for src, dst in PROJECT_MERGE.items():
        a, b = by_key.pop(src, None), by_key.get(dst)
        if not a or not b: continue
        for k in ('datasets', 'episodes', 'frames'): b[k] += a[k]
        b['hours'] = round(b['hours'] + a['hours'], 2)
        for k in ('embodiments', 'forms', 'views'):
            for kk, v in a[k].items(): b[k][kk] = b[k].get(kk, 0) + v
        for k in ('inventory_hours', 'inventory_bytes'):
            if a.get(k) and b.get(k): b[k] += a[k]
        b['overlays'] += a['overlays']
    out['projects'] = sorted(by_key.values(), key=lambda p: p['key'])
    out['totals']['projects'] = len(out['projects'])
    return out


# --- paper alignment -------------------------------------------------------------------------------------------
# The browse tree follows the source tables of the paper's appendix (tab:camx_sources, tab:camx_sources_held; user,
# 2026-10-02): the inventory files every hand-held rig under UMI and bands each leaf by its own form factor, the paper
# groups the hand-held rigs by hardware (UMI, iPhUMI, TacUMI, Other research projects, Dexterous hands) and keeps every
# embodiment inside one band. Rows keep their own `form`; only `embodiment` and `morph` change.
PAPER_EMBODIMENT = {  # (inventory embodiment, source) -> embodiment group of the paper
    ('UMI', 'Behavior Prompting'): 'iPhUMI', ('UMI', 'Gated Memory Policy'): 'iPhUMI', ('UMI', 'HoMMI'): 'iPhUMI',
    ('UMI', 'MoFPO'): 'iPhUMI', ('UMI', 'UMIFT'): 'iPhUMI',
    ('UMI', 'OpenNeoData'): 'TacUMI',
    ('UMI', 'Dobb-E Homes of New York'): 'Other research projects', ('UMI', 'AetheRock'): 'Other research projects',
}
PAPER_MORPH = {  # embodiment -> the band the paper lists it under (Galaxea RoboCOIN, RoboMIND 2.0 UR, single-arm ARX5 leaves)
    'Galaxea R1-Lite': 'Mobile manipulator', 'UR5': 'Single-arm robot', 'ARX5': 'Bimanual robot', 'OpenArm': 'Bimanual robot',
    # groups of the 2026-10-03 conversion pass (the morph column of data/pending.json)
    'xArm6': 'Single-arm robot', 'WidowX 250S': 'Single-arm robot', 'AIRBOT MMK2 + XHAND': 'Bimanual robot',
    'Dexterous hands': 'Handheld, robot-free', 'Other research projects': 'Handheld, robot-free', 'iPhUMI': 'Handheld, robot-free',
}
PENDING = os.path.join(REPO, 'data', 'pending.json')


def align_paper(out):
    for r in out['datasets']:
        r['embodiment'] = PAPER_EMBODIMENT.get((r['embodiment'], r['source']), r['embodiment'])
        r['morph'] = PAPER_MORPH.get(r['embodiment'], r['morph'])
    embs = collections.defaultdict(collections.Counter)
    for r in out['datasets']: embs[r['project']][r['embodiment']] += 1
    for p in out['projects']:
        if p['key'] in embs: p['embodiments'] = dict(embs[p['key']])
    out['totals']['embodiments'] = len({r['embodiment'] for r in out['datasets']})
    return out


def pending_pass(out):
    """data/pending.json: every source of the paper's tables that has no converted data on the site (no sample archive, no
    clip), with the paper's counts, copied into out['pending']; and the totals of the paper's two tables (`paper`), copied
    into totals['paper'] for the header and the footer of the site, which quote the paper and not the site's own sums."""
    out['pending'] = []; out['pending_notes'] = {}
    if not os.path.isfile(PENDING):
        print(f'warning: {PENDING} not found, the unconverted sources of the paper are not listed', file=sys.stderr); return out
    text = open(PENDING).read()
    hits = sorted({m.group(0).lower() for m in FORBIDDEN.finditer(text)})
    if hits: sys.exit(f'anonymisation failed in {PENDING}, still present: {hits}')
    j = json.loads(text)
    morphs = {m for _, m in MORPH_OF_FORM}
    for e in j['entries']:
        assert e['morph'] in morphs, e
        for k in ('embodiment', 'source', 'datasets', 'episodes', 'frames', 'hours', 'views', 'fps'): assert k in e, (k, e)
        assert e.get('note') in (None, *j['notes']), e
    out['pending'] = j['entries']; out['pending_notes'] = j['notes']
    conv = {(r['embodiment'], r['source']) for r in out['datasets']}
    pend = {(e['embodiment'], e['source']) for e in out['pending']}
    t = out['totals']
    t['embodiments_listed'] = len({r['embodiment'] for r in out['datasets']} | {e['embodiment'] for e in out['pending']})
    t['sources'] = len(conv | pend)  # table rows of the paper: one per embodiment and source
    t['pending'] = {'sources': len(out['pending']), 'datasets': sum(e['datasets'] for e in out['pending']),
                    'episodes': sum(e['episodes'] for e in out['pending']), 'hours': round(sum(e['hours'] for e in out['pending']), 1)}
    if j.get('paper'):
        t['paper'] = {k: j['paper'][k] for k in ('sources', 'embodiments', 'datasets', 'episodes', 'hours')}
        site = {'sources': t['sources'], 'embodiments': t['embodiments_listed'],
                **{k: round(t[k] + t['pending'][k], 1) for k in ('datasets', 'episodes', 'hours')}}
        for k, v in t['paper'].items():  # hours: the listed sources carry the tables' rounded hours, so allow half an hour
            if abs(site[k] - v) > (0.5 if k == 'hours' else 0):
                print(f'warning: {k}: the paper counts {v}, the site (converted + listed) {site[k]}', file=sys.stderr)
    print(f"{len(out['pending'])} unconverted sources listed from {os.path.relpath(PENDING, REPO)}; "
          f"{t['sources']} sources / {t['embodiments_listed']} embodiment groups in all", file=sys.stderr)
    return out


# robot_type (info.json) -> inventory embodiment; first regex that matches wins
EMBODIMENT_RULES = [
    (r'YAM', 'YAM'), (r'HiFi-UMI|SimpleAI UMI 4', 'HiFi-UMI'), (r'genrobot|GenRobot', 'GenRobot'),
    (r'DROID|FR3|Franka|Panda', 'Franka'), (r'Cobot Magic|ARX5|ARX X5', 'ARX5'), (r'Galaxea', 'Galaxea R1-Lite'),
    (r'AGIBOT|AgiBot', 'AgiBot'), (r'PiPER|Piper', 'AgileX PiPER'), (r'ALOHA|ViperX', 'ALOHA'), (r'OpenArm', 'OpenArm'),
    (r'UR5|UR7', 'UR5'), (r'KUKA', 'KUKA LBR iiwa'), (r'Flexiv', 'Flexiv Rizon 4'), (r'RealSource|RS-02', 'RealSource RS-02'),
    (r'RB-Y1|Rainbow', 'Rainbow RB-Y1'), (r'DataClaw', 'DataClaw'), (r'XARM', 'xArm'),
    (r'UMI|iPhUMI|FastUMI|Dobb-E|AetheRock|Vitamin|ViTaMIn|HuMI', 'UMI'),
]
MORPH_OF_FORM = [('handheld', 'Handheld, robot-free'), ('mobile', 'Mobile manipulator'),
                 ('bimanual', 'Bimanual robot'), ('single-arm', 'Single-arm robot')]
CAM_ROLE = [(r'wrist|hand|left_main|right_main|gripper|eef|cam_(left|right)|(^|_)(left|right)(_|$)', 'wrist'),
            (r'head|top|front|third|exterior|scene|neck|base|side|back|overhead|global|external|main', 'external')]


PROJECT_EMBODIMENT = {'fastumi/fastumi': 'UMI', 'fastumi/fastumi_100k_single_arm': 'UMI',  # inventory rolls FastUMI (XARM6 rows) into UMI
                      # paper table rows of the 2026-10-03 conversion pass (the embodiment column of data/pending.json)
                      'xarm/mint_xarm': 'xArm6', 'umi/vista_umi': 'UMI', 'aloha/aloha_lerobot_mobile': 'ALOHA',
                      'fastumi/fastumi_100k_dual_arm': 'UMI', 'freetacman/freetacman': 'Other research projects',
                      'iphumi/muse': 'iPhUMI', 'dexumi/dexumi': 'Dexterous hands', 'umi/tamen': 'Other research projects',
                      'xhand/dexora': 'AIRBOT MMK2 + XHAND', 'widowx/bridge_v2': 'WidowX 250S', 'franka_hand/molmoact': 'Franka',
                      'dexwild/dexwild': 'Dexterous hands'}


def embodiment_of(robot_type, project=None):
    if project in PROJECT_EMBODIMENT: return PROJECT_EMBODIMENT[project]
    for pat, emb in EMBODIMENT_RULES:
        if re.search(pat, robot_type or ''): return emb
    return robot_type or 'unknown'


def form_of(row, setup, robot_type, project):
    ff = (row or {}).get('form_factor') or ''
    if '/' in ff:  # row spans two form factors: pick by the leaf's setup
        parts = [p.strip() for p in ff.split('/')]
        want = 'bimanual' if setup == 'bimanual' else 'single-arm'
        ff = next((p for p in parts if want in p), parts[0])
    if not ff:
        hand = bool(re.search(r'UMI|handheld|DataClaw|Dobb|AetheRock|Vitamin|HuMI|genrobot|FreeTacMan|TAMEn|MuSe|DexWild', robot_type or '', re.I))
        ff = ('handheld (%s)' if hand else '%s (fixed base)') % ('bimanual' if setup == 'bimanual' else 'single-arm')
    return ff


def morph_of(ff):
    for key, m in MORPH_OF_FORM:
        if key in ff: return m
    return 'Single-arm robot'


def cam_role(name):
    for pat, role in CAM_ROLE:
        if re.search(pat, name, re.I): return role
    return 'other'


def overlay_metas():
    """meta.json paths of every example clip: the shared tree, then the CAMX_OVERLAYS_EXTRA trees project by project."""
    by_proj = {}
    for root in [OVERLAYS] + OVERLAYS_EXTRA:
        found = {}
        for m in sorted(glob.glob(os.path.join(root, '*', '*', 'meta.json'))):
            found.setdefault(m.split('/')[-3], []).append(m)
        by_proj.update(found)
    return [m for k in sorted(by_proj) for m in by_proj[k]]


def clip_captions(root, dataset, ep, seconds):
    """Captions of one example clip over time, [[start second, caption], ...], from the dataset's current data: the
    episode's per-frame task_index resolved through meta/tasks.parquet. One entry when a single caption covers the
    clip, several for an episode annotated per sub-task. The clip plays the episode's first `seconds` in real time.
    Alternate wordings of one caption stay '||'-joined inside the string."""
    import pyarrow.parquet as pq
    d = os.path.join(root, dataset); info = json.load(open(os.path.join(d, 'meta', 'info.json'))); want = [('episode_index', '=', ep)]
    for f in sorted(glob.glob(os.path.join(d, 'meta', 'episodes', '**', '*.parquet'), recursive=True)):
        rows = pq.read_table(f, columns=['data/chunk_index', 'data/file_index'], filters=want).to_pylist()
        if rows: break
    else: raise KeyError(f'episode {ep} not in meta/episodes')
    data = os.path.join(d, info['data_path'].format(chunk_index=rows[0]['data/chunk_index'], file_index=rows[0]['data/file_index']))
    t = pq.read_table(data, columns=['frame_index', 'task_index'], filters=want).sort_by('frame_index')
    names = {r['task_index']: r['task'] for r in pq.read_table(os.path.join(d, 'meta', 'tasks.parquet')).to_pylist()}
    track = []
    for fi, ti in zip(t['frame_index'].to_pylist(), t['task_index'].to_pylist()):
        if fi / info['fps'] >= seconds: break
        if not track or track[-1][1] != names[ti]: track.append([round(fi / info['fps'], 2), names[ti]])
    return track


def caption_track(root, dataset, ep, seconds):
    """clip_captions of an episode whose caption changes inside the clip; None when one caption covers it."""
    track = clip_captions(root, dataset, ep, seconds)
    return track if len(track) > 1 else None


def captions_pass(out, root):
    """The captions of every example clip, from the dataset's current data (clip_captions): o['task'], the caption at
    the start of the clip, and o['captions'], the whole track, on a clip whose caption changes while it plays. The
    render tree's meta.json `tasks` is a snapshot of the dataset at render time and goes stale when an annotation
    bank is re-expanded (RDT: 20 wordings at render time, 25 now), so it only stands in for a dataset that cannot be
    read here. The record's Caption row (dataset_captions) reads the same tasks.parquet, so the clip viewer, the
    overlays page and the record always agree."""
    try: import pyarrow.parquet  # noqa: F401
    except ImportError:
        print('warning: no pyarrow, the captions of the example clips not read', file=sys.stderr); return out
    back = {v: k for k, v in ID_RENAMES.items()}   # the clip records carry the renamed ids, the tree the original ones
    n = changed = 0
    for o in (o for p in out['projects'] for o in p['overlays']):
        try: track = clip_captions(root, back.get(o['dataset'], o['dataset']), int(o['episode']), o['seconds'])
        except (OSError, KeyError) as e:
            print(f"warning: {o['dataset']} ep {o['episode']}: captions not read, keeping the render-time task ({e!r})", file=sys.stderr); continue
        if not track: continue
        if o.get('task') != track[0][1]: changed += 1
        o['task'] = track[0][1]; o.pop('captions', None)
        if len(track) > 1: o['captions'] = track; n += 1
    print(f'{n} example clips with a caption track; {changed} clips whose task string differed from the render tree', file=sys.stderr)
    return out


CAPTIONS = os.path.join(REPO, 'data', 'captions.json')
CAPTION_TASKS = 3   # instructions of a dataset listed in data/captions.json; the rest is a count


def dataset_captions(out, root):
    """data/captions.json: the language annotations of every dataset for the Caption row of its record, keyed by the
    row's id: {"n": tasks in meta/tasks.parquet, "tasks": [the first CAPTION_TASKS by task_index, alternate wordings
    kept '||'-joined], "name": info.json task_name where there is one (AgiBot's task group over its sub-task labels)}.
    Its own file, fetched when the first record opens: the task strings of all datasets run to 13 MB (DROID lists
    every episode's instruction), too much for datasets.json. Goes through the anonymisation pass like the rest.
    Merges into the existing file: a row whose dataset is not readable under `root` keeps its entry (an incremental
    build against a tree that holds only the new leaves must not drop the others), ids no longer in `out` go."""
    try: import pyarrow.parquet as pq
    except ImportError:
        print(f'warning: no pyarrow, {os.path.relpath(CAPTIONS, REPO)} not written', file=sys.stderr); return
    back = {v: k for k, v in ID_RENAMES.items()}   # the rows carry the renamed ids, the tree the original ones
    old = json.load(open(CAPTIONS)) if os.path.isfile(CAPTIONS) else {}
    caps = {}; kept = []
    for r in out['datasets']:
        d = os.path.join(root, back.get(r['id'], r['id']), 'meta')
        try:
            tasks = pq.read_table(os.path.join(d, 'tasks.parquet'), columns=['task_index', 'task']).sort_by('task_index').column('task').to_pylist()
            name = json.load(open(os.path.join(d, 'info.json'))).get('task_name')
        except OSError as e:
            if r['id'] in old: caps[r['id']] = old[r['id']]; kept.append(r['id'])
            else: print(f"warning: {r['id']}: captions not read, no entry ({e!r})", file=sys.stderr)
            continue
        e = {'n': len(tasks), 'tasks': [str(t) for t in tasks[:CAPTION_TASKS]]}
        if name: e['name'] = str(name)
        caps[r['id']] = scrub(e)
    hits = sorted({m.group(0).lower() for m in FORBIDDEN.finditer(json.dumps(caps))})
    if hits: sys.exit(f'anonymisation failed in the captions, still present: {hits}')
    json.dump(caps, open(CAPTIONS, 'w'), separators=(',', ':'))
    print(f'{len(caps)} datasets -> {os.path.relpath(CAPTIONS, REPO)} ({os.path.getsize(CAPTIONS) // 1024} KB)'
          + (f'; {len(kept)} not under {root}, entries kept from the previous file' if kept else ''), file=sys.stderr)


# --- task mix of every dataset ----------------------------------------------------------------------------------
# Skill taxonomy of the curation site's stats page (cam_uva/scripts/monitor/camx_stats_page/skills.py): the first verb of
# the first wording of a caption names its skill class. Copied so the per-dataset task mix uses the same classes as the
# project skill histograms that stats.json brings in.
SKILLS = {
    'pick / grasp': 'pick grasp grab take retrieve lift get collect gather hold grip catch fetch raise elevate pickup',
    'place / put': 'place put set deposit position load store return drop lower release',
    'move / carry / hand over': 'move carry transfer transport bring deliver pass hand shift relocate slide swap exchange',
    'open': 'open uncap unzip unlock unscrew lift-lid',
    'close': 'close shut cover zip lock screw-on',
    'fold / unfold': 'fold unfold spread flatten smooth roll layout lay straighten wrap',
    'pour / scoop / fill': 'pour fill empty drain scoop spoon serve dispense squeeze',
    'wipe / clean / sweep': 'wipe clean mop sweep scrub brush dust wash rinse dry',
    'stack / arrange / sort': 'stack arrange organize organise sort tidy align line group separate unstack neatly assemble reassemble pack unpack',
    'insert / plug / attach': 'insert plug peg thread attach connect mount install hang hook fit clip',
    'push / press / toggle': 'push press poke tap toggle switch',
    'pull / remove / detach': 'pull drag tug extract unplug detach remove unwrap peel tear disassemble take-off',
    'rotate / turn / flip': 'rotate turn tilt flip twist spin invert orient adjust reorient',
    'cut / slice': 'cut slice chop',
    'toss / throw': 'toss throw tossing throwing',
    'stir / cook / prepare': 'stir mix whisk brew cook steam toast make bake heat microwave prepare cooking',
    'write / draw / point': 'write draw point scan',
    'walk / navigate': 'walk navigate go approach come drive',
    'unlabeled / play': 'unlabeled unlabelled unknown random play no-action',
}
_SKILL_WORD = {w: k for k, ws in SKILLS.items() for w in ws.split()}


def skill_of(t):
    t = (t or '').split('||')[0].lower()
    if t.strip() in ('no action', 'no-action'): return 'unlabeled / play'
    toks = re.findall(r'[a-z]+', t.replace('_', ' '))
    for i, w in enumerate(toks):
        if w in _SKILL_WORD: return _SKILL_WORD[w]
        if w.endswith('ing') and w[:-3] in _SKILL_WORD: return _SKILL_WORD[w[:-3]]
        if w.endswith('ing') and w[:-3] + 'e' in _SKILL_WORD: return _SKILL_WORD[w[:-3] + 'e']
        if w.endswith('s') and w[:-1] in _SKILL_WORD and i == 0: return _SKILL_WORD[w[:-1]]
    return 'other'


MIX_TOP = 4   # most frequent captions kept per mixed / steps dataset


def task_mix(root, dataset):
    """How the episodes of one dataset divide into tasks, from the `tasks` list of every episode (meta/episodes):
      single  one task: every episode carries the same caption (the dataset is split by task, like most of the site),
      mixed   several tasks: one caption per episode, differing between episodes (the DROID lab splits, BiPlay, RoboCOIN),
      steps   one task annotated per sub-task: several captions per episode (AgiBot World, Galaxea, MolmoAct).
    Returns None for a single-task dataset (its name and Caption row already say what it is), else
    {kind, eps, per_ep: median captions per episode, n_task: distinct episode-level captions, n_step: distinct sub-task
    captions (steps), skills: [[class, n], ...] (per episode for mixed, per sub-task caption for steps), top: the MIX_TOP
    most frequent captions with their counts}. Alternate wordings of a caption ('||'-joined) count as one wording."""
    import pyarrow.parquet as pq
    files = sorted(glob.glob(os.path.join(root, dataset, 'meta', 'episodes', '**', '*.parquet'), recursive=True))
    if not files: raise KeyError('no meta/episodes')
    first = lambda c: (c or '').split('||')[0].strip()
    eps = 0; per = []; ep_task = collections.Counter(); steps = collections.Counter()
    for f in files:
        for s in pq.read_table(f, columns=['tasks']).column('tasks').to_pylist():
            try: caps = json.loads(s) if isinstance(s, str) else list(s or [])
            except ValueError: caps = [s]
            caps = [first(c) for c in caps if c]
            if not caps: continue
            eps += 1; per.append(len(caps)); ep_task[caps[0]] += 1
            for c in caps: steps[c] += 1
    if not eps: raise KeyError('no episode with a caption')
    per.sort(); per_ep = per[len(per) // 2]
    kind = 'steps' if per_ep > 1 else 'mixed' if len(ep_task) > 1 else 'single'
    if kind == 'single': return None
    src = steps if kind == 'steps' else ep_task
    sk = collections.Counter()
    for c, n in src.items(): sk[skill_of(c)] += n
    out = {'kind': kind, 'eps': eps, 'per_ep': per_ep, 'n_task': len(ep_task),
           'skills': [[k, n] for k, n in sk.most_common()], 'top': [[c if len(c) <= 120 else c[:119].rstrip() + '…', n] for c, n in src.most_common(MIX_TOP)]}
    if kind == 'steps': out['n_step'] = len(steps)
    return out


def tasks_pass(out, root, rows=None):
    """r['tm'] (task_mix) on every dataset row that holds more than one task, and r['title'] from the dataset's
    info.json `task_name` where the converter wrote one (AgiBot World, whose dataset ids are opaque numbers); the cards
    and the record show the title over the id. A dataset that cannot be read keeps what it had. `rows`: only these
    rows of out['datasets'] (the --add path), default all."""
    try: import pyarrow.parquet  # noqa: F401
    except ImportError:
        print('warning: no pyarrow, task mix of the datasets not read', file=sys.stderr); return out
    back = {v: k for k, v in ID_RENAMES.items()}   # the rows carry the renamed ids, the tree the original ones
    kinds = collections.Counter()
    for r in (out['datasets'] if rows is None else rows):
        rel = back.get(r['id'], r['id'])
        try: info = json.load(open(os.path.join(root, rel, 'meta', 'info.json')))
        except (OSError, ValueError): info = {}
        tn = str(info.get('task_name') or '').strip().rstrip('.')
        if tn and tn.lower() != r['name'].replace('_', ' ').lower(): r['title'] = tn
        else: r.pop('title', None)
        try: tm = task_mix(root, rel)
        except (OSError, KeyError) as e:
            print(f"warning: {r['id']}: task mix not read ({e!r})", file=sys.stderr); continue
        r.pop('tm', None)
        if tm: r['tm'] = tm
        kinds[tm['kind'] if tm else 'single'] += 1
    print(f'task mix of {sum(kinds.values())} of {len(out["datasets"])} datasets: {dict(kinds)}', file=sys.stderr)
    return out


def scan_leaves(root):
    out = []
    def walk(d, depth):
        if depth > 6: return
        try: ents = os.listdir(d)
        except Exception: return
        if 'meta' in ents and os.path.isfile(os.path.join(d, 'meta', 'info.json')):
            out.append(d); return
        for e in sorted(ents):
            if e.startswith(('.', '_')) or e in ('videos', 'data'): continue
            p = os.path.join(d, e)
            if os.path.isdir(p): walk(p, depth + 1)
    walk(root, 0)
    return out


SAMPLES = os.environ.get('CAMX_SAMPLES', '/data/camx_samples')
RELEASES = 'https://github.com/camx-anonymous/camx-anonymous.github.io/releases'
SITE = 'https://camx-anonymous.github.io/'
DOWNLOAD = {'samples': RELEASES, 'sample_episode': 0, 'layout': '<family>/<project>/<dataset>/{meta,data,videos}',
            'citations': SITE + 'data/citations.bib'}

# --- sources: license + papers of every source dataset (hand-maintained data/sources.json) ---------------------------
# {"sources": {"<source label>": {"homepage", "license": {"name", "url", "repo"} | null, "papers": [{"key", "title", "year",
#  "arxiv", "url", "bibtex"}]}}, "projects": {"family/project": "<label>"}, "datasets": {"<row id>": "<label>"}}, keyed by
# the inventory "source" label that every row carries (SOURCE_OF); license.url is the license text and license.repo the page
# that states the license (the dataset's Hugging Face / ModelScope repository, else the project's GitHub repository, else the
# UMI Data Initiative listing), which the site's license chips link to; "projects" / "datasets" point rows at a more
# specific entry where one source ships under two licenses (FastUMI-100K, RH20T cfg 6-7, the Apache-2.0 ALOHA repos). The site
# shows them in the dataset record and in the download gate (cite + license confirmation); this script checks that
# every source has an entry and no forbidden term, and writes data/citations.bib (CAMX + every source paper).
SOURCES = os.path.join(REPO, 'data', 'sources.json')
BIB = os.path.join(REPO, 'data', 'citations.bib')
CAMX_BIB = '''@misc{camx2026,
  title  = {CAMX: A Camera-Aware Cross-Embodiment Dataset},
  author = {Anonymous Authors},
  year   = {2026},
  note   = {Under review}
}'''


def sources_pass(out):
    out['download'] = dict(DOWNLOAD)
    if not os.path.isfile(SOURCES):
        print(f'warning: {SOURCES} not found, no licenses / citations on the site', file=sys.stderr); return out
    text = open(SOURCES).read()
    hits = sorted({m.group(0).lower() for m in FORBIDDEN.finditer(text)})
    if hits: sys.exit(f'anonymisation failed in {SOURCES}, still present: {hits}')
    j = json.loads(text); src = j['sources']; proj = j.get('projects', {}); ds = j.get('datasets', {})
    used = collections.Counter(ds.get(r['id'], proj.get(r['project'], r['source'])) for r in out['datasets'])
    for e in out.get('pending', []): used[e.get('entry') or e['source']] += 1
    missing = sorted(k for k in used if k not in src)
    if missing: print(f'warning: {len(missing)} sources without an entry in data/sources.json: {missing}', file=sys.stderr)
    unused = sorted(k for k in src if k not in used)
    if unused: print(f'warning: sources.json entries no dataset uses: {unused}', file=sys.stderr)
    for k, v in src.items():
        if not v.get('license'): print(f'warning: {k}: license not stated', file=sys.stderr)
        elif not v['license'].get('repo'): print(f'warning: {k}: license without the page that states it (license.repo)', file=sys.stderr)
        if not v.get('papers'): print(f'warning: {k}: no paper listed', file=sys.stderr)
    lines = ['% CAMX one-episode samples: CAMX plus every source dataset it re-exports.',
             '% Each source keeps its own license; see data/sources.json or the record of each dataset on the site.', '', CAMX_BIB]
    seen = set()
    for k in sorted(src, key=str.lower):
        for pp in src[k].get('papers') or []:
            if pp['key'] in seen: continue
            seen.add(pp['key'])
            lic = (src[k].get('license') or {}).get('name')
            lines += ['', f'% {k}' + (f' · {lic}' if lic else ''), pp['bibtex'].strip()]
    open(BIB, 'w').write('\n'.join(lines) + '\n')
    print(f'{len(src)} sources, {len(seen)} source papers -> {os.path.relpath(BIB, REPO)}', file=sys.stderr)
    return out




def attach_samples(out, samples_dir):
    """Merge the one-episode sample archives (tools/build_samples.py + tools/publish_samples.py) into the rows:
    r['sample'] = {url, bytes, frames, seconds} for every dataset whose archive is on a GitHub release."""
    idx = {}
    for name in ('index.jsonl', 'published.jsonl'):
        p = os.path.join(samples_dir, name)
        if not os.path.exists(p): print(f'warning: {p} not found, no samples attached', file=sys.stderr); return out
        for line in open(p):
            r = json.loads(line); idx.setdefault(r['id'], {}).update(r)
    n = 0
    for r in out['datasets']:
        s = idx.get(r['id'])
        r['sample'] = None
        if s and s.get('ok') and s.get('url'):
            r['sample'] = {'url': s['url'], 'bytes': s['bytes'], 'frames': s['frames'], 'seconds': s['seconds']}; n += 1
    out['totals']['samples'] = n
    print(f'{n} of {len(out["datasets"])} datasets have a published sample', file=sys.stderr)
    return out


def leaf_row(root, p, inv_rows):
    """The dataset row of one leaf (a folder with meta/info.json) of the camx_480p tree."""
    rel = p[len(root.rstrip('/')) + 1:]
    family, project = rel.split('/')[:2]
    pk = f'{family}/{project}'
    d = json.load(open(os.path.join(p, 'meta', 'info.json')))
    feat = d.get('features', {})
    cams = []
    for k, v in feat.items():
        if v.get('dtype') != 'video': continue
        name = k.split('.')[-1]; base = name.replace('_rgb', '')
        g = lambda suf: d.get(base + suf, d.get(name + suf))
        shape = v.get('shape') or [None, None, None]
        cams.append({'name': name, 'h': shape[0], 'w': shape[1], 'model': g('_model'),
                     'fisheye': bool(g('_is_fisheye')), 'role': cam_role(name)})
    fps = float(d.get('fps') or 0)
    frames = int(d.get('total_frames') or 0)
    eps = int(d.get('total_episodes') or 0)
    rt = d.get('robot_type') or ''
    setup = d.get('robot_setup_type') or ('bimanual' if 'bimanual' in rt.lower() else 'single_arm')
    emb = embodiment_of(rt, pk)
    src = SOURCE_OF_DATASET.get(rel) or SOURCE_OF.get(pk, project)
    row = inv_rows.get((emb, src))
    ff = form_of(row, setup, rt, pk)
    state = [k for k in feat if k.startswith('observation.state')]
    has_eef = any('trajectory' in k or 'eef' in k or 'pose' in k for k in state)
    has_joint = any('joint' in k for k in state)
    has_grip = any('gripper' in k for k in state)
    # samples-first conversion (2026-10-03): the converter kept one episode per dataset and stamped the rest as pending;
    # the row carries that episode's counts and `partial`, the record says so, the paper's counts stay in data/pending.json
    partial = d.get('camx_partial_export')
    # ... with `source_totals: {episodes, frames}` (read from the raw release, no transcode) the row shows the dataset's
    # true size, the site being a browser of samples: episode 0 is what it serves either way (user, 2026-10-03)
    tot = (partial or {}).get('source_totals') or {}
    if tot.get('episodes') and tot.get('frames'): eps, frames = int(tot['episodes']), int(tot['frames'])
    return {**({'partial': partial} if partial else {}),
        'id': rel, 'family': family, 'project': pk, 'name': '/'.join(rel.split('/')[2:]),
        'embodiment': emb, 'source': src, 'robot_type': rt, 'setup': setup, 'form': ff, 'morph': morph_of(ff),
        'episodes': eps, 'frames': frames, 'fps': round(fps, 2), 'hours': round(frames / fps / 3600, 3) if fps else 0,
        'tasks': int(d.get('total_tasks') or 0), 'cams': cams, 'n_views': len(cams),
        'fisheye': any(c['fisheye'] for c in cams), 'wrist': sum(c['role'] == 'wrist' for c in cams),
        'external': sum(c['role'] == 'external' for c in cams),
        'res': sorted({f"{c['w']}x{c['h']}" for c in cams if c['w']}),
        'fk_urdf': d.get('fk_urdf'), 'eef': has_eef, 'joints': has_joint, 'gripper': has_grip,
        'export_id': (d.get('camx_export') or {}).get('export_id'),
        'released': os.path.exists(os.path.join(p, 'meta', '_SUCCESS')),
        'quality': os.path.isdir(os.path.join(p, 'meta', 'quality')),
        'mobile': 'mobile' in ff,
        'station': d.get('station_type'), 'source_dataset': d.get('source_dataset'),
    }


def size_estimates(rows, inv_rows):
    """r['bytes_est']: the inventory row's bytes shared among its leaves by frames (None without an inventory row)."""
    by_row = collections.defaultdict(list)
    for r in rows: by_row[(r['embodiment'], r['source'])].append(r)
    for key, rs in by_row.items():
        row = inv_rows.get(key)
        tot = ((row or {}).get('size') or {}).get('total_bytes')
        fr = sum(r['frames'] for r in rs)
        for r in rs:
            r['bytes_est'] = int(tot * r['frames'] / fr) if tot and fr else None


def build_projects(rows, stats, inv_rows):
    """The project records (one per family/project of the rows) with empty overlay lists."""
    projects = {}
    for r in rows:
        pj = projects.setdefault(r['project'], {'key': r['project'], 'family': r['family'], 'datasets': 0, 'episodes': 0,
                                                'frames': 0, 'hours': 0.0, 'embodiments': collections.Counter(),
                                                'sources': set(), 'forms': collections.Counter(), 'views': collections.Counter()})
        pj['datasets'] += 1; pj['episodes'] += r['episodes']; pj['frames'] += r['frames']; pj['hours'] += r['hours']
        pj['embodiments'][r['embodiment']] += 1; pj['sources'].add(r['source']); pj['forms'][r['form']] += 1
        pj['views'][r['n_views']] += r['episodes']
    for k, pj in projects.items():
        st = stats['by_project'].get(k) or {}
        emb = pj['embodiments'].most_common(1)[0][0]
        src = sorted(pj['sources'])[0]
        row = inv_rows.get((emb, src)) or {}
        pj.update({'embodiments': dict(pj['embodiments']), 'sources': sorted(pj['sources']), 'forms': dict(pj['forms']),
                   'views': dict(pj['views']), 'hours': round(pj['hours'], 2),
                   'skills': st.get('skills'), 'dur_hist': st.get('dur_hist'), 'median_s': st.get('median_s'),
                   'n_instr': st.get('n_instr'), 'platforms': st.get('platforms'), 'notes': row.get('notes'),
                   'inventory_hours': row.get('hours'), 'inventory_bytes': (row.get('size') or {}).get('total_bytes'),
                   'overlays': []})
    return projects


def overlay_records(metas):
    """(project key, clip record) of every meta.json of the clip trees, as the site's projects[].overlays carry them."""
    out = []
    for m in metas:
        d = json.load(open(m)); pkey, slug = m.split('/')[-3:-1]
        st = os.path.join(os.path.dirname(m), 'stitched.mp4')
        grips = {s: {'model': g.get('model'), 'profile': g.get('profile'), 'urdf': bool(g.get('urdf_present'))}
                 for s, g in (d.get('grippers') or {}).items() if g.get('model')}
        # overlay_mode is written by tools/overlay_picks.py ('primitive' = hinged stand-in fingers + TCP axes for rigs
        # without a URDF); the shared tree's meta.json has no such field, so fall back on the gripper profiles.
        mode = d.get('overlay_mode') or ('urdf' if any(g['urdf'] for g in grips.values()) else ('camera-path' if 'dataclaw' in pkey else 'none'))
        try: tasks = json.loads(d.get('tasks') or '[]')
        except Exception: tasks = [d.get('tasks')]
        rec = {'key': pkey, 'slug': slug, 'dataset': d.get('dataset'), 'episode': d.get('episode_index'),
               'task': (tasks or [''])[0], 'views': [v['name'] for v in d.get('views', [])], 'grippers': grips, 'mode': mode,
               'fisheye': bool(d.get('fisheye')), 'accept': d.get('accept') or 'unmeasured',
               'export_id': d.get('source_export_id'), 'rendered_from': d.get('source_success_mtime'),
               'seconds': round((d.get('n_frames') or 0) / (d.get('out_fps') or 10), 1),
               'bytes': os.path.getsize(st) if os.path.exists(st) else 0}
        if any(g.get('standin') for g in (d.get('grippers') or {}).values()):
            rec['standin'] = sorted({g['profile'] for g in d['grippers'].values() if g.get('standin')})
        out.append((d.get('project'), rec))
    return out


def retotal(out):
    rows, projects = out['datasets'], out['projects']
    out['totals'].update({'datasets': len(rows), 'projects': len(projects), 'episodes': sum(r['episodes'] for r in rows),
                          'frames': sum(r['frames'] for r in rows), 'hours': round(sum(r['hours'] for r in rows), 1),
                          'embodiments': len({r['embodiment'] for r in rows}), 'overlays': sum(len(p['overlays']) for p in projects),
                          'samples': sum(1 for r in rows if r.get('sample'))})
    return out


def add_leaves(out, root, prefixes, stats, inv_rows):
    """Incremental build: the rows of the leaves under the root-relative `prefixes` (family/project[/dataset]) replace or
    join those of --out, the other rows stay as they were built (the live site is built from desktop001's tree, which
    this machine's tree does not match leaf for leaf: user, 2026-10-03). The touched projects are re-aggregated, keeping
    their clip records; new rows carry sample=None until their archives are published."""
    want = [x.strip().strip('/').split('/') for x in prefixes if x.strip()]
    leaves = [p for p in scan_leaves(root) if any(p[len(root.rstrip('/')) + 1:].split('/')[:len(w)] == w for w in want)]
    new = [leaf_row(root, p, inv_rows) for p in leaves]
    if not new: sys.exit(f'--add: no dataset under {prefixes} in {root}')
    size_estimates(new, inv_rows)
    had = {r['id']: r for r in out['datasets']}
    for r in new:  # a rebuilt row keeps its published sample archive and task mix (tasks_pass rewrites the latter)
        r['sample'] = (had.get(r['id']) or {}).get('sample')
        for k in ('tm', 'title'):
            if k in (had.get(r['id']) or {}): r[k] = had[r['id']][k]
    ids = {r['id'] for r in new}
    replaced = sum(1 for r in out['datasets'] if r['id'] in ids)
    out['datasets'] = [r for r in out['datasets'] if r['id'] not in ids] + new
    touched = {r['project'] for r in new}
    prev = {p['key']: p for p in out['projects']}
    # clip records of the touched projects: rebuilt from the clip trees where they hold any (the site's 360p mp4s are
    # encoded from the same trees by tools/rerun_clips.py / tools/add_clips.py), else kept; captions from the dataset
    # itself as rerun_clips.attach does, meta.json's `tasks` only when the dataset cannot be read
    clips = collections.defaultdict(list)
    for proj, rec in overlay_records(overlay_metas()):
        if proj not in touched: continue
        try: track = clip_captions(root, rec['dataset'], int(rec['episode']), rec['seconds'])
        except (OSError, KeyError, ImportError, TypeError, ValueError) as e:
            track = None; print(f"warning: {rec['dataset']}: clip captions kept from the render tree ({e!r})", file=sys.stderr)
        else: rec['task'] = track[0][1]
        if track and len(track) > 1: rec['captions'] = track
        clips[proj].append(rec)
    for k, pj in build_projects([r for r in out['datasets'] if r['project'] in touched], stats, inv_rows).items():
        had_clips = {(o['key'], o['slug']): o for o in (prev.get(k) or {}).get('overlays') or []}
        had_clips.update({(o['key'], o['slug']): o for o in clips.get(k, [])})   # the tree's record wins, clips it lacks stay
        pj['overlays'] = [had_clips[x] for x in sorted(had_clips)]
        prev[k] = pj
    out['projects'] = sorted(prev.values(), key=lambda p: p['key'])
    out['built'] = datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')
    print(f'--add: {len(new)} rows under {prefixes} ({replaced} replaced), projects {sorted(touched)}', file=sys.stderr)
    return retotal(out), new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.environ.get('CAMX_ROOT', '/data/camx_480p'))
    ap.add_argument('--out', default=os.path.join(REPO, 'data', 'datasets.json'))
    ap.add_argument('--add', default=None, metavar='PREFIXES',
                    help='incremental: comma-separated root-relative family/project[/dataset] prefixes whose leaves are '
                         '(re)built into --out; every other row of --out is kept as it is')
    ap.add_argument('--scrub-only', action='store_true',
                    help='only re-run the anonymisation pass over --out (and the sources check + data/citations.bib)')
    ap.add_argument('--attach-samples-only', action='store_true',
                    help=f'only merge the published sample archives ({SAMPLES}) into --out')
    ap.add_argument('--captions-only', action='store_true',
                    help='only re-read the captions from --root: the caption tracks of the example clips into --out, '
                         f'and {os.path.relpath(CAPTIONS, REPO)} for the dataset records')
    ap.add_argument('--tasks-only', action='store_true',
                    help='only re-read the task mix of every dataset (rows\' tm / title) from --root into --out')
    a = ap.parse_args()
    if a.scrub_only or a.attach_samples_only or a.captions_only or a.tasks_only:
        out = json.load(open(a.out))
        if a.attach_samples_only: out = attach_samples(out, SAMPLES)
        if a.captions_only: out = captions_pass(out, a.root); dataset_captions(out, a.root)
        if a.tasks_only: out = tasks_pass(out, a.root)
        out = sources_pass(pending_pass(align_paper(anonymise(merge_projects(out)))))
        json.dump(out, open(a.out, 'w'), separators=(',', ':'))
        print(json.dumps(out['totals']), file=sys.stderr); return
    inv = json.load(open(INVENTORY))
    inv_rows = {(e['embodiment'], e['source']): e for e in inv['entries'] if e.get('status') == 'counted'}
    stats = json.load(open(STATS))

    if a.add:
        out, new = add_leaves(json.load(open(a.out)), a.root, a.add.split(','), stats, inv_rows)
        out = tasks_pass(out, a.root, rows=new)
        out = sources_pass(pending_pass(align_paper(anonymise(merge_projects(out)))))
        json.dump(out, open(a.out, 'w'), separators=(',', ':'))
        print(json.dumps(out['totals']), file=sys.stderr)
        dataset_captions(out, a.root)
        for r in sorted(new, key=lambda r: r['id']):
            print(f"  {r['id']:60s} {r['embodiment']:22s} {r['source']:26s} {r['morph']:20s} {r['episodes']:6d} ep {r['hours']:7.2f} h "
                  f"{r['n_views']} views{'' if r['released'] else '  (no _SUCCESS)'}", file=sys.stderr)
        return

    leaves = scan_leaves(a.root)
    print(f'{len(leaves)} leaves under {a.root}', file=sys.stderr)
    rows = [leaf_row(a.root, p, inv_rows) for p in leaves]
    size_estimates(rows, inv_rows)
    projects = build_projects(rows, stats, inv_rows)

    # overlay clips
    for proj, rec in overlay_records(overlay_metas()):
        if proj in projects: projects[proj]['overlays'].append(rec)

    total_h = sum(r['hours'] for r in rows)
    out = {'built': datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z'), 'root': a.root,
           'inventory_updated': inv.get('updated'), 'stats_as_of': stats.get('as_of'),
           # clips are served from the site itself (overlays/videos/, root-relative): GitHub release assets come back as
           # application/octet-stream through an extension-less signed redirect, which iOS Safari refuses to play
           'overlay_base': '/overlays/videos/',
           'totals': {'datasets': len(rows), 'projects': len(projects), 'episodes': sum(r['episodes'] for r in rows),
                      'frames': sum(r['frames'] for r in rows), 'hours': round(total_h, 1),
                      'embodiments': len({r['embodiment'] for r in rows}), 'overlays': sum(len(p['overlays']) for p in projects.values())},
           'projects': sorted(projects.values(), key=lambda p: p['key']), 'datasets': rows}
    out = sources_pass(pending_pass(align_paper(anonymise(merge_projects(attach_samples(tasks_pass(captions_pass(out, a.root), a.root), SAMPLES))))))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(out, open(a.out, 'w'), separators=(',', ':'))
    print(json.dumps(out['totals']), file=sys.stderr)
    dataset_captions(out, a.root)
    # cross-check against the inventory
    inv_h = collections.defaultdict(float)
    for r in rows: inv_h[(r['embodiment'], r['source'])] += r['hours']
    for key, h in sorted(inv_h.items()):
        ih = (inv_rows.get(key) or {}).get('hours')
        flag = '' if ih and abs(ih - h) / ih < 0.02 else '  <-- differs from inventory' if ih else '  <-- not in inventory'
        print(f'{key[0]:26s} {key[1]:28s} site {h:8.1f} h  inventory {ih if ih is not None else "-":>8}{flag}', file=sys.stderr)


if __name__ == '__main__':
    main()
