#!/usr/bin/env python3
"""Upload the one-episode sample archives (tools/build_samples.py) to GitHub releases of this repo.

One release per dataset family, tag samples-v1-<family>; GitHub caps a release at 1,000 assets, so a family with more
samples spills over into samples-v1-<family>-2, -3, ... Assets that a release already has are skipped, so the script
is resumable. Every uploaded asset is recorded in
<out>/published.jsonl as {id, asset, url, bytes}; tools/build_site_data.py --attach-samples merges that file into
data/datasets.json.

Usage: python3 tools/publish_samples.py [--out /data/camx_samples] [--workers 4] [--ids id1,id2]
Auth: the camx-anonymous token from `gh auth token --user camx-anonymous` (or $GH_TOKEN).
"""
import argparse, json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

import requests

OWNER, REPO_NAME = 'camx-anonymous', 'camx-anonymous.github.io'
API = f'https://api.github.com/repos/{OWNER}/{REPO_NAME}'
TAG = 'samples-v1'
LIMIT = 1000  # GitHub refuses (422) the 1,001st asset of a release


def token():
    t = os.environ.get('GH_TOKEN')
    if not t:
        t = subprocess.run(['gh', 'auth', 'token', '--user', OWNER], capture_output=True, text=True, check=True).stdout.strip()
    return t


def api(sess, method, url, **kw):
    for attempt in range(5):
        r = sess.request(method, url, timeout=600, **kw)
        if r.status_code < 500 and r.status_code != 429: return r
        time.sleep(5 * (attempt + 1))
    return r


def tag_of(family, part):
    return f'{TAG}-{family}' + ('' if part == 1 else f'-{part}')


def get_release(sess, tag):
    r = api(sess, 'GET', f'{API}/releases/tags/{tag}')
    if r.status_code == 404: return None
    if r.status_code >= 300: sys.exit(f'cannot read release {tag}: {r.status_code} {r.text[:300]}')
    return r.json()


def create_release(sess, family, part):
    tag = tag_of(family, part)
    body = (f'One-episode samples (episode 0) of every `{family}/*` dataset, one `.tar.gz` per dataset that unpacks '
            'to `<family>/<project>/<dataset>/{meta,data,videos}` in the LeRobot-v3 layout. '
            + (f'Part {part}: GitHub caps a release at {LIMIT:,} assets. ' if part > 1 else '')
            + 'Pick datasets and get a download command at https://camx-anonymous.github.io/#download')
    name = f'One-episode samples: {family}' + (f' ({part})' if part > 1 else '')
    r = api(sess, 'POST', f'{API}/releases', json={'tag_name': tag, 'name': name, 'body': body, 'draft': False, 'prerelease': False})
    if r.status_code >= 300: sys.exit(f'cannot create release {tag}: {r.status_code} {r.text[:300]}')
    print(f'created release {tag}', file=sys.stderr)
    return r.json()


def release_assets(sess, rel):
    assets = {}
    page = 1
    while True:
        r = api(sess, 'GET', f'{API}/releases/{rel["id"]}/assets', params={'per_page': 100, 'page': page})
        if r.status_code >= 300: sys.exit(f'cannot list assets of {rel["tag_name"]}: {r.status_code}')
        batch = r.json()
        for a in batch: assets[a['name']] = a
        if len(batch) < 100: break
        page += 1
    return assets


def family_releases(sess, family):
    """Every existing samples-v1-<family>[-N] release with its assets, in part order (created on demand by main)."""
    parts = []
    while True:
        rel = get_release(sess, tag_of(family, len(parts) + 1))
        if rel is None: break
        parts.append([rel, release_assets(sess, rel)])
    return parts


