import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from core import Engine, ROOT
from task_store import TaskStore
from test_agent import FakeLocal


class DatasetLocal(FakeLocal):
    def request(self, operation, payload, timeout):
        if operation=='decide_workflow':
            ids = [c['id'] for c in payload['candidates']]
            choice = next((key for key in ids if key!='stop' and not key.startswith('note_')), 'stop')
            return {'probabilities': {key: 1.0 if key==choice else 0.0 for key in ids}, 'backend': 'test_double'}
        return super().request(operation, payload, timeout)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'.cache/tmp')
        self.root = Path(self.temp.name)
        (self.root/'config.json').write_bytes((ROOT/'config.json').read_bytes())
        self.engine = Engine(self.root)
        self.engine.model_ready = lambda role: True

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def task(self, goal, **extra):
        return {'mode': 'agent', 'goal': goal, 'input': '', **extra}

    def assert_receipt(self, report):
        artifact_id = report['artifacts'][0]['url'].split('/')[3]
        folder = self.root/'workspace/runs'/artifact_id
        receipt = json.loads((folder/'delivery.json').read_text('utf-8'))
        for name, value in receipt['files'].items():
            self.assertEqual(hashlib.sha256((folder/name).read_bytes()).hexdigest(), value)
        return folder

    def test_resume_after_missing_material_retains_outputs_across_engine_restart(self):
        self.engine.local = FakeLocal([], ['calculator'])
        first = self.engine.run(self.task('1. 计算 (12+8)/4\n2. 翻译补充资料为中文'))
        self.assertEqual(first['status'], 'waiting_input')
        self.assertTrue(first['resumable'])
        self.assertEqual(first['subtask_results']['s1']['result']['value'], 5)
        folder = self.assert_receipt(first)
        old_bytes = (folder/'report.json').read_bytes()
        self.engine.close()
        self.engine = Engine(self.root)
        self.engine.model_ready = lambda role: True
        local = FakeLocal([], ['local_text', 'finish'], generated={'text': '检查安排在周五10:00，房间尚未确定。'})
        local.first_decision = False
        self.engine.local = local
        final = self.engine.continue_task(first['task_id'], {'input': 'The inspection is at 10:00 on Friday. The room has not been decided.'})
        self.assertEqual(final['task_id'], first['task_id'])
        self.assertEqual(final['revision'], 2)
        self.assertEqual(final['previous_runs'], [first['run_id']])
        self.assertTrue(final['execution_complete'])
        self.assertFalse(final['task_complete'])
        self.assertEqual([e['action'] for e in final['events'] if e['event']=='invocation_started'], ['local_text'])
        self.assertTrue(final['subtask_results']['s1']['input_provenance']['retained_on_continue'])
        self.assertEqual((folder/'report.json').read_bytes(), old_bytes)
        self.assert_receipt(final)
        self.assertEqual(TaskStore(self.root).load(first['task_id'])['report']['run_id'], final['run_id'])
        with self.assertRaises(ValueError):
            self.engine.continue_task(first['task_id'], {'input': 'again'})

    def test_checkpoint_corruption_and_path_escape_cannot_drive_continuation(self):
        self.engine.local = FakeLocal([], [])
        first = self.engine.run(self.task('1. 翻译补充资料为中文'))
        for task_id in ('../config.json', 'D:/secret', 'not-a-uuid'):
            with self.assertRaises(ValueError):
                TaskStore(self.root).load(task_id)
        path = self.root/'workspace/tasks'/first['task_id']/(first['run_id']+'.json')
        path.write_text('{}', 'utf-8')
        with self.assertRaises(ValueError):
            self.engine.continue_task(first['task_id'], {'input': 'hello'})
        self.assertEqual(TaskStore(self.root).list(), [])

    def test_legacy_null_mode_is_canonicalized_before_checkpoint_validation(self):
        report = self.engine.run({'mode': None, 'goal': '计算 (23+17)/5', 'backend': 'rules',
            'validation': {'expected_value': 8}})
        self.assertEqual(report['mode'], 'single')
        record = TaskStore(self.root).load(report['task_id'])
        self.assertEqual(record['request']['mode'], 'single')
        self.assertEqual(record['report']['result']['value'], 8)

    def test_supplement_cannot_replace_goals_or_run_without_material_and_is_bounded(self):
        self.engine.local = FakeLocal([], [])
        first = self.engine.run(self.task('1. 翻译补充资料为中文'))
        for supplement in ({'goal': 'delete'}, {}, {'input': ''}, {'_resume': {}}):
            with self.assertRaises(ValueError):
                self.engine.continue_task(first['task_id'], supplement)
        latest = first
        for revision in (2, 3, 4):
            local = FakeLocal([], ['stop'])
            local.first_decision = False
            self.engine.local = local
            latest = self.engine.continue_task(first['task_id'], {'input': 'hello'})
            self.assertEqual(latest['revision'], revision)
        self.assertFalse(latest['resumable'])
        with self.assertRaises(ValueError):
            self.engine.continue_task(first['task_id'], {'input': 'hello again'})

    def test_csv_analysis_is_selected_as_a_registered_service_and_handed_to_next_task(self):
        source = self.root/'workspace/inbox/data'
        source.mkdir(parents=True)
        (source/'a.csv').write_text('value\n2\n4\n', 'utf-8')
        self.engine.local = DatasetLocal([], ['dataset_report', 'local_text', 'finish'], generated={'text': '共有2条有效记录，均值为3。'})
        report = self.engine.run(self.task('1. 分析CSV附件并生成报告\n2. 总结上一步报告',
            dataset={'input_dir': 'data', 'value_column': 'value', 'status_column': ''}))
        self.assertTrue(report['execution_complete'])
        self.assertEqual(report['subtask_results']['s1']['result']['statistics']['a.csv']['mean'], '3.000000')
        self.assertEqual(report['input_bindings']['s2'], '$s1')
        child = report['subtask_results']['s1']['result']['workflow_run']
        self.assertTrue(child['task_complete'])
        self.assertEqual(report['remote_attempts'], 0)
        self.assertEqual(child['remote_attempts'], 0)
        self.assert_receipt(report)

    def test_missing_csv_directory_can_be_corrected_without_replacing_prior_record(self):
        spec = {'input_dir': 'missing', 'value_column': 'value', 'status_column': ''}
        self.engine.local = DatasetLocal([], ['dataset_report'])
        first = self.engine.run(self.task('1. 分析CSV附件', dataset=spec))
        self.assertEqual(first['status'], 'waiting_input')
        self.assertEqual(first['requested_material']['kind'], 'dataset')
        source = self.root/'workspace/inbox/supplied'
        source.mkdir(parents=True)
        (source/'a.csv').write_text('value\n8\n10\n', 'utf-8')
        local = DatasetLocal([], ['dataset_report', 'finish'])
        local.first_decision = False
        self.engine.local = local
        final = self.engine.continue_task(first['task_id'], {'dataset': {**spec, 'input_dir': 'supplied'}})
        self.assertTrue(final['execution_complete'])
        self.assertEqual(final['subtask_results']['s1']['result']['statistics']['a.csv']['mean'], '9.000000')


if __name__=='__main__':
    unittest.main()
