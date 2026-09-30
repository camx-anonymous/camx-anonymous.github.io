#!/usr/bin/env python3
"""Build data/datasets.json for the CAMX data manager site.

Sources (desktop001 only):
  * every LeRobot-v3 leaf under the canonical camx_480p namespace (meta/info.json)
  * camera-cross-embodiment/camx/figures/dataset_inventory.json  (embodiment / source / form factor / notes / 480p bytes)
  * camx_480p_browser/stats/stats.json                            (skills, episode-duration histogram, #instructions)
  * camx_480p_browser/mv_urdf/videos/<project>/<slug>/meta.json   (projection overlay clips)

Usage: python3 tools/build_site_data.py [--root /data/camx_480p]
       python3 tools/build_site_data.py --scrub-only   # re-run the anonymisation pass over data/datasets.json
       python3 tools/build_site_data.py --attach-samples-only   # merge the published one-episode samples
                                                                # ($CAMX_SAMPLES/{index,published}.jsonl) into it
"""
import argparse, collections, glob, json, os, re, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
INVENTORY = os.path.expanduser('~/projects/camera-cross-embodiment/camx/figures/dataset_inventory.json')
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
LABEL_FIXES = [(r'RB-Y1m', 'RB-Y1'), (r'GenRobot DAS handheld gripper \(bimanual\)', 'GenRobot (bimanual)')]


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
}

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


PROJECT_EMBODIMENT = {'fastumi/fastumi': 'UMI', 'fastumi/fastumi_100k_single_arm': 'UMI'}  # inventory rolls FastUMI (XARM6 rows) into UMI


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
        hand = bool(re.search(r'UMI|handheld|DataClaw|Dobb|AetheRock|Vitamin|HuMI|genrobot', robot_type or '', re.I))
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
# {"sources": {"<source label>": {"homepage", "license": {"name", "url"} | null, "papers": [{"key", "title", "year",
#  "arxiv", "url", "bibtex"}]}}, "projects": {"family/project": "<label>"}, "datasets": {"<row id>": "<label>"}}, keyed by
# the inventory "source" label that every row carries (SOURCE_OF); "projects" / "datasets" point rows at a more
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
    missing = sorted(k for k in used if k not in src)
    if missing: print(f'warning: {len(missing)} sources without an entry in data/sources.json: {missing}', file=sys.stderr)
    unused = sorted(k for k in src if k not in used)
    if unused: print(f'warning: sources.json entries no dataset uses: {unused}', file=sys.stderr)
    for k, v in src.items():
        if not v.get('license'): print(f'warning: {k}: license not stated', file=sys.stderr)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.environ.get('CAMX_ROOT', '/data/camx_480p'))
    ap.add_argument('--out', default=os.path.join(REPO, 'data', 'datasets.json'))
    ap.add_argument('--scrub-only', action='store_true',
                    help='only re-run the anonymisation pass over --out (and the sources check + data/citations.bib)')
    ap.add_argument('--attach-samples-only', action='store_true',
                    help=f'only merge the published sample archives ({SAMPLES}) into --out')
    a = ap.parse_args()
    if a.scrub_only or a.attach_samples_only:
        out = json.load(open(a.out))
        if a.attach_samples_only: out = attach_samples(out, SAMPLES)
        out = sources_pass(anonymise(merge_projects(out)))
        json.dump(out, open(a.out, 'w'), separators=(',', ':'))
        print(json.dumps(out['totals']), file=sys.stderr); return
    inv = json.load(open(INVENTORY))
    inv_rows = {(e['embodiment'], e['source']): e for e in inv['entries'] if e.get('status') == 'counted'}
    stats = json.load(open(STATS))

    leaves = scan_leaves(a.root)
    print(f'{len(leaves)} leaves under {a.root}', file=sys.stderr)
    rows = []
    for p in leaves:
        rel = p[len(a.root.rstrip('/')) + 1:]
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
        src = SOURCE_OF.get(pk, project)
        row = inv_rows.get((emb, src))
        ff = form_of(row, setup, rt, pk)
        state = [k for k in feat if k.startswith('observation.state')]
        has_eef = any('trajectory' in k or 'eef' in k or 'pose' in k for k in state)
        has_joint = any('joint' in k for k in state)
        has_grip = any('gripper' in k for k in state)
        rows.append({
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
        })

    # size estimate per leaf: inventory row bytes shared by frames
    by_row = collections.defaultdict(list)
    for r in rows: by_row[(r['embodiment'], r['source'])].append(r)
    for key, rs in by_row.items():
        row = inv_rows.get(key)
        tot = ((row or {}).get('size') or {}).get('total_bytes')
        fr = sum(r['frames'] for r in rs)
        for r in rs:
            r['bytes_est'] = int(tot * r['frames'] / fr) if tot and fr else None

    # projects
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

    # overlay clips
    for m in overlay_metas():
        d = json.load(open(m)); pkey, slug = m.split('/')[-3:-1]
        proj = d.get('project')
        if proj not in projects: continue
        st = os.path.join(os.path.dirname(m), 'stitched.mp4')
        grips = {s: {'model': g.get('model'), 'profile': g.get('profile'), 'urdf': bool(g.get('urdf_present'))}
                 for s, g in (d.get('grippers') or {}).items() if g.get('model')}
        # overlay_mode is written by tools/overlay_picks.py ('primitive' = hinged stand-in fingers + TCP axes for rigs
        # without a URDF); the shared tree's meta.json has no such field, so fall back on the gripper profiles.
        mode = d.get('overlay_mode') or ('urdf' if any(g['urdf'] for g in grips.values()) else ('camera-path' if 'dataclaw' in pkey else 'none'))
        try: tasks = json.loads(d.get('tasks') or '[]')
        except Exception: tasks = [d.get('tasks')]
        projects[proj]['overlays'].append({
            'key': pkey, 'slug': slug, 'dataset': d.get('dataset'), 'episode': d.get('episode_index'),
            'task': (tasks or [''])[0], 'views': [v['name'] for v in d.get('views', [])], 'grippers': grips, 'mode': mode,
            'fisheye': bool(d.get('fisheye')), 'accept': d.get('accept') or 'unmeasured',
            'export_id': d.get('source_export_id'), 'rendered_from': d.get('source_success_mtime'),
            'seconds': round((d.get('n_frames') or 0) / (d.get('out_fps') or 10), 1),
            'bytes': os.path.getsize(st) if os.path.exists(st) else 0,
        })

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
    out = sources_pass(anonymise(merge_projects(attach_samples(out, SAMPLES))))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(out, open(a.out, 'w'), separators=(',', ':'))
    print(json.dumps(out['totals']), file=sys.stderr)
    # cross-check against the inventory
    inv_h = collections.defaultdict(float)
    for r in rows: inv_h[(r['embodiment'], r['source'])] += r['hours']
    for key, h in sorted(inv_h.items()):
        ih = (inv_rows.get(key) or {}).get('hours')
        flag = '' if ih and abs(ih - h) / ih < 0.02 else '  <-- differs from inventory' if ih else '  <-- not in inventory'
        print(f'{key[0]:26s} {key[1]:28s} site {h:8.1f} h  inventory {ih if ih is not None else "-":>8}{flag}', file=sys.stderr)


if __name__ == '__main__':
    main()
