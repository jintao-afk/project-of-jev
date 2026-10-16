import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from core import Engine, ROOT
from workflow import WorkflowError, read_csv, scoped_path, table_statistics, threshold_check


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp')
        self.root = Path(self.temp.name)
        (self.root / 'config.json').write_text((ROOT / 'config.json').read_text('utf-8'), 'utf-8')
        self.folder = self.root / 'workspace/inbox/data'
        self.folder.mkdir(parents=True)
        self.engine = Engine(self.root)

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def write(self, name, text):
        path = self.folder / name
        path.write_text(text, 'utf-8')
        return path

    def request(self, **extra):
        return {'mode': 'workflow', 'backend': 'rules', 'goal': '分析并交付数据报告。',
                'workflow': {'input_dir': 'data', 'value_column': 'value', 'status_column': 'status', **extra}}

    def test_exact_statistics_and_disclosed_bad_values(self):
        path = self.write('a.csv', 'value,status\n1.1,returned\n2.2,needs_review\n,missing\nNaN,bad\n-0.3,returned\n')
        table = read_csv(path, 'value', 'status')
        stats = table_statistics(table, 'value', 'status')
        self.assertEqual(stats['rows'], 5)
        self.assertEqual(stats['mean'], '1.000000')
        self.assertEqual(stats['median'], '1.100000')
        self.assertEqual(stats['missing_rows'], [4])
        self.assertEqual(stats['invalid_rows'], [5])
        self.assertEqual(stats['status_counts']['returned'], 2)
        # A strict threshold excludes equality and includes the correct CSV row.
        checks = threshold_check(table, 'value', Decimal('1.1'))
        self.assertEqual(checks['count'], 1)
        self.assertEqual(checks['matches'][0]['source_row'], 3)

    def test_rejects_path_escape_and_invalid_csv_structure(self):
        for path in ('../config.json', 'D:/secret.csv', '..\\secret.csv'):
            with self.assertRaises(WorkflowError):
                scoped_path(self.folder, path)
        for text in ('value,value\n1,2\n', 'value,status\n1,ok,extra\n'):
            path = self.write('bad.csv', text)
            with self.assertRaises(WorkflowError):
                read_csv(path, 'value', 'status')

    def test_full_report_has_comparison_evidence_and_delivery(self):
        self.write('a.csv', 'value,status\n2,returned\n4,needs_review\n')
        self.write('b.csv', 'value,status\n6,returned\n8,timeout\n')
        report = self.engine.run(self.request(threshold=4))
        self.assertTrue(report['task_complete'])
        self.assertEqual(report['result']['comparison']['mean_delta'], '4.000000')
        self.assertFalse(report['validation']['semantic_verified'])
        self.assertEqual(report['remote_attempts'], 0)
        path = self.root / 'workspace/runs' / report['run_id'] / 'report.json'
        data = json.loads(path.read_text('utf-8'))
        self.assertTrue((path.parent / 'delivery.json').is_file())
        self.assertEqual(data['threshold_checks']['a.csv']['count'], 0)
        self.assertEqual(data['threshold_checks']['b.csv']['count'], 2)
        actions = [e['action'] for e in report['events'] if e['event'] == 'invocation_started']
        self.assertLess(actions.index('write'), actions.index('verify'))
        self.assertLess(actions.index('verify'), actions.index('finish'))

    def test_missing_column_is_execution_failure_not_fake_completion(self):
        self.write('a.csv', 'other,status\n1,ok\n')
        report = self.engine.run(self.request())
        self.assertFalse(report['task_complete'])
        self.assertTrue(any(e['event'] == 'invocation_failed' and '缺少' in e['error'] for e in report['events']))
        self.assertFalse((self.root / 'workspace/runs').exists())

    def test_comparison_rounds_once_and_markdown_escapes_untrusted_text(self):
        self.write('a.csv', 'value,status\n0.00000049,<img>\n')
        self.write('b.csv', 'value,status\n0.00000051,ok\n')
        report = self.engine.run({**self.request(), 'goal': '![load](https://invalid.example/image) <script>'})
        self.assertTrue(report['task_complete'])
        self.assertEqual(report['result']['comparison']['mean_delta'], '0.000000')
        text = (self.root / 'workspace/runs' / report['run_id'] / 'report.md').read_text('utf-8')
        self.assertNotIn('<img>', text)
        self.assertNotIn('<script>', text)
        self.assertNotIn('![load](', text)

    def test_stop_choice_and_review_recorded_without_rule_fallback(self):
        self.write('a.csv', 'value,status\n1,ok\n')
        class Stop:
            def request(self, operation, payload, timeout):
                if operation == 'review_workflow':
                    return {'choice': 'stop', 'reason': 'cannot proceed'}
                return {'backend': 'anyjev', 'probabilities': {c['id']: float(c['id'] == 'stop') for c in payload['candidates']}}
            def close(self): pass
        self.engine.local = Stop()
        self.engine.model_ready = lambda role: True
        report = self.engine.run({**self.request(), 'backend': 'anyjev'})
        self.assertFalse(report['task_complete'])
        self.assertEqual(report['route_reviews'], 1)
        self.assertEqual(report['successful_calls'], 0)
        self.assertTrue(next(e for e in report['events'] if e['event'] == 'route_finalized')['reviewed'])

    def test_artifact_corruption_is_repaired_once_and_reverified(self):
        self.write('a.csv', 'value,status\n2,ok\n')
        class CorruptOnce:
            corrupted = False
            def request(inner, operation, payload, timeout):
                candidates = payload['candidates']
                if any(c['id'] == 'verify' for c in candidates) and not inner.corrupted:
                    paths = list((self.root / 'workspace/runs').glob('*/report.json'))
                    paths[0].write_text('{"wrong":true}', 'utf-8')
                    inner.corrupted = True
                chosen = next(c['id'] for c in candidates if c['id'] != 'stop')
                return {'backend': 'anyjev', 'probabilities': {c['id']: float(c['id'] == chosen) for c in candidates}}
            def close(inner): pass
        self.engine.local = CorruptOnce()
        self.engine.model_ready = lambda role: True
        report = self.engine.run({**self.request(), 'backend': 'anyjev'})
        self.assertTrue(report['task_complete'])
        self.assertEqual(report['artifact_repairs'], 1)
        self.assertEqual(sum(e['event'] == 'invocation_started' and e['action'] == 'verify' for e in report['events']), 2)

    def test_source_change_prevents_delivery(self):
        source = self.write('a.csv', 'value,status\n2,ok\n')
        class ChangeSource:
            changed = False
            def request(inner, operation, payload, timeout):
                candidates = payload['candidates']
                if any(c['id'] == 'verify' for c in candidates) and not inner.changed:
                    source.write_text('value,status\n999,ok\n', 'utf-8')
                    inner.changed = True
                chosen = next(c['id'] for c in candidates if c['id'] != 'stop')
                return {'backend': 'anyjev', 'probabilities': {c['id']: float(c['id'] == chosen) for c in candidates}}
            def close(inner): pass
        self.engine.local = ChangeSource()
        self.engine.model_ready = lambda role: True
        report = self.engine.run({**self.request(), 'backend': 'anyjev'})
        self.assertFalse(report['task_complete'])
        self.assertFalse(any(e['event']=='invocation_started' and e['action']=='finish' for e in report['events']))

    def test_budget_stops_before_report_and_all_invalid_stops(self):
        self.write('a.csv', 'value,status\nNaN,bad\n')
        report = self.engine.run(self.request())
        self.assertFalse(report['task_complete'])
        self.write('a.csv', 'value,status\n1,ok\n')
        self.engine.config['workflow_max_steps'] = 2
        report = self.engine.run(self.request())
        self.assertFalse(report['task_complete'])
        self.assertEqual(report['invocation_attempts'], 2)


if __name__ == '__main__':
    unittest.main()
