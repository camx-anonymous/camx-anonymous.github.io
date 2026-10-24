"""Run: python3 -m unittest discover -s tools -p 'test_write_site_catalog.py'."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import write_site_catalog as catalog


def sample():
    return {'projects': [{'key': 'robot/project', 'overlays': [
        {'key': 'robot_project', 'slug': 'task__ep7', 'dataset': 'robot/project/task',
         'episode': 7, 'export_id': None, 'render_fingerprint': 'abc123',
         'rendered_from': {'export_id': 'release-7', 'future_provenance': ['µ', None, 2]},
         'captions': [[0, '先拿起 ☕\\"\n']], 'tile_w': [640, 320], 'tile_h': 480}]}],
        'datasets': [{'id': 'robot/project/task', 'project': 'robot/project',
                      'future_metadata': {'unknown': ['雪', 3.125, True]}}],
        'pending': [], 'totals': {'overlays': 1},
        'unknown_top_level': {'long': '☕"\\\n' * 9000}, 'raw_base': 'https://example.test/raw/'}


def reconstruct(directory):
    index = json.loads((directory / 'index.json').read_text())
    pieces = []
    for part, entry in enumerate(index['shards']):
        payload = (directory / entry['path']).read_bytes()
        assert len(payload) == entry['bytes'] <= index['max_bytes']
        assert hashlib.sha256(payload).hexdigest() == entry['sha256']
        shard = json.loads(payload)
        assert shard['part'] == part
        pieces.append(shard['text'])
    document = ''.join(pieces).encode('utf-8')
    assert len(document) == index['catalog_bytes']
    assert hashlib.sha256(document).hexdigest() == index['catalog_sha256']
    return json.loads(document)


class CatalogWriterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source, self.out = self.root / 'source.json', self.root / 'catalog'
        self.data = sample()
        self.source.write_text(json.dumps(self.data))

    def test_unicode_large_record_roundtrip_size_determinism_and_source_unchanged(self):
        original = self.source.read_bytes()
        index = catalog.write_catalog(self.source, self.out, 32 * 1024)
        self.assertGreater(len(index['shards']), 1)
        self.assertEqual(reconstruct(self.out), self.data)
        self.assertEqual(index['counts'], {'projects': 1, 'datasets': 1, 'overlays': 1, 'pending': 0})
        self.assertEqual(index['source_sha256'], hashlib.sha256(original).hexdigest())
        before = {p.name: p.read_bytes() for p in self.out.iterdir()}
        catalog.write_catalog(self.source, self.out, 32 * 1024)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.out.iterdir()})
        self.assertTrue(all(len(blob) <= 32 * 1024 for blob in before.values()))
        self.assertEqual(self.source.read_bytes(), original)

    def test_default_real_five_mib_boundary(self):
        self.data['unknown_top_level']['long'] = 'x' * (catalog.MAX_BYTES + 100)
        self.source.write_text(json.dumps(self.data))
        index = catalog.write_catalog(self.source, self.out)
        self.assertEqual(index['shards'][0]['bytes'], catalog.MAX_BYTES)
        self.assertEqual(reconstruct(self.out), self.data)
        self.assertTrue(all(p.stat().st_size <= catalog.MAX_BYTES for p in self.out.iterdir()))

    def test_index_last_and_old_shards_retained(self):
        old = catalog.write_catalog(self.source, self.out, 32 * 1024)
        old_index = (self.out / 'index.json').read_bytes()
        self.data['unknown_top_level']['long'] = 'new data' * 9000
        self.source.write_text(json.dumps(self.data))
        original_write = catalog.atomic_write
        writes = []

        def fail_index(path, blob):
            writes.append(path.name)
            if path.name == 'index.json':
                raise OSError('simulated interrupted publication')
            original_write(path, blob)

        with mock.patch.object(catalog, 'atomic_write', side_effect=fail_index):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                catalog.write_catalog(self.source, self.out, 32 * 1024)
        self.assertEqual(writes[-1], 'index.json')
        self.assertEqual((self.out / 'index.json').read_bytes(), old_index)
        self.assertEqual(reconstruct(self.out), sample())
        catalog.write_catalog(self.source, self.out, 32 * 1024)
        self.assertEqual(reconstruct(self.out), self.data)
        self.assertTrue(all((self.out / entry['path']).exists() for entry in old['shards']))

    def test_bad_input_rejected_before_publication(self):
        invalids = [[], {'projects': [], 'datasets': 'bad'}]
        for path, value in [('totals', {'overlays': 2}), ('pending', {})]:
            changed = copy.deepcopy(self.data)
            changed[path] = value
            invalids.append(changed)
        changed = copy.deepcopy(self.data)
        changed['projects'][0]['overlays'][0]['render_fingerprint'] = 19
        invalids.append(changed)
        changed = copy.deepcopy(self.data)
        changed['datasets'][0]['project'] = 'missing'
        invalids.append(changed)
        for data in invalids:
            with self.subTest(data=str(data)[:80]):
                self.source.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    catalog.write_catalog(self.source, self.out)
                self.assertFalse(self.out.exists())
        self.source.write_text('{"projects":[],"projects":[],"datasets":[]}')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            catalog.write_catalog(self.source, self.out)

    def test_existing_corrupt_shard_rejected_without_replacing_index(self):
        index = catalog.write_catalog(self.source, self.out, 32 * 1024)
        before = (self.out / 'index.json').read_bytes()
        shard = self.out / index['shards'][0]['path']
        shard.write_text('corrupt')
        with self.assertRaisesRegex(ValueError, 'corrupt'):
            catalog.write_catalog(self.source, self.out, 32 * 1024)
        self.assertEqual((self.out / 'index.json').read_bytes(), before)
        self.assertEqual(shard.read_text(), 'corrupt')

    def test_limit_and_input_destination_guards(self):
        for limit in (0, 1023, catalog.MAX_BYTES + 1):
            with self.assertRaises(ValueError):
                catalog.write_catalog(self.source, self.out, limit)
        with self.assertRaisesRegex(ValueError, 'outside'):
            catalog.write_catalog(self.source, self.root)


if __name__ == '__main__':
    unittest.main()