def upload(sess, rel, path, name):
    url = rel['upload_url'].split('{')[0]
    with open(path, 'rb') as f:
        data = f.read()
    for attempt in range(4):
        r = sess.post(url, params={'name': name}, data=data, headers={'Content-Type': 'application/gzip'}, timeout=900)
        if r.status_code < 300: return r.json()
        if r.status_code == 422: return None  # already there (name taken) or the release is full
        time.sleep(10 * (attempt + 1))
    raise RuntimeError(f'{name}: {r.status_code} {r.text[:200]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='/data/camx_samples')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--ids', help='comma-separated site ids (default: every ok line of index.jsonl)')
    a = ap.parse_args()
    recs = [json.loads(l) for l in open(os.path.join(a.out, 'index.jsonl'))]
    recs = [r for r in recs if r.get('ok')]
    if a.ids: want = set(a.ids.split(',')); recs = [r for r in recs if r['id'] in want]
    sess = requests.Session()
    sess.headers.update({'Authorization': f'Bearer {token()}', 'Accept': 'application/vnd.github+json',
                         'X-GitHub-Api-Version': '2022-11-28'})
    pub_path = os.path.join(a.out, 'published.jsonl')
    published = {}
    if os.path.exists(pub_path):
        for l in open(pub_path): p = json.loads(l); published[p['id']] = p
    by_family = {}
    for r in recs: by_family.setdefault(r['id'].split('/')[0], []).append(r)
    todo = []
    with open(pub_path, 'a') as pub:
        for family, rs in sorted(by_family.items()):
            parts = family_releases(sess, family) or [[create_release(sess, family, 1), {}]]
            have = {name: a_ for _, assets in parts for name, a_ in assets.items()}
            pending = []
            for r in rs:
                if r['id'] in published: continue
                if r['asset'] in have:  # uploaded by an earlier run whose record was lost
                    a_ = have[r['asset']]
                    p = {'id': r['id'], 'asset': a_['name'], 'url': a_['browser_download_url'], 'bytes': a_['size']}
                    pub.write(json.dumps(p) + '\n'); published[r['id']] = p; continue
                pending.append(r)
            fill = [len(assets) for _, assets in parts]  # assets per part once this run's uploads land
            for r in pending:
                if fill[-1] >= LIMIT:
                    parts.append([create_release(sess, family, len(parts) + 1), {}]); fill.append(0)
                todo.append((parts[-1][0], r)); fill[-1] += 1
            print(f'{family}: {len(rs)} samples, ' + ', '.join(f'{len(a)} on {rel["tag_name"]}' for rel, a in parts)
                  + f', {len(pending)} to upload', file=sys.stderr)
        print(f'{len(todo)} archives to upload', file=sys.stderr)

        def work(job):
            rel, r = job
            path = os.path.join(a.out, 'archives', r['asset'])
            a_ = upload(sess, rel, path, r['asset'])
            if a_ is None: return r['id'], None
            return r['id'], {'id': r['id'], 'asset': a_['name'], 'url': a_['browser_download_url'], 'bytes': a_['size']}

        t0 = time.time(); n = 0; fails = 0
        with ThreadPoolExecutor(a.workers) as ex:
            for fut in ex.map(lambda j: _safe(work, j), todo):
                n += 1
                sid, p = fut
                if isinstance(p, Exception): fails += 1; print(f'FAIL {sid}: {p}', file=sys.stderr)
                elif p: pub.write(json.dumps(p) + '\n'); pub.flush(); published[sid] = p
                else: print(f'{sid}: asset name already taken, re-run to pick it up', file=sys.stderr)
                if n % 25 == 0 or n == len(todo):
                    el = time.time() - t0
                    print(f'{n}/{len(todo)} uploaded, {fails} failed, {el/60:.1f} min, eta {el/n*(len(todo)-n)/60:.0f} min', file=sys.stderr)
    print(f'published: {len(published)} of {len(recs)} samples', file=sys.stderr)


def _safe(fn, job):
    try: return fn(job)
    except Exception as e:  # noqa: BLE001
        return job[1]['id'], e


if __name__ == '__main__':
    main()
