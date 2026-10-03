#!/usr/bin/env python3
"""Ingest example clips rendered outside tools/rerun_clips.py (the conversion pass of 2026-10-03 renders its own
validation clips, in the same headless-Rerun white-CAD look) into the site's clip tree and encode them for the site.

  add_clips.py <src tree>/<key> [...] [--as family/project]

Each <key>/<slug>/ must hold stitched.mp4, meta.json and DONE.json in the layout of the shared clip tree. The folder is
copied (stitched.mp4, meta.json, DONE.json, poster.jpg) to $CAMX_CLIPS_OUT/<project key>/<slug>/; with --as the clips
are filed under that project (meta.json `project`, and the dataset id rewritten to <family/project>/<dataset name>), for
clips rendered under a scratch project name. Then overlays/videos/<key>__<slug>.mp4 (360p) and overlays/posters/*.jpg
are encoded exactly as rerun_clips.py encode does. Follow with build_site_data.py --add (CAMX_OVERLAYS_EXTRA=the clip
tree) for the clip records and tools/raw_clips.py --only <key> for the raw companions.
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
OUT = os.environ.get('CAMX_CLIPS_OUT', '/data/camx_clips')
ROOT = os.environ.get('CAMX_ROOT', '/data/camx_480p')


def probe(mp4):
    o = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries', 'stream=r_frame_rate,nb_read_packets',
                        '-of', 'csv=p=0', mp4], capture_output=True, text=True, check=True).stdout.strip().split(',')
    a, b = o[0].split('/'); return float(a) / float(b), int(o[1])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('src', nargs='+'); ap.add_argument('--as', dest='proj', default=None)
    a = ap.parse_args()
    vdir, pdir = os.path.join(REPO, 'overlays', 'videos'), os.path.join(REPO, 'overlays', 'posters')
    for src in a.src:
        for slug in sorted(os.listdir(src)):
            s = os.path.join(src, slug)
            if not all(os.path.isfile(os.path.join(s, f)) for f in ('stitched.mp4', 'meta.json', 'DONE.json')): continue
            m = json.load(open(os.path.join(s, 'meta.json')))
            if a.proj: m['project'] = a.proj; m['dataset'] = a.proj + '/' + m['dataset'].split('/', 2)[2]
            if not os.path.isfile(os.path.join(ROOT, m['dataset'], 'meta', 'info.json')):
                print(f'skip {slug}: {m["dataset"]} is not in {ROOT}', file=sys.stderr); continue
            key = m['project'].replace('/', '_'); d = os.path.join(OUT, key, slug); os.makedirs(d, exist_ok=True)
            rate, n = probe(os.path.join(s, 'stitched.mp4'))
            m.setdefault('n_frames', n); m.setdefault('out_fps', round(rate, 3)); m['slug'] = slug
            # no gripper CAD in the render (stand-in fingers): the site labels the clip as a stand-in overlay
            m.setdefault('overlay_mode', 'urdf' if any(g.get('urdf_present') for g in (m.get('grippers') or {}).values()) else 'primitive')
            for k in ('config', 'source_realpath'): m.pop(k, None)          # local paths stay out of the tree the site reads
            for g in (m.get('grippers') or {}).values(): g.pop('urdf', None)
            for f in ('stitched.mp4', 'DONE.json', 'poster.jpg'):
                if os.path.isfile(os.path.join(s, f)): shutil.copy2(os.path.join(s, f), os.path.join(d, f))
            json.dump(m, open(os.path.join(d, 'meta.json'), 'w'), indent=1)
            name = f'{key}__{slug}'; mp4 = os.path.join(vdir, name + '.mp4')
            subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', os.path.join(d, 'stitched.mp4'), '-vf', 'scale=-2:360', '-c:v', 'libx264',
                            '-preset', 'slow', '-crf', '28', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', mp4], check=True)
            rate, n = probe(mp4)
            subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{n / rate / 2:.3f}', '-i', mp4, '-frames:v', '1', '-vf', 'scale=-2:180', '-q:v', '6',
                            os.path.join(pdir, name + '.jpg')], check=True)
            print(f'{name}: {m["dataset"]} ep {m["episode_index"]}, {n} frames, {os.path.getsize(mp4) // 1024} KB')


if __name__ == '__main__':
    main()
