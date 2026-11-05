#!/usr/bin/env python3
"""Keep the public CamX site to the data whose licence allows commercial use (user decision 2026-10-30).

build_site_data.py applies `trim_pass` after `merge_projects` in every build path, so a full rebuild or `--add` cannot bring
an excluded source back; the module also runs on its own:

    python3 tools/trim_noncommercial.py                  # trim data/datasets.json in place and rerun the standard passes
    python3 tools/trim_noncommercial.py --dry-run         # only report what would change
    python3 tools/trim_noncommercial.py --scan-rh20t /data/camx_480p   # refresh configs/rh20t_scene_split.json

Rules
  * EXCLUDED_PROJECTS: every family/project whose source is released under a licence that forbids commercial use
    (CC BY-NC-SA 4.0): AgiBot World 2026 and Beta, DM-DataClaw, Galaxea Open-World, OpenNeoData (TacUMI, UR5, Flexiv Rizon 4,
    ARX5 and AgileX PiPER), RealSource-World and TAMEn. Their rows, project records, clip records and samples leave the site;
    EXCLUDED_SOURCES drops the same sources from the paper's unconverted list (data/pending.json entries).
  * RH20T carries two licences inside every configuration: scenes 0001-0005 are RH20T-C (CC BY-SA 4.0), scenes 0006-0010 are
    RH20T-NC (CC BY-NC 4.0, "commercial use of the RH20T-NC subset or models trained on it is not allowed"), and the few
    episodes of scenes above 0010 belong to neither subset. Only RH20T-C episodes count: a row's episodes / frames / hours are
    its licensed episodes, a row without a licensed episode is dropped, and the episode-0 sample archive and the clips stay
    only when their episode is a licensed scene. Per-episode scenes come from meta/episodes_source.jsonl of every converted
    leaf, cached in tools/configs/rh20t_scene_split.json (`--scan-rh20t` rebuilds it; needs pyarrow for the episode lengths).
  * EXCLUDED_DATASETS: single rows dropped for the same reason (none besides the RH20T rule at the moment).
"""
import argparse
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATASETS = os.path.join(REPO, 'data', 'datasets.json')
SPLIT = os.path.join(HERE, 'configs', 'rh20t_scene_split.json')

EXCLUDED_PROJECTS = {
    'agibot/agibot_world_2026', 'agibot/agibot_world_beta',              # AgiBot World 2026 / Beta: CC BY-NC-SA 4.0
    'daimon/dataclaw',                                                   # DM-DataClaw (Daimon-Infinity): CC BY-NC-SA 4.0
    'aloha/galaxea',                                                     # Galaxea Open-World: CC BY-NC-SA 4.0
    'realman/realsource',                                                # RealSource-World: CC BY-NC-SA 4.0
    'umi/openneo_umi', 'umi/openneo_umi_single', 'ur/openneo_ur', 'flexiv/openneo_flexiv',
    'aloha/openneo_arx5', 'aloha/openneo_arx5_single', 'aloha/openneo_aloha',   # OpenNeoData: CC BY-NC-SA 4.0
    'umi/tamen',                                                         # TAMEn (BiTacMan): CC BY-NC-SA 4.0
}
EXCLUDED_SOURCES = {'AgiBot World 2026', 'AgiBot World Beta', 'DM-DataClaw', 'Galaxea Open-World', 'OpenNeoData',
                    'RealSource-World', 'TAMEn'}
EXCLUDED_DATASETS = set()
RH20T_LICENSED_SCENES = range(1, 6)   # RH20T-C


def is_rh20t(project):
    return '/rh20t_cfg' in project


