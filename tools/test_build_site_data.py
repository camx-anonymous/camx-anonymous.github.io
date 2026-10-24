"""Focused build regressions using temporary metadata, with no canonical data access."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


class BuildSiteDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import without consulting a developer's private scrub configuration.
        with tempfile.TemporaryDirectory() as directory:
            scrub = Path(directory) / 'scrub.json'
            scrub.write_text('{}')
            spec = importlib.util.spec_from_file_location(
                'build_site_data_test_subject', Path(__file__).with_name('build_site_data.py'))
            cls.build = importlib.util.module_from_spec(spec)
            with mock.patch.dict(os.environ, {'CAMX_SCRUB': str(scrub)}), \
                    contextlib.redirect_stderr(io.StringIO()):
                spec.loader.exec_module(cls.build)

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        for name, filename in [('CAPTIONS', 'captions.json'), ('SOURCES', 'sources.json'),
                               ('BIB', 'citations.bib'), ('PENDING', 'pending.json'),
                               ('INVENTORY', 'inventory.json'), ('STATS', 'stats.json')]:
            self.stack.enter_context(mock.patch.object(self.build, name, str(self.root / filename)))
        self.write('inventory.json', {'entries': []})
        self.write('stats.json', {})
        self.write('sources.json', {'sources': {'Test source': {
            'license': {'name': 'Test license', 'repo': 'https://example.com/license'},
            'papers': [{'key': 'test', 'bibtex': '@misc{test, title={Test paper}}'}],
        }}})

    def write(self, filename, value):
        (self.root / filename).write_text(json.dumps(value))

    @staticmethod
    def fixture():
        rows = []
        for project, name in [('family/old', 'owner'), ('family/main', 'matching'),
                              ('family/main', 'different')]:
            rows.append({'id': f'{project}/{name}', 'name': name, 'project': project,
                         'source': 'Test source', 'embodiment': 'Test robot', 'morph': 'Test form',
                         'episodes': 1, 'frames': 10, 'hours': 0.1, 'n_views': 1, 'released': True})
        projects = []
        for key in ['family/old', 'family/main']:
            projects.append({'key': key, 'datasets': 1, 'episodes': 1, 'frames': 10, 'hours': 0.1,
                             'embodiments': {}, 'forms': {}, 'views': {}, 'overlays': []})
        projects[0]['overlays'] = [{'dataset': rows[0]['id'], 'task': 'Place the cup',
                                    'also_for': [rows[2]['id']]}]
        return {'datasets': rows, 'projects': projects, 'totals': {}}

    def test_full_and_add_build_use_refreshed_captions_on_first_run(self):
        for mode in ['full', 'add']:
            for prior_file in [False, True]:
                with self.subTest(mode=mode, prior_file=prior_file), contextlib.ExitStack() as stack:
                    out = self.fixture()
                    path = self.root / 'datasets.json'
                    self.write(path.name, out)
                    captions = Path(self.build.CAPTIONS)
                    if prior_file:
                        self.write(captions.name, {r['id']: {'tasks': ['Old instruction']}
                                                  for r in out['datasets']})
                    else:
                        captions.unlink(missing_ok=True)
                    expected_caps = {r['id']: {'tasks': ['Place the cup' if r['name'] != 'different'
                                                        else 'Open the drawer']}
                                     for r in out['datasets']}

                    def refresh(current, root):
                        self.assertEqual(root, str(self.root))
                        self.assertEqual([p['key'] for p in current['projects']], ['family/main'])
                        self.assertTrue(all(r['project'] == 'family/main' for r in current['datasets']))
                        self.write(captions.name, expected_caps)

                    stack.enter_context(mock.patch.object(self.build, 'PROJECT_MERGE',
                                                          {'family/old': 'family/main'}))
                    stack.enter_context(mock.patch.object(self.build, 'SOURCE_OF',
                                                          {'family/main': 'Test source'}))
                    refresh_mock = stack.enter_context(mock.patch.object(
                        self.build, 'dataset_captions', side_effect=refresh))
                    for name in ['captions_pass', 'tasks_pass', 'variants_pass', 'attach_samples']:
                        stack.enter_context(mock.patch.object(self.build, name,
                                                              side_effect=lambda current, *a, **kw: current))
                    stack.enter_context(mock.patch.object(self.build, 'add_leaves',
                                                          return_value=(out, out['datasets'])))
                    leaves = [str(self.root / r['id']) for r in out['datasets']]
                    stack.enter_context(mock.patch.object(self.build, 'scan_leaves', return_value=leaves))
                    stack.enter_context(mock.patch.object(self.build, 'leaf_row',
                                                          side_effect=lambda root, p, inv: out['datasets'][leaves.index(p)]))
                    stack.enter_context(mock.patch.object(self.build, 'size_estimates'))
                    stack.enter_context(mock.patch.object(self.build, 'build_projects',
                                                          return_value={p['key']: p for p in out['projects']}))
                    stack.enter_context(mock.patch.object(self.build, 'overlay_metas', return_value=[]))
                    argv = ['build_site_data.py', '--root', str(self.root), '--out', str(path)]
                    if mode == 'add':
                        argv += ['--add', 'family']
                    stack.enter_context(mock.patch.object(sys, 'argv', argv))

                    self.build.main()

                    refresh_mock.assert_called_once()
                    result = json.loads(path.read_text())
                    overlay = result['projects'][0]['overlays'][0]
                    self.assertEqual(overlay['also_for'], ['family/main/matching'])
                    self.assertEqual(json.loads(captions.read_text()), expected_caps)

    def test_same_task_sharing_requires_matching_owner_project_and_task_group(self):
        caps = {
            'owner': {'tasks': ['Place the cup || Put the cup down'], 'name': 'Kitchen'},
            'matching': {'tasks': [' PLACE THE CUP '], 'name': 'kitchen'},
            'other_group': {'tasks': ['Place the cup'], 'name': 'Workshop'},
            'other_project': {'tasks': ['Place the cup'], 'name': 'Kitchen'},
            'unknown': {'tasks': ['Unknown task.']},
            'unknown_sibling': {'tasks': ['Unknown task.']},
        }
        self.write('captions.json', caps)
        out = {'datasets': [{'id': name, 'project': 'q' if name == 'other_project' else 'p'}
                            for name in [*caps, 'missing']],
               'projects': [{'key': 'p', 'overlays': [
                   {'dataset': 'owner', 'task': 'Place the cup', 'also_for': ['other_group']},
                   {'dataset': 'owner', 'task': 'Open the drawer', 'also_for': ['matching']},
                   {'dataset': 'unknown', 'task': 'Unknown task.', 'also_for': ['unknown_sibling']},
                   {'dataset': 'missing', 'task': 'Place the cup', 'also_for': ['matching']},
               ]}]}

        result = self.build.same_task_pass(out)

        overlays = result['projects'][0]['overlays']
        self.assertEqual(overlays[0]['also_for'], ['matching'])
        for overlay in overlays[1:]:
            self.assertNotIn('also_for', overlay)

    def test_sources_pass_can_suppress_bibliography_writes(self):
        out = self.fixture()
        bib = Path(self.build.BIB)
        original = b'Existing bibliography must stay byte-for-byte intact.\n'
        bib.write_bytes(original)

        result = self.build.sources_pass(copy.deepcopy(out), write_bib=False)

        self.assertEqual(bib.read_bytes(), original)
        self.assertEqual(result['download'], self.build.DOWNLOAD)
        bib.unlink()
        self.build.sources_pass(copy.deepcopy(out), write_bib=False)
        self.assertFalse(bib.exists())
        self.build.sources_pass(copy.deepcopy(out))
        self.assertIn('@misc{test, title={Test paper}}', bib.read_text())


if __name__ == '__main__':
    unittest.main()
