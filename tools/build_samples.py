#!/usr/bin/env python3
"""Cut a one-episode sample (episode 0) out of every dataset in data/datasets.json.

Each sample is a valid LeRobot-v3 dataset with the same layout as the full one, holding only episode 0:
  <id>/meta/info.json           total_episodes=1, total_frames=len(ep0), splits train 0:1, private _note* keys dropped
  <id>/meta/episodes/chunk-000/file-000.parquet   the episode-0 row
  <id>/meta/tasks.parquet, meta/stats.json, meta/_SUCCESS   copied
  <id>/data/chunk-000/file-000.parquet            the episode-0 rows of the first packed data file
  <id>/videos/<view>/chunk-000/file-000.mp4       the first packed video cut at episode 0's to_timestamp (stream copy)
Everything else under meta/ (quality/, *_source.jsonl, export configs, backups ...) is NOT copied: those files carry
local paths and user names. Every JSON/text/string column that is copied goes through the site's scrub list and the
build fails for a dataset if a forbidden term survives.

Output (--out, default /data/camx_samples):
  tree/<id>/...                 the sample dataset
  archives/<asset>.tar.gz       one archive per dataset, unpacks to <family>/<project>/<dataset>/
  index.jsonl                   one line per dataset: id, asset, bytes, frames, seconds, views, ok, error

Usage: uv run --with pyarrow python tools/build_samples.py [--root /data/camx_480p] [--workers 8]
                                                          [--ids id1,id2 | --limit N] [--force]
Re-running skips datasets whose archive already exists with an ok index line.
"""
import argparse, json, os, re, shutil, subprocess, sys, tarfile, time
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from build_site_data import scrub, FORBIDDEN, ID_RENAMES  # noqa: E402

import pyarrow.parquet as pq  # noqa: E402
import pyarrow.compute as pc  # noqa: E402

if FORBIDDEN.pattern == r'(?!x)x':
    sys.exit('refusing to build samples without the scrub list: set CAMX_SCRUB=<path to scrub.json>')
REAL_ID = {v: k for k, v in ID_RENAMES.items()}          # site id -> id in the data tree
EPISODE = 0
META_COPY = ['tasks.parquet', 'stats.json', '_SUCCESS']


def asset_name(site_id):
    family, project, dataset = site_id.split('/', 2)
    return f'{family}_{project}__{dataset}'.replace('/', '_')


LOCAL_PATH = re.compile(r'(^|[\s"\'=:])/(storage|data|home|mnt|tmp)/')


def drop_local_paths(obj):
    """Remove every string value that holds a machine-local absolute path (export provenance such as
    source_dir / path entries): those name users and drives, not anything a consumer of the sample needs."""
    if isinstance(obj, dict):
        return {k: drop_local_paths(v) for k, v in obj.items()
                if not (isinstance(v, str) and LOCAL_PATH.search(v))}
    if isinstance(obj, list):
        return [drop_local_paths(x) for x in obj if not (isinstance(x, str) and LOCAL_PATH.search(x))]
    return obj


def forbidden_hits(text):
    return sorted({m.group(0).lower() for m in FORBIDDEN.finditer(text)})


def check_strings(table, where):
    """Raise if any string column of a parquet table holds a forbidden term."""
    for name, col in zip(table.column_names, table.columns):
        if col.type.equals('string') or col.type.equals('large_string'):
            hits = forbidden_hits('\n'.join(x for x in col.to_pylist() if x))
            if hits: raise RuntimeError(f'forbidden term in {where}.{name}: {hits}')


def ffprobe_packets(path):
    p = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries',
                        'stream=nb_read_packets', '-of', 'csv=p=0', path], capture_output=True, text=True)
    return int(p.stdout.strip() or 0)