def scan_rh20t(root):
    """Per-leaf scene split of every converted RH20T leaf under `root` (camx_480p layout)."""
    import pyarrow.parquet as pq
    leaves = collections.OrderedDict()
    for fam, proj in [('dahuan', 'rh20t_cfg1'), ('dahuan', 'rh20t_cfg2'), ('wsg50', 'rh20t_cfg3'), ('robotiq', 'rh20t_cfg4'),
                      ('franka_hand', 'rh20t_cfg5'), ('robotiq', 'rh20t_cfg6'), ('robotiq', 'rh20t_cfg7')]:
        for leaf in sorted(glob.glob(os.path.join(root, fam, proj, '*'))):
            src = os.path.join(leaf, 'meta', 'episodes_source.jsonl')
            if not os.path.isfile(src): continue
            lengths = {}
            for p in sorted(glob.glob(os.path.join(leaf, 'meta', 'episodes', '*', '*.parquet'))):
                t = pq.read_table(p, columns=['episode_index', 'length']).to_pydict()
                lengths.update(zip(t['episode_index'], t['length']))
            e = {'episodes': 0, 'frames': 0, 'licensed_episodes': [], 'frames_licensed': 0, 'scenes': {}}
            for line in open(src):
                rec = json.loads(line); idx = rec['episode_idx']; scene = int(rec['source_scene'])
                e['episodes'] += 1; e['frames'] += lengths.get(idx, 0); e['scenes'][str(idx)] = scene
                if scene in RH20T_LICENSED_SCENES:
                    e['licensed_episodes'].append(idx); e['frames_licensed'] += lengths.get(idx, 0)
            leaves[f'{fam}/{proj}/{os.path.basename(leaf)}'] = e
    return leaves


def load_split():
    if not os.path.isfile(SPLIT):
        sys.exit(f'{os.path.relpath(SPLIT, REPO)} missing: run tools/trim_noncommercial.py --scan-rh20t <camx_480p root>')
    return json.load(open(SPLIT))['leaves']


