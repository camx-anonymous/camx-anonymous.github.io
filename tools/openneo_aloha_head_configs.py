#!/usr/bin/env python3
"""Per-dataset viz configs for the OpenNeo aloha clips: the fitted HEAD camera pose of each clip's recording-session block.

The release stores ONE hand prior (fold_towels top-down) as head_main_camera_trajectory for every aloha task, while the head
camera was re-placed per task / session. Until the data is backfilled, the site renders the head view through the pose fitted
from the data (camx: camx/data_processing/openneo/config/aloha_head_pose_by_source_episode.json, rows {task, src_ep0, src_ep1,
pose_in_world_xyz_wxyz, ...}), passed to lerobot_rerun_viz as ``static_pose_xyz_wxyz`` of the head video.

  openneo_aloha_head_configs.py            writes configs/aloha_openneo_aloha/<task>.json for every clip of data/datasets.json
Base config: configs/openneo_aloha_fx306.json (wrist fx 306 assumption, head hfov 70).
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
CAMX = os.path.expanduser(os.environ.get('CAMX_REPO', '~/video-gen/repositories/camera-cross-embodiment'))
TABLE = os.path.join(CAMX, 'camx/data_processing/openneo/config/aloha_head_pose_by_source_episode.json')
WRIST = os.path.join(CAMX, 'camx/data_processing/openneo/config/aloha_wrist_camera_in_eef_fit_1006.json')   # fitted wrist camera_in_eef (both arms)
BASE = os.path.join(HERE, 'configs', 'openneo_aloha_fx306.json'); OUT = os.path.join(HERE, 'configs', 'aloha_openneo_aloha')
PROJECT = 'aloha/openneo_aloha'


def row_for(rows, task, ep):
    """The clip record's episode is the CONVERTED index: match on converted_ep0/1 (source ranges are for the converter)."""
    hits = [r for r in rows if r['task'] == task and r.get('converted_ep0', r['src_ep0']) <= ep <= r.get('converted_ep1', r['src_ep1'])]
    return hits[0] if hits else None


def main():
    table = json.load(open(TABLE)); rows = table['rows']
    base = json.load(open(BASE)); os.makedirs(OUT, exist_ok=True)
    clips = [o for o in json.load(open(os.path.join(REPO, 'data', 'datasets.json')))['overlays'] if o['dataset'].startswith(PROJECT + '/')] \
        if 'overlays' in json.load(open(os.path.join(REPO, 'data', 'datasets.json'))) else None
    if clips is None:   # datasets.json layout: find clip records anywhere
        def walk(o):
            if isinstance(o, dict):
                if str(o.get('dataset', '')).startswith(PROJECT + '/') and 'episode' in o and 'views' in o: yield o
                for v in o.values(): yield from walk(v)
            elif isinstance(o, list):
                for v in o: yield from walk(v)
        clips = list(walk(json.load(open(os.path.join(REPO, 'data', 'datasets.json')))))
    n = 0
    for o in clips:
        task, ep = o['dataset'].split('/')[-1], int(o['episode'])
        r = row_for(rows, task, ep)
        if r is None:
            print(f'{task} ep {ep}: no fitted head pose row, config not written', file=sys.stderr); continue
        c = json.loads(json.dumps(base))
        c['_README'] = (base.get('_README', '') + f' PER-DATASET COPY: head static_pose_xyz_wxyz = fitted pose of {task} source episodes '
                        f'{r["src_ep0"]}-{r["src_ep1"]} (placement {r.get("placement")}, {r.get("method")}, rms {r.get("rms_px")} px, {r.get("confidence")}); the stored head trajectory is the unfitted prior. '
                        'Wrist videos: retarget_camera_in_eef from the pass-12 hand prior to the 2026-10-06 fitted mount (aloha_wrist_camera_in_eef_fit_1006.json).')
        wrist = json.load(open(WRIST)) if os.path.isfile(WRIST) else None
        for v in c['videos']:
            if v['name'] == 'head_main_camera_rgb':
                v['static_pose_xyz_wxyz'] = r['pose_in_world_xyz_wxyz']; v['hfov_deg'] = r.get('hfov_deg', v.get('hfov_deg', 70.0))
            elif wrist is not None and v['name'] in ('left_main_camera_rgb', 'right_main_camera_rgb'):
                # the stored wrist trajectories were exported with the hand prior: re-target them to the fitted mount (viewer option)
                v['retarget_camera_in_eef'] = {'old': wrist['prior_camera_in_eef_xyz_wxyz'], 'new': wrist['camera_in_eef_xyz_wxyz']}
                v['hfov_deg'] = wrist.get('hfov_deg', v.get('hfov_deg'))
        json.dump(c, open(os.path.join(OUT, task + '.json'), 'w'), indent=2); n += 1
        print(f'{task} ep {ep}: placement {r.get("placement")} src {r["src_ep0"]}-{r["src_ep1"]} hfov {r.get("hfov_deg")} -> configs/aloha_openneo_aloha/{task}.json')
    print(f'{n} config(s) written')


if __name__ == '__main__':
    main()