def build_one(job):
    site_id, root, out, force = job
    real = REAL_ID.get(site_id, site_id)
    src = os.path.join(root, real)
    dst = os.path.join(out, 'tree', site_id)
    asset = asset_name(site_id)
    arch = os.path.join(out, 'archives', asset + '.tar.gz')
    rec = {'id': site_id, 'asset': asset + '.tar.gz', 'ok': False}
    t0 = time.time()
    try:
        info = json.load(open(os.path.join(src, 'meta', 'info.json')))
        views = [k for k, f in info['features'].items() if f.get('dtype') == 'video']
        eps = pq.read_table(os.path.join(src, 'meta', 'episodes', 'chunk-000', 'file-000.parquet'))
        eps = eps.filter(pc.equal(eps['episode_index'], EPISODE))
        if eps.num_rows != 1: raise RuntimeError(f'episode {EPISODE} not in meta/episodes file-000 ({eps.num_rows} rows)')
        ep = eps.to_pylist()[0]
        if ep['data/chunk_index'] or ep['data/file_index']: raise RuntimeError('episode 0 is not in data file-000')
        for v in views:
            if ep[f'videos/{v}/chunk_index'] or ep[f'videos/{v}/file_index'] or ep[f'videos/{v}/from_timestamp']:
                raise RuntimeError(f'episode 0 does not start video file-000 of {v}')
        length = int(ep['length'])
        check_strings(eps, 'episodes')

        if os.path.isdir(dst): shutil.rmtree(dst)
        os.makedirs(os.path.join(dst, 'meta', 'episodes', 'chunk-000'))
        os.makedirs(os.path.join(dst, 'data', 'chunk-000'))

        # meta
        info = {k: v for k, v in info.items() if not k.startswith('_')}
        info.update(total_episodes=1, total_frames=length, splits={'train': '0:1'})
        info = scrub(drop_local_paths(info))
        txt = json.dumps(info, indent=1)
        if real != site_id:  # renamed dataset: repo_id and friends must carry the public name
            txt = txt.replace(real, site_id).replace(real.split('/')[-1], site_id.split('/')[-1])
            info = json.loads(txt)
        hits = forbidden_hits(txt)
        if hits: raise RuntimeError(f'forbidden term in info.json: {hits}')
        open(os.path.join(dst, 'meta', 'info.json'), 'w').write(txt + '\n')
        pq.write_table(eps, os.path.join(dst, 'meta', 'episodes', 'chunk-000', 'file-000.parquet'))
        for f in META_COPY:
            p = os.path.join(src, 'meta', f)
            if not os.path.exists(p): continue
            if f.endswith('.parquet'):
                t = pq.read_table(p); check_strings(t, f); pq.write_table(t, os.path.join(dst, 'meta', f))
            elif f.endswith('.json'):
                s = json.dumps(scrub(json.load(open(p))), indent=1)
                hits = forbidden_hits(s)
                if hits: raise RuntimeError(f'forbidden term in {f}: {hits}')
                open(os.path.join(dst, 'meta', f), 'w').write(s + '\n')
            else:
                shutil.copyfile(p, os.path.join(dst, 'meta', f))

        # data
        t = pq.read_table(os.path.join(src, 'data', 'chunk-000', 'file-000.parquet'))
        t = t.filter(pc.equal(t['episode_index'], EPISODE))
        if t.num_rows != length: raise RuntimeError(f'data rows {t.num_rows} != episode length {length}')
        check_strings(t, 'data')
        pq.write_table(t, os.path.join(dst, 'data', 'chunk-000', 'file-000.parquet'))

        # videos: stream-copy the prefix of the first packed file
        for v in views:
            vsrc = os.path.join(src, 'videos', v, 'chunk-000', 'file-000.mp4')
            vdst = os.path.join(dst, 'videos', v, 'chunk-000', 'file-000.mp4')
            os.makedirs(os.path.dirname(vdst))
            # exactly `length` frames: some exports have a non-integer fps whose to_timestamp lands past frame N
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', vsrc, '-frames:v', str(length), '-c', 'copy',
                            '-movflags', '+faststart', vdst], check=True, capture_output=True)
            n = ffprobe_packets(vdst)
            if n != length: raise RuntimeError(f'{v}: {n} video frames != episode length {length}')

        # archive: unpacks to <family>/<project>/<dataset>/
        os.makedirs(os.path.dirname(arch), exist_ok=True)
        tmp = arch + '.tmp'
        with tarfile.open(tmp, 'w:gz', compresslevel=1) as tf:
            tf.add(dst, arcname=site_id)
        os.replace(tmp, arch)
        rec.update(ok=True, bytes=os.path.getsize(arch), frames=length, fps=info.get('fps'),
                   seconds=round(length / info['fps'], 2) if info.get('fps') else None, views=len(views),
                   tree_bytes=sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(dst) for f in fs))
    except Exception as e:  # noqa: BLE001
        rec['error'] = f'{type(e).__name__}: {e}'[:500]
        if os.path.isdir(dst): shutil.rmtree(dst, ignore_errors=True)
    rec['secs'] = round(time.time() - t0, 1)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.environ.get('CAMX_ROOT', '/data/camx_480p'))
    ap.add_argument('--out', default='/data/camx_samples')
    ap.add_argument('--datasets', default=os.path.join(REPO, 'data', 'datasets.json'))
    ap.add_argument('--ids', help='comma-separated site ids (default: every dataset)')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--force', action='store_true', help='rebuild even if the archive exists')
    a = ap.parse_args()
    ids = [r['id'] for r in json.load(open(a.datasets))['datasets']]
    if a.ids: ids = a.ids.split(',')
    if a.limit: ids = ids[:a.limit]
    os.makedirs(a.out, exist_ok=True)
    index_path = os.path.join(a.out, 'index.jsonl')
    done = {}
    if os.path.exists(index_path) and not a.force:
        for line in open(index_path):
            r = json.loads(line)
            if r.get('ok') and os.path.exists(os.path.join(a.out, 'archives', r['asset'])): done[r['id']] = r
    todo = [i for i in ids if i not in done]
    print(f'{len(ids)} datasets, {len(done)} already built, {len(todo)} to do', file=sys.stderr)
    jobs = [(i, a.root, a.out, a.force) for i in todo]
    n_ok = n_err = 0; t0 = time.time()
    with open(index_path, 'a') as idx, Pool(a.workers) as pool:
        for k, rec in enumerate(pool.imap_unordered(build_one, jobs), 1):
            idx.write(json.dumps(rec) + '\n'); idx.flush()
            if rec['ok']: n_ok += 1
            else: n_err += 1; print(f'FAIL {rec["id"]}: {rec["error"]}', file=sys.stderr)
            if k % 25 == 0 or k == len(jobs):
                el = time.time() - t0
                print(f'{k}/{len(jobs)} ok={n_ok} err={n_err} {el/60:.1f} min, eta {el/k*(len(jobs)-k)/60:.0f} min', file=sys.stderr)
    # de-duplicate the index: keep the last line per id
    last = {}
    for line in open(index_path): r = json.loads(line); last[r['id']] = r
    with open(index_path, 'w') as f:  # every id ever built, this run's (--ids / --limit) first
        for i in ids + [i for i in last if i not in set(ids)]:
            if i in last: f.write(json.dumps(last[i]) + '\n')
    tot = sum(r.get('bytes', 0) for r in last.values() if r.get('ok'))
    print(f'done: {sum(1 for r in last.values() if r.get("ok"))} ok, {sum(1 for r in last.values() if not r.get("ok"))} failed, '
          f'{tot/1e9:.1f} GB of archives', file=sys.stderr)


if __name__ == '__main__':
    main()