def trim_pass(out, split=None, log=sys.stderr):
    """Drop the excluded sources and the unlicensed RH20T episodes from a datasets.json object; recompute its totals."""
    split = split if split is not None else load_split()
    keep, dropped, adjusted, pulled = [], [], [], []
    for r in out['datasets']:
        if r.get('project') in EXCLUDED_PROJECTS or r.get('id') in EXCLUDED_DATASETS:
            dropped.append(r['id']); continue
        if is_rh20t(r.get('project') or ''):
            s = split.get(r['id'])
            if s is None: sys.exit(f"{r['id']}: no entry in {os.path.relpath(SPLIT, REPO)}; rerun --scan-rh20t")
            lic = s['licensed_episodes']
            if not lic: dropped.append(r['id']); continue
            if len(lic) != s['episodes']:
                r['episodes'] = len(lic); r['frames'] = s['frames_licensed']
                r['hours'] = round(s['frames_licensed'] / r['fps'] / 3600, 2); adjusted.append(r['id'])
            if 0 not in lic:   # the sample archive and the clips are episode 0
                if r.get('sample'): pulled.append(r['id'])
                r['sample'] = None
        keep.append(r)
    out['datasets'] = keep
    ids = {r['id'] for r in keep}
    by_proj = collections.defaultdict(list)
    for r in keep: by_proj[r.get('project')].append(r)
    projects, clips_dropped = [], 0
    for p in out['projects']:
        rows = by_proj.get(p['key'])
        if not rows: continue
        p['datasets'] = len(rows); p['episodes'] = sum(r.get('episodes') or 0 for r in rows)
        p['frames'] = sum(r.get('frames') or 0 for r in rows); p['hours'] = round(sum(r.get('hours') or 0 for r in rows), 2)
        p['embodiments'] = dict(collections.Counter(r.get('embodiment') for r in rows))
        if any('form' in r for r in rows): p['forms'] = dict(collections.Counter(r.get('form') for r in rows))
        if any('n_views' in r for r in rows):
            views = collections.Counter()
            for r in rows: views[str(r.get('n_views'))] += r.get('episodes') or 0
            p['views'] = dict(views)
        overlays = []
        for o in p.get('overlays') or []:
            if o['dataset'] not in ids: clips_dropped += 1; continue
            if is_rh20t(p['key']) and o.get('episode', 0) not in split[o['dataset']]['licensed_episodes']:
                clips_dropped += 1; continue
            if o.get('also_for'):
                o['also_for'] = [i for i in o['also_for'] if i in ids]
                if not o['also_for']: del o['also_for']
            overlays.append(o)
        p['overlays'] = overlays
        projects.append(p)
    out['projects'] = projects
    out['pending'] = [e for e in out.get('pending') or [] if e.get('source') not in EXCLUDED_SOURCES]
    t = out.setdefault('totals', {})
    t.update({'datasets': len(keep), 'projects': len(projects), 'episodes': sum(r.get('episodes') or 0 for r in keep),
              'frames': sum(r.get('frames') or 0 for r in keep), 'hours': round(sum(r.get('hours') or 0 for r in keep), 1),
              'embodiments': len({r.get('embodiment') for r in keep}), 'overlays': sum(len(p['overlays']) for p in projects),
              'samples': sum(1 for r in keep if r.get('sample'))})
    conv = {(r.get('embodiment'), r.get('source')) for r in keep}
    pend = {(e['embodiment'], e['source']) for e in out['pending']}
    t['sources'] = len(conv | pend)
    t['embodiments_listed'] = len({r.get('embodiment') for r in keep} | {e['embodiment'] for e in out['pending']})
    t['pending'] = {'sources': len(out['pending']), 'datasets': sum(e['datasets'] for e in out['pending']),
                    'episodes': sum(e['episodes'] for e in out['pending']), 'hours': round(sum(e['hours'] for e in out['pending']), 1)}
    out['trimmed'] = {'rule': 'commercial-use licences only (tools/trim_noncommercial.py)', 'dropped_datasets': len(dropped),
                      'rh20t_rows_recounted': len(adjusted), 'rh20t_samples_pulled': len(pulled), 'clips_dropped': clips_dropped}
    if log:
        print(f'trim: {len(dropped)} datasets dropped ({len(EXCLUDED_PROJECTS)} excluded projects + RH20T rows without a licensed '
              f'episode), {len(adjusted)} RH20T rows recounted to their RH20T-C episodes, {len(pulled)} RH20T episode-0 samples '
              f'pulled, {clips_dropped} clip records dropped; {len(keep)} datasets / {len(projects)} projects / '
              f"{t['episodes']:,} episodes / {t['hours']:,} h / {t['embodiments']} embodiments / {t['sources']} sources remain", file=log)
    out['_trim_log'] = {'dropped': dropped, 'adjusted': adjusted, 'pulled': pulled}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=DATASETS)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--scan-rh20t', metavar='ROOT', help='rebuild tools/configs/rh20t_scene_split.json from this camx_480p tree')
    a = ap.parse_args()
    if a.scan_rh20t:
        leaves = scan_rh20t(a.scan_rh20t)
        json.dump({'_about': 'RH20T per-leaf licence split from meta/episodes_source.jsonl (source_scene) and the episode lengths of '
                             'every converted RH20T leaf (tools/trim_noncommercial.py --scan-rh20t). RH20T-C = scenes 0001-0005 '
                             '(CC BY-SA 4.0) is the only part the site may carry; RH20T-NC = scenes 0006-0010 (CC BY-NC 4.0) and the '
                             'scenes above 0010 (no named subset) are left out. licensed_episodes are loader indices; scenes maps '
                             'every episode index to its source scene.',
                   'root': a.scan_rh20t, 'leaves': leaves}, open(SPLIT, 'w'), separators=(',', ':'))
        print(f"{len(leaves)} leaves -> {os.path.relpath(SPLIT, REPO)}", file=sys.stderr); return
    out = json.load(open(a.out))
    sys.path.insert(0, HERE)
    import build_site_data as b   # the standard passes after a trim: project merge, anonymisation, paper, pending, sources, also_for
    out = b.same_task_pass(b.sources_pass(b.pending_pass(b.align_paper(b.anonymise(trim_pass(b.merge_projects(out)))))))
    log = out.pop('_trim_log')
    if a.dry_run:
        print(json.dumps({'dropped': log['dropped'][:20] + (['...'] if len(log['dropped']) > 20 else []), 'adjusted': len(log['adjusted']),
                          'pulled': log['pulled'], 'totals': out['totals']}, indent=1)); return
    json.dump(out, open(a.out, 'w'), separators=(',', ':'))
    print(json.dumps(out['totals']), file=sys.stderr)


if __name__ == '__main__':
    main()
