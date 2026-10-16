import json
import unittest
from unittest.mock import patch
import test_agent
from test_agent import FakeLocal
from research_control import evidence_checks, invocation_fingerprint, validate_memory
from task_store import TaskStore


class RepairLocal(FakeLocal):
    def request(self, operation, payload, timeout):
        if operation == 'plan_agent':
            self.calls.append((operation, payload))
            return {'text': json.dumps({'input': payload['allowed_inputs'][0], 'parameters': {}}), 'truncated': False}
        if operation == 'decide_agent' and payload['state'].get('stage')=='result_feedback' and not payload['state']['feedback']['usable']:
            self.calls.append((operation, payload))
            return {'probabilities': {c['id']: float(c['id']=='replan') for c in payload['candidates']}, 'backend': 'test_double'}
        return super().request(operation, payload, timeout)


class ResearchTests(unittest.TestCase):
    setUp = test_agent.AgentTests.setUp
    tearDown = test_agent.AgentTests.tearDown
    run_agent = test_agent.AgentTests.run_agent

    def test_repair_cannot_erase_failure_or_replace_translation_with_counting(self):
        local = RepairLocal([], ['local_text', 'stop'], generated=RuntimeError('injected worker failure'))
        report = self.run_agent(local, goal='1. 翻译原文', input='Hello')
        self.assertEqual(report['invocation_attempts'], 1)
        self.assertEqual(report['plans'][1]['steps'][0]['goal'], '翻译原文')
        self.assertEqual(report['plans'][1]['repairs'], {'s1': 's2'})
        filtered = [e for e in report['events'] if e['event']=='candidates_filtered'][-1]
        self.assertNotIn('local_text', filtered['available'])
        self.assertNotIn('text_stats', filtered['available'])
        self.assertIn('失败记录', filtered['excluded']['local_text'])
        self.assertEqual(len(report['failure_memory']), 1)
        self.assertFalse(report['execution_complete'])
        self.assertTrue(any(e['event']=='controller_single_candidate' for e in report['events']))
        self.assertFalse(any(e['event']=='decision' and e.get('backend')=='program_single_candidate' for e in report['events']))
        loaded = TaskStore(self.root).load(report['task_id'])
        self.assertEqual(loaded['report']['failure_memory'], report['failure_memory'])

    def test_changed_input_has_distinct_attempt_identity(self):
        a = invocation_fingerprint('local_text', {'goal':'翻译', 'input':'a'}, {'text':'a'})
        b = invocation_fingerprint('local_text', {'goal':'翻译', 'input':'b'}, {'text':'b'})
        self.assertNotEqual(a, b)
        with self.assertRaises(ValueError):
            validate_memory([{'fingerprint': 'invented'}])

    def test_resume_retains_memory_but_allows_new_material(self):
        local = RepairLocal([], ['local_text', 'stop'], generated=RuntimeError('injected'))
        first = self.run_agent(local, goal='1. 翻译原文', input='Hello')
        self.engine.local = FakeLocal([], ['local_text', 'finish'], generated={'text':'早上好'})
        second = self.engine.continue_task(first['task_id'], {'input':'Good morning'})
        self.assertTrue(second['execution_complete'])
        self.assertEqual(second['failure_memory'], first['failure_memory'])

    def test_wrong_number_is_blocked_with_independent_reference(self):
        local = FakeLocal([], ['calculator', 'stop'])
        with patch.object(self.engine, 'invoke_local', return_value={'value': 99, 'expression': '0.1+0.2'}):
            report = self.run_agent(local, goal='1. 计算 0.1+0.2')
        self.assertEqual(report['subtask_results'], {})
        checked = next(e for e in report['events'] if e['event']=='result_checked')['validation']['checks'][0]
        self.assertEqual(checked['expected_fraction'], '3/10')
        self.assertEqual(checked['actual'], 99)
        self.assertEqual(checked['status'], 'blocked')

    def test_floating_roundoff_and_uncovered_operators_disclosed(self):
        checks = evidence_checks('calculator', {'goal':'calculate'}, {'expression':'0.1+0.2'}, {'value':0.1+0.2}, self.root)
        self.assertEqual(checks[0]['status'], 'passed')
        checks = evidence_checks('calculator', {'goal':'calculate'}, {'expression':'3//2'}, {'value':1}, self.root)
        self.assertEqual(checks[0]['status'], 'not_checked')

    def test_rewrite_checks_do_not_trust_worker_quality_label(self):
        checks = evidence_checks('local_text', {'goal':'改写原文', 'input':'会议周五召开。地点待定。'}, {},
            {'text':'会议周四召开，地点一号楼。', 'quality':{'status':'unverified'}}, self.root)
        self.assertTrue(any(c['check']=='added_time' and c['status']=='blocked' for c in checks))
        self.assertTrue(any(c['check']=='missing_or_changed_state' for c in checks))

    def test_equivalent_decimal_format_is_not_new_fact(self):
        checks = evidence_checks('local_text', {'goal':'总结原文', 'input':'均值3.000000。'}, {}, {'text':'均值3。'}, self.root)
        self.assertFalse(any(c['status']=='blocked' for c in checks))

    def test_quote_does_not_license_extra_claims(self):
        task = {'goal':'总结原文', 'input':'地点待定。'}
        result = {'answer_mode':'verified_source_quotes', 'evidence':[{'source_id':'user_input', 'source_number':1, 'quote':'地点待定。'}],
                  'text':'原文要点（完整句摘录）：\n“地点待定。” [1]\n已确认在一楼。'}
        checks = evidence_checks('local_text', task, {}, result, self.root)
        self.assertEqual(checks[-1]['status'], 'blocked')
        result['text']='原文要点（完整句摘录）：\n“地点待定。” [1]'
        checks = evidence_checks('local_text', task, {}, result, self.root)
        self.assertEqual(checks[-1]['status'], 'passed')
        self.assertFalse(any(c['status']=='blocked' for c in checks))

    def test_forged_reference_rejected_against_registered_document(self):
        (self.root/'knowledge.json').write_text(json.dumps([{'id':'one','text':'尚未验证。'}]), 'utf-8')
        result = {'answer_mode':'verified_source_quotes', 'evidence':[{'source_id':'one','source_number':1,'quote':'已经验证。'}],
                  'text':'资料可提供以下原文依据：\n“已经验证。” [1]'}
        checks = evidence_checks('knowledge_qa', {'goal':'资料问答'}, {}, result, self.root)
        self.assertEqual(checks[0]['status'], 'blocked')

    def test_evidence_exception_is_validation_failure_not_call_failure(self):
        local = FakeLocal([], ['local_text', 'stop'], generated={'text':'摘要'})
        with patch('agent.evidence_checks', side_effect=ValueError('injected checker failure')):
            report = self.run_agent(local, goal='1. 总结原文', input='资料。')
        self.assertEqual(report['successful_calls'], 1)
        self.assertEqual(report['subtask_results'], {})
        checked = next(e for e in report['events'] if e['event']=='result_checked')
        self.assertEqual(checked['validation']['checks'][0]['check'], 'evidence_checker_error')
