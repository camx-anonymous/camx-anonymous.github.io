"""Bounded release contract tests; synthetic filters only, no GPU, network or dataset writes."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import release_clips as R


def media(width=1280, height=480, frames=450, rate='10/1', **extra):
    result = dict(width=width, height=height, frames=frames, nb_frames=frames, rate=rate, avg_rate=rate,
                  duration=frames / float(R.Fraction(rate)), start=0.0, codec='h264')
    result.update(extra)
    return result


class ContractTests(unittest.TestCase):
    def test_contract_validation_and_fingerprint(self):
        for args in ((0, 10, 45), (481, 10, 45), (480, 0, 45), (480, 10, -1), (480, float('nan'), 45),
                     (480, 10, float('inf')), (480, 1, .01)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                R.output_contract(*args)
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'meta.json').write_text('{}')
            original = R.fingerprint(tmp)
            self.assertNotEqual(original, R.fingerprint(tmp, R.output_contract(fps=12)))
            Path(tmp, R.RECEIPT).write_text('{}')
            self.assertNotEqual(original, R.fingerprint(tmp))

    def test_unequal_recorded_widths_preserved_and_scaled_per_tile(self):
        meta = {'views': ['a', 'b'], 'renderer_summary': {'tile_w': [640, 856], 'tile_h': 480}}
        widths, height = R.tile_layout(meta, media(width=1496))
        self.assertEqual(R.output_layout(widths, height, R.output_contract()), ([640, 856], 480))
        self.assertEqual(R.output_layout([960, 1284], 720, R.output_contract()), ([640, 856], 480))
        fc = R.overlay_filter(media(width=2244, height=720), [960, 1284], [640, 856], 480, R.output_contract(), 450)
        self.assertIn('crop=1284:720:960:0:exact=1,scale=856:480', fc)

    def test_duration_is_capped_without_rounding_up(self):
        self.assertEqual(R.output_frames(media(frames=563, rate='25/2'), R.output_contract()), 450)
        self.assertEqual(R.output_frames(media(frames=13, rate='25/2'), R.output_contract()), 10)
        self.assertEqual(R.output_frames(media(frames=13, rate='25/2'), R.output_contract(seconds=.99)), 9)

    def test_stream_copy_requires_receipt_and_actual_contract(self):
        receipt = dict(encoder='h264_nvenc', preset='p5', cq=36, final_quality=True)
        contract = R.output_contract()
        eligible = lambda rec, src=media(), cq=36: R.copy_eligible({'stitched_encode': rec}, src, contract, [640, 640], 450, cq)
        self.assertTrue(eligible(receipt))
        self.assertTrue(eligible(dict(receipt, cq=42), cq=42))
        for key, bad in [('encoder', 'libx264'), ('preset', 'p4'), ('cq', 42), ('final_quality', 'true')]:
            self.assertFalse(eligible(dict(receipt, **{key: bad})))
        for bad in (media(height=720), media(frames=451), media(rate='25/2'), media(codec='av1'),
                    media(avg_rate='25/2'), media(duration=46), media(start=.2)):
            self.assertFalse(eligible(receipt, bad))
        self.assertFalse(eligible({}))

    def test_container_probe_never_decodes_frames(self):
        result = {'width': 1280, 'height': 480, 'r_frame_rate': '10/1', 'avg_frame_rate': '10/1', 'duration': '45',
                  'nb_frames': '450', 'codec_name': 'h264', 'start_time': '0'}
        with patch.object(R.subprocess, 'run', return_value=types.SimpleNamespace(stdout=json.dumps({'streams': [result]}))) as run:
            self.assertEqual(R.probe('test.mp4')['frames'], 450)
            self.assertNotIn('-count_frames', run.call_args.args[0])
            result['nb_frames'] = 'N/A'
            run.return_value.stdout = json.dumps({'streams': [result]})
            with self.assertRaises(ValueError):
                R.probe('test.mp4')

    def test_cache_requires_new_contract_and_probed_media(self):
        contract = R.output_contract()
        with tempfile.TemporaryDirectory() as tmp:
            paths = {key: str(Path(tmp, key)) for key in ('record', 'raw', 'video', 'poster')}
            Path(paths['poster']).touch()
            rec = dict(render_fingerprint='fp', cq=36, encoder='h264_nvenc', output_contract=contract,
                       tile_w=[640, 640], tile_h=480, width=1280, height=480, frames=450, fps=10,
                       decoded_frames={'raw':450, 'video':450})
            Path(paths['record']).write_text(json.dumps(rec))
            with patch.object(R, 'probe', return_value=media()) as probe:
                self.assertEqual(R.cached_record(paths, 'fp', 36, contract, [640, 640], 450, False), rec)
                probe.return_value = media(rate='25/2')
                self.assertIsNone(R.cached_record(paths, 'fp', 36, contract, [640, 640], 450, False))
                probe.return_value = media()
                del rec['output_contract']
                Path(paths['record']).write_text(json.dumps(rec))
                self.assertIsNone(R.cached_record(paths, 'fp', 36, contract, [640, 640], 450, False))

    def test_nvenc_failure_has_no_software_fallback(self):
        with self.assertRaises(ValueError):
            R.encoder_args('libx264', 36)
        with patch.object(R, 'ff', side_effect=RuntimeError('NVENC unavailable')) as ff:
            with self.assertRaisesRegex(RuntimeError, 'NVENC unavailable'):
                R.encode_with('/nonexistent/release-test.mp4', ('h264_nvenc',), 36, '-i', 'source.mp4')
            self.assertEqual(ff.call_count, 1)
            self.assertNotIn('libx264', ff.call_args.args)

    def test_full_decode_rejects_short_or_incomplete_output(self):
        for progress in ('frame=449\nprogress=end\n', 'frame=450\nprogress=continue\n', ''):
            with patch.object(R, 'ff', return_value=progress), self.assertRaises(RuntimeError):
                R.verify_decoded_frames('test.mp4', 450)
        with patch.object(R, 'ff', return_value='frame=1\nprogress=continue\nframe=450\nprogress=end\n'):
            self.assertEqual(R.verify_decoded_frames('test.mp4',450),450)

    def test_broker_receives_codec_work_and_copy_bypasses_routing(self):
        broker = types.SimpleNamespace(run=Mock(return_value=types.SimpleNamespace(returncode=0, stdout='')))
        with patch.object(R, '_CODECS', broker), patch.object(R, '_CODEC_ENV', {'CAMX_GPU_CODECS': 'nvidia'}):
            R.ff('-i', 'source.mp4', '-c:v', 'copy', 'copy.mp4', route=False)
            self.assertFalse(broker.run.call_args.kwargs['route'])
            R.ff('-i', 'source.mp4', '-c:v', 'h264_nvenc', 'encoded.mp4')
            self.assertTrue(broker.run.call_args.kwargs['route'])
        with self.assertRaises(ValueError):
            R.configure_codecs(None)
        with patch.object(R, '_CODECS', None), self.assertRaisesRegex(RuntimeError, 'GPU broker'):
            R.ff('-i', 'source.mp4', 'out.mp4')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg unavailable for synthetic filter check')
    def test_actual_raw_overlay_sampling_matches_at_12_5_fps(self):
        # lavfi-generated frame IDs and rawvideo transport exercise filters only, with no compressed codecs.
        temporal = R.final_sampling('25/2', R.output_contract(), 20)
        def pixels(rate, expression, prefilter):
            src = f"nullsrc=s=2x2:r={rate}:d=2,geq=lum='{expression}':cb=128:cr=128"
            command = ['ffmpeg', '-nostdin', '-v', 'error', '-filter_threads', '1', '-f', 'lavfi', '-i', src,
                       '-vf', prefilter + temporal, '-frames:v', '20', '-pix_fmt', 'yuv420p', '-threads', '1',
                       '-f', 'rawvideo', '-']
            return subprocess.run(command, capture_output=True, check=True, timeout=20).stdout
        raw = pixels('25', 'N', r'trim=end_frame=50,select=not(mod(n\,2)),')
        overlay = pixels('25/2', 'N*2', '')
        self.assertEqual(raw, overlay)
        self.assertEqual(len(raw), 20 * 6)
        self.assertEqual(len(set(raw[::6])), 20)


class CommandTests(unittest.TestCase):
    def test_record_accepts_native_and_json_task_lists(self):
        for value in (['move the cup'], '["move the cup"]', 'move the cup'):
            with self.subTest(tasks=value):
                rec = R.record_of('fam/proj', 'ds', 0, {'dataset': 'ds', 'views': ['front']},
                                  {}, {'tasks': value}, '/nonexistent', 'fp', 20, '10/1', 100, 100,
                                  'h264_nvenc', 36, 640, 480, [640], 480, '/render')
                self.assertEqual(rec['task'], 'move the cup')

    def test_renderer_error_sets_nonzero_batch_exit(self):
        args = argparse.Namespace(jobs=1, nvenc_slots=1, height=480, fps=10, seconds=45, codec_lib='fake', only=None,
                                  cq_map='unused', render='render', samples='samples', out='out', default_cq=None, force=False)
        executor = Mock()
        executor.__enter__ = Mock(return_value=executor)
        executor.__exit__ = Mock(return_value=False)
        executor.map.return_value = [{'name': 'bad', 'status': 'render-error', 'error': 'missing pose'}]
        with tempfile.TemporaryDirectory() as tmp:
            args.out = tmp
            args.cq_map = str(Path(tmp, 'cq.json'))
            Path(args.cq_map).write_text('{"family/project":36}')
            with patch.object(R, 'configure_codecs'), patch.object(R, 'find_renders', return_value=[('family/project', 'ds', 0, tmp)]), \
                    patch.object(R, 'ProcessPoolExecutor', return_value=executor), contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
                R.cmd_encode(args)
            self.assertEqual(error.exception.code, 1)

    def test_encode_one_normalizes_and_copies_only_eligible_stitched(self):
        for copy in (False, True):
            with self.subTest(copy=copy), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                render = root / 'render'
                render.mkdir()
                sample = root / 'sample'
                (sample / 'meta').mkdir(parents=True)
                (sample / 'meta' / 'info.json').write_text(json.dumps({'fps': 25, 'video_path': '{video_key}.mp4'}))
                (sample / 'observation.image.front.mp4').touch()
                source = media(width=640, frames=450 if copy else 563, rate='10/1' if copy else '25/2')
                meta = dict(route='urdf', dataset='ds', views=['front'], clip=dict(stride=2, source_frames=900 if copy else 1125),
                            renderer_summary={'tile_w': [640], 'tile_h': 480})
                if copy:
                    meta['stitched_encode'] = dict(encoder='h264_nvenc', preset='p5', cq=36, final_quality=True)
                (render / 'meta.json').write_text(json.dumps(meta))
                (render / 'stitched.mp4').touch()
                row = {f'videos/observation.image.front/{field}': 0 for field in ('chunk_index', 'file_index', 'from_timestamp')}
                job = dict(project='fam/proj', dataset='ds', ep=0, ep_dir=str(render), samples='unused', out=str(root / 'out'),
                           cq=36, force=False, contract=R.output_contract())
                calls = []
                def fake_ff(*args, **kwargs):
                    calls.append((args, kwargs))
                    if args[-1] != '-':
                        Path(args[-1]).write_bytes(b'test output')
                    return 'frame=450\nprogress=end\n'
                semaphore = Mock()
                semaphore.acquire.return_value = True
                with patch.object(R, 'sample_root', return_value=str(sample)), patch.object(R, 'episode_row', return_value=row), \
                        patch.object(R, 'probe', side_effect=lambda p: source if p == str(render / 'stitched.mp4') else media(width=640)), \
                        patch.object(R, 'ff', side_effect=fake_ff), patch.object(R, '_NVENC', semaphore):
                    result = R.encode_one(job)
                self.assertEqual(result['status'], 'encoded', result)
                self.assertEqual(result['record']['frames'], 450)
                self.assertEqual(result['record']['fps'], 10)
                self.assertEqual(result['record']['stitched_stream_copy'], copy)
                self.assertEqual(result['record']['tile_w'], [640])
                self.assertEqual(result['record']['output_contract'], R.output_contract())
                semaphore.acquire.assert_called_once_with()
                semaphore.release.assert_called_once_with()
                first, opts = calls[0]
                if copy:
                    self.assertIn('copy', first)
                    self.assertEqual(opts, {'route': False})
                else:
                    overlay = first[first.index('-filter_complex') + 1]
                    raw_args = calls[1][0]
                    raw = raw_args[raw_args.index('-filter_complex') + 1]
                    expected = R.final_sampling('25/2', R.output_contract(), 450)
                    self.assertIn(expected, overlay)
                    self.assertIn(expected, raw)
                self.assertEqual(sum('-xerror' in args for args, _ in calls), 2)

    def test_attach_preserves_geometry_without_bibliography_write(self):
        helper = types.ModuleType('build_site_data')
        helper.PROJECT_MERGE, helper.ID_RENAMES = {}, {}
        for name in ('scrub', 'same_task_pass', 'pending_pass', 'align_paper', 'anonymise', 'merge_projects'):
            setattr(helper, name, lambda value: value)
        helper.captions_pass = lambda value, root: value
        helper.sources_pass = Mock(side_effect=lambda value, **kwargs: value)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = root / 'records'
            records.mkdir()
            rec = dict(project='fam/proj', key='fam_proj', slug='ds__ep0', dataset='ds', episode=0, mode='urdf',
                       tile_w=[640, 856], tile_h=480)
            (records / 'record.json').write_text(json.dumps(rec))
            data = root / 'datasets.json'
            previous = [dict(key='fam_proj', slug='untouched__ep0', dataset='untouched', task='keep me'),
                        dict(key='fam_proj', slug='ds__ep0', dataset='ds', tile_w=[1])]
            data.write_text(json.dumps({'projects': [{'key': 'fam/proj', 'overlays': previous}], 'totals': {}}))
            args = argparse.Namespace(records=str(records), plan=None, datasets=str(data), out=str(root / 'attached.json'),
                                      root='unused', overlay_base='videos/', raw_base='raw/', poster_base='posters/')
            with patch.dict(sys.modules, {'build_site_data': helper}), contextlib.redirect_stderr(io.StringIO()):
                R.cmd_attach(args)
            overlays = json.loads(Path(args.out).read_text())['projects'][0]['overlays']
            self.assertEqual(len(overlays), 2)
            self.assertEqual(next(o for o in overlays if o['dataset'] == 'untouched'), previous[0])
            attached = next(o for o in overlays if o['dataset'] == 'ds')
            self.assertEqual(attached['tile_w'], [640, 856])
            self.assertEqual(attached['tile_h'], 480)
            self.assertFalse(helper.sources_pass.call_args.kwargs['write_bib'])

    def test_generated_upload_script_with_fake_gh_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix='release test ') as tmp:
            root = Path(tmp)
            for folder in ('records', 'raw', 'videos', 'bin'):
                (root / folder).mkdir()
            for index, mode in enumerate(('urdf', 'raw', 'urdf')):
                rec = dict(project='fam/proj', key='fam_proj', slug=f'ds__ep{index}', mode=mode)
                name = R.clip_name(rec)
                (root / 'records' / f'{name}.json').write_text(json.dumps(rec))
                (root / 'raw' / f'{name}.mp4').touch()
                if mode != 'raw':
                    (root / 'videos' / f'{name}.mp4').touch()
            args = argparse.Namespace(records=str(root / 'records'), out=str(root / 'plan.json'), max_assets=3,
                                      tag_prefix='clips-test', repo='example/repo')
            with contextlib.redirect_stderr(io.StringIO()):
                R.cmd_plan(args)
            fake = root / 'bin' / 'gh'
            fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
p = pathlib.Path(os.environ['FAKE_GH_STATE'])
state = json.loads(p.read_text()) if p.exists() else {'tags': {}, 'uploads': 0}
args = sys.argv[1:]
assert args[0] == 'release'
action, tag = args[1:3]
if action == 'view':
    if tag not in state['tags']: sys.exit(1)
    if '--json' in args: print('\\n'.join(state['tags'][tag]))
elif action == 'create': state['tags'][tag] = []
elif action == 'upload':
    for value in args[3:]:
        source = pathlib.Path(value)
        if source.is_file():
            assert source.exists()
            if source.name not in state['tags'][tag]: state['tags'][tag].append(source.name)
            state['uploads'] += 1
else: raise AssertionError(args)
p.write_text(json.dumps(state))
''')
            fake.chmod(0o755)
            state_path = root / 'gh-state.json'
            env = dict(os.environ, PATH=str(root / 'bin') + os.pathsep + os.environ['PATH'], FAKE_GH_STATE=str(state_path), BATCH='2')
            script = args.out + '.upload.sh'
            for expected, force in ((5, '0'), (5, '0'), (10, '1')):
                env['FORCE'] = force
                run = subprocess.run(['bash', script], env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                state = json.loads(state_path.read_text())
                self.assertEqual(state['uploads'], expected)
                self.assertEqual(sorted(len(assets) for assets in state['tags'].values()), [2, 3])
            plan = json.loads(Path(args.out).read_text())
            self.assertNotIn('overlay_asset', plan['fam_proj__ds__ep1'])

    def test_default_plan_versions_changed_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = root / 'records'
            records.mkdir()
            rec = dict(project='fam/proj', key='fam_proj', slug='ds__ep0', mode='raw', render_fingerprint='old')
            record = records / 'clip.json'
            args = argparse.Namespace(records=str(records), out=str(root/'plan.json'), max_assets=900,
                                      tag_prefix=None, repo='example/repo')
            tags = []
            for fingerprint in ('old', 'old', 'changed'):
                rec['render_fingerprint'] = fingerprint
                record.write_text(json.dumps(rec))
                with contextlib.redirect_stderr(io.StringIO()):
                    R.cmd_plan(args)
                tags.append(json.loads(Path(args.out).read_text())['fam_proj__ds__ep0']['tag'])
            self.assertEqual(tags[0], tags[1])
            self.assertNotEqual(tags[1], tags[2])


if __name__ == '__main__':
    unittest.main()
