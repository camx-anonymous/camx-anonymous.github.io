#!/usr/bin/env python3
"""Publish a derived, lossless site catalog in JSON files no larger than 5 MiB.

Usage: python3 tools/write_site_catalog.py --input /tmp/attached-datasets.json --out data/catalog
The input is read-only. Content-addressed shards are retained across publications;
index.json is atomically replaced only after every new shard is ready. Text chunks
allow even one large project/metadata value to span files without dropping fields.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

MAX_BYTES = 5 * 1024 * 1024
SCHEMA = 'camx-catalog-v1'


def encode(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_catalog(data):
    if not isinstance(data, dict):
        raise ValueError('catalog must be an object')
    for key in ('projects', 'datasets'):
        if not isinstance(data.get(key), list):
            raise ValueError(f'{key} must be an array')
    if 'pending' in data and not isinstance(data['pending'], list):
        raise ValueError('pending must be an array')
    projects, datasets = set(), set()
    overlays = 0
    for project in data['projects']:
        if not isinstance(project, dict) or not isinstance(project.get('key'), str) or not project['key']:
            raise ValueError('project needs a nonempty key')
        if project['key'] in projects or not isinstance(project.get('overlays'), list):
            raise ValueError(f'duplicate project or missing overlays: {project["key"]}')
        projects.add(project['key'])
        overlays += len(project['overlays'])
        for clip in project['overlays']:
            if not isinstance(clip, dict):
                raise ValueError('clip must be an object')
            for field in ('key', 'slug', 'dataset'):
                if not isinstance(clip.get(field), str) or not clip[field]:
                    raise ValueError(f'clip needs a nonempty {field}')
            # Legacy exports may be null. Preserve all provenance fields verbatim.
            for field in ('export_id', 'render_fingerprint'):
                if clip.get(field) is not None and (not isinstance(clip[field], str) or not clip[field]):
                    raise ValueError(f'clip {field} must be a nonempty string or null')
    for row in data['datasets']:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id']:
            raise ValueError('dataset needs a nonempty id')
        if row['id'] in datasets or row.get('project') not in projects:
            raise ValueError(f'duplicate dataset or unknown project: {row["id"]}')
        datasets.add(row['id'])
    if isinstance(data.get('totals'), dict) and 'overlays' in data['totals']:
        if data['totals']['overlays'] != overlays:
            raise ValueError('totals.overlays does not match clip count')
    return {'projects': len(projects), 'datasets': len(datasets),
            'overlays': overlays, 'pending': len(data.get('pending', []))}


def make_shards(document, max_bytes):
    """Find maximal text chunks by their actual serialized UTF-8 envelope size."""
    offset, part = 0, 0
    while offset < len(document):
        def envelope(end):
            return encode({'schema': SCHEMA, 'part': part, 'text': document[offset:end]})
        low, high = offset + 1, min(len(document), offset + max_bytes)
        best, blob = offset, None
        while low <= high:
            end = (low + high) // 2
            candidate = envelope(end)
            if len(candidate) <= max_bytes:
                best, blob = end, candidate
                low = end + 1
            else:
                high = end - 1
        if blob is None:
            raise ValueError('byte budget cannot fit a shard envelope')
        yield {'path': f'part-{part:05d}-{digest(blob)}.json', 'bytes': len(blob),
               'sha256': digest(blob)}, blob
        offset, part = best, part + 1


def atomic_write(path, payload):
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def write_catalog(source, destination, max_bytes=MAX_BYTES):
    source, destination = Path(source), Path(destination)
    if not 1024 <= max_bytes <= MAX_BYTES:
        raise ValueError(f'max bytes must be between 1024 and {MAX_BYTES}')
    if source.resolve() == (destination / 'index.json').resolve() or source.resolve().is_relative_to(destination.resolve()):
        raise ValueError('input must be outside the output catalog directory')
    raw = source.read_bytes()
    data = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    counts = validate_catalog(data)
    document = encode(data)
    parts = list(make_shards(document.decode('utf-8'), max_bytes))
    index = {'schema': SCHEMA, 'max_bytes': max_bytes, 'source_sha256': digest(raw),
             'catalog_sha256': digest(document), 'catalog_bytes': len(document),
             'counts': counts, 'shards': [entry for entry, _ in parts]}
    index_blob = encode(index)
    if len(index_blob) > max_bytes:
        raise ValueError('index exceeds byte budget')
    destination.mkdir(parents=True, exist_ok=True)
    for entry, blob in parts:
        target = destination / entry['path']
        if target.exists():
            if target.read_bytes() != blob:
                raise ValueError(f'existing content-addressed shard is corrupt: {target}')
        else:
            atomic_write(target, blob)
    # Old index readers can continue loading the retained old shards.
    atomic_write(destination / 'index.json', index_blob)
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--max-bytes', type=int, default=MAX_BYTES,
                        help='maximum bytes per JSON file, capped at 5 MiB')
    args = parser.parse_args()
    try:
        index = write_catalog(args.input, args.out, args.max_bytes)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({'index': str(args.out / 'index.json'), 'shards': len(index['shards']),
                      'counts': index['counts'], 'max_shard_bytes': max(p['bytes'] for p in index['shards'])}))


if __name__ == '__main__':
    main()
