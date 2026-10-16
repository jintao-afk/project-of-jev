"""R1 persistence boundaries with real large CSVs and simulated child decisions."""
import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from core import Engine, ROOT
from services import invoke
from task_store import DELIVERY_METADATA_RESERVE, MAX_RECORD_BYTES, TaskStore
from test_agent import FakeLocal
from workflow import read_csv, table_statistics, threshold_check


class R1BoundaryTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'.cache/tmp').mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'.cache/tmp')
        self.root = Path(self.temp.name)
        (self.root/'config.json').write_bytes((ROOT/'config.json').read_bytes())
        self.engine = Engine(self.root)
        self.engine.model_ready = lambda role: True

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def make_child(self, rows=5000, long_states=True):
        source = self.root/'workspace/inbox/data'
        source.mkdir(parents=True)
        stats, checks, hashes = {}, {}, {}
        for name in ('a.csv', 'b.csv'):
            path = source/name
            text = 'value,status\n'+''.join('1,'+str(i).zfill(4)+'-'+('a'*180 if long_states else 'ok')+'\n' for i in range(rows))
            path.write_text(text, 'utf-8')
            self.assertLessEqual(path.stat().st_size, 1_000_000)
            if rows==5000:
                self.assertGreater(path.stat().st_size, 900_000)
            table = read_csv(path, 'value', 'status')
            stats[name] = table_statistics(table, 'value', 'status')
            checks[name] = threshold_check(table, 'value', Decimal('0'))
            hashes[name] = table['sha256']
        run_id = 'a'*32
        folder = self.root/'workspace/runs'/run_id
        folder.mkdir(parents=True)
        artifact_data = {'statistics': stats, 'threshold_checks': checks,
            'comparison': {'first': 'a.csv', 'second': 'b.csv', 'rows_delta': 0, 'mean_delta': '0.000000',
                'status_counts': {name:data['status_counts'] for name, data in stats.items()}},
            'source_files': hashes}
        raw = json.dumps(artifact_data, ensure_ascii=False, indent=2).encode('utf-8')
        (folder/'report.json').write_bytes(raw)
        (folder/'report.md').write_text('Simulated verified child artifact, not model inference.', 'utf-8')
        (folder/'delivery.json').write_text(json.dumps({'run_id': run_id, 'files': {
            name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in ('report.json', 'report.md')}}), 'utf-8')
        artifacts = [{'name':name, 'url':f'/v1/artifacts/{run_id}/{name}'} for name in ('report.md', 'report.json')]
        child = {'run_id': run_id, 'mode': 'workflow', 'backend': 'test_double', 'status': 'completed',
            'task_complete': True, 'completion_scope': 'deterministic_dataset_contract',
            'invocation_attempts': 11, 'successful_calls': 11, 'route_reviews': 1, 'artifact_repairs': 0,
            'remote_attempts': 0, 'semantic_accuracy': None, 'total_ms': 25,
            'result': {**artifact_data, 'artifacts': artifacts},
            'events': [{'event': 'decision', 'step': 1, 'choice': 'stats_0', 'probabilities': {'stats_0':1}},
                {'event': 'route_review_finished', 'step': 1, 'choice': 'stats_0', 'reason': 'test double'},
                {'event': 'route_finalized', 'step': 1, 'initial_choice': 'stop', 'choice': 'stats_0', 'reviewed': True},
                {'event': 'invocation_started', 'step': 1, 'action': 'stats_0'},
                {'event': 'invocation_finished', 'step': 1, 'action': 'stats_0', 'call_success': True, 'result': artifact_data}]}
        log_path = self.root/'logs'/(run_id+'.json')
        log_path.parent.mkdir(exist_ok=True)
        log_path.write_text(json.dumps(child, ensure_ascii=False, indent=2), 'utf-8')
        child['log_file'] = str(log_path)
        return child, folder

    def test_two_legal_near_megabyte_csvs_keep_complete_artifacts_and_bounded_checkpoint(self):
        child, folder = self.make_child()
        self.engine.local = FakeLocal([], ['dataset_report', 'finish'])
        request = {'mode': 'agent', 'goal': '1. 分析CSV附件并交付报告', 'input': '',
            'dataset': {'input_dir': 'data', 'value_column': 'value', 'status_column': 'status', 'threshold': '0'}}
        with patch('workflow.WorkflowRunner.run', return_value=child):
            report = self.engine.run(request)
        result = report['subtask_results']['s1']['result']
        self.assertTrue(report['execution_complete'])
        self.assertLess(len(json.dumps(report, ensure_ascii=False, indent=2).encode()), 500_000)
        raw = TaskStore(self.root).ensure_record_size(request, report, '2026-10-15T00:00:00Z')
        self.assertLess(len(raw)+DELIVERY_METADATA_RESERVE, MAX_RECORD_BYTES)
        restored = TaskStore(self.root).load(report['task_id'])
        self.assertEqual(restored['report']['run_id'], report['run_id'])
        full = json.loads((folder/'report.json').read_text('utf-8'))
        for name in ('a.csv', 'b.csv'):
            preview = result['statistics'][name]
            self.assertEqual(len(full['statistics'][name]['status_counts']), 5000)
            self.assertEqual(len(full['threshold_checks'][name]['matches']), 5000)
            self.assertEqual(preview['status_counts_total'], 5000)
            self.assertEqual(len(preview['status_counts'])+preview['status_counts_omitted'], 5000)
            threshold = result['threshold_checks'][name]
            self.assertEqual(threshold['count'], 5000)
            self.assertEqual(len(threshold['matches']), 50)
            self.assertEqual(threshold['matches_omitted'], 4950)
        summary = result['workflow_run']
        self.assertNotIn('events', summary)
        self.assertNotIn('result', summary)
        self.assertEqual(summary['route_reviews'], 1)
        self.assertEqual(summary['remote_attempts'], 0)
        self.assertEqual(summary['trace'][0]['choice'], 'stats_0')
        self.assertEqual(summary['trace'][-1]['action'], 'stats_0')
        reference = summary['log_reference']
        self.assertEqual(reference['sha256'], hashlib.sha256(Path(reference['path']).read_bytes()).hexdigest())
        self.assertEqual(result['detail_scope']['full_details'], child['result']['artifacts'])
        self.assertLess(len(result['text']), 1000)

    def test_small_details_are_unchanged_and_failed_child_keeps_failure_trace(self):
        child, _ = self.make_child(rows=2, long_states=False)
        spec = {'dataset': {'input_dir':'data'}}
        with patch('workflow.WorkflowRunner.run', return_value=child):
            result = invoke(self.engine, 'dataset_report', {'goal':'分析CSV'}, spec, 10)
        for key in ('statistics', 'comparison', 'threshold_checks'):
            self.assertEqual(result[key], child['result'][key])
        child.update(task_complete=False, status='stopped', reason='CSV缺少声明字段')
        child['events'].append({'event':'invocation_failed', 'action':'load_0', 'error':'missing value column'})
        with patch('workflow.WorkflowRunner.run', return_value=child):
            rejected = invoke(self.engine, 'dataset_report', {'goal':'分析CSV'}, spec, 10)
        self.assertEqual(rejected['quality']['status'], 'rejected_draft')
        self.assertFalse(rejected['workflow_run']['task_complete'])
        self.assertEqual(rejected['workflow_run']['trace'][-1]['error'], 'missing value column')

    def test_rehashed_malformed_checkpoint_is_rejected_and_history_skips_it(self):
        self.engine.local = FakeLocal([], ['calculator', 'finish'])
        report = self.engine.run({'mode':'agent', 'goal':'1. 计算 2+3', 'input':''})
        store = TaskStore(self.root)
        folder = store.folder(report['task_id'])
        record_path = folder/(report['run_id']+'.json')
        pristine = json.loads(record_path.read_text('utf-8'))
        pointer = json.loads((folder/'latest.json').read_text('utf-8'))
        mutations = [lambda d:d.update(request=[]), lambda d:d['report'].update(revision='1'),
            lambda d:d['report'].update(resumable=1), lambda d:d['report'].update(subtask_results=[]),
            lambda d:d['report'].update(pending_subtasks=[d['report']['plans'][0]['steps'][0]]),
            lambda d:d['report']['plans'][0]['steps'].append(deepcopy(d['report']['plans'][0]['steps'][0])),
            lambda d:d['report']['subtask_results']['s1']['input_provenance'].update(sha256='broken'),
            lambda d:d['report'].update(input_bindings={'s6':'$input'}),
            lambda d:d['report'].pop('replans')]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                damaged = deepcopy(pristine)
                mutate(damaged)
                raw = json.dumps(damaged, ensure_ascii=False).encode('utf-8')
                record_path.write_bytes(raw)
                (folder/'latest.json').write_text(json.dumps({**pointer, 'sha256':hashlib.sha256(raw).hexdigest()}), 'utf-8')
                with self.assertRaises(ValueError):
                    store.load(report['task_id'])
                self.assertEqual(store.list(), [])

    def test_preflight_reserves_delivery_metadata_and_rejects_unsafe_json(self):
        store = TaskStore(self.root)
        self.assertEqual(DELIVERY_METADATA_RESERVE, 8192)
        with self.assertRaises(ValueError):
            store.ensure_record_size({}, {'padding':'a'*(MAX_RECORD_BYTES-DELIVERY_METADATA_RESERVE)}, 'now')
        with self.assertRaises(ValueError):
            store.ensure_record_size({}, {'value':float('nan')}, 'now')
        self.assertFalse(store.base.exists())


if __name__=='__main__':
    unittest.main()
