"""Controller fault injection; these are not model quality measurements."""
from unittest.mock import patch
import unittest
import test_agent
from test_agent import FakeLocal, subtask


class FeedbackLocal(FakeLocal):
    def __init__(self, *args, feedback_action='continue', **kwargs):
        super().__init__(*args, **kwargs)
        self.feedback_action = feedback_action

    def request(self, operation, payload, timeout):
        if operation == 'decide_agent' and payload['state'].get('stage') == 'result_feedback':
            self.calls.append((operation, payload))
            return {'probabilities': {c['id']: float(c['id']==self.feedback_action) for c in payload['candidates']},
                    'backend': 'test_double'}
        return super().request(operation, payload, timeout)


class FeedbackTests(unittest.TestCase):
    setUp = test_agent.AgentTests.setUp
    tearDown = test_agent.AgentTests.tearDown
    run_agent = test_agent.AgentTests.run_agent
    def test_feedback_stop_retains_output_without_running_next_step(self):
        local = FeedbackLocal([], ['calculator'], feedback_action='stop')
        report = self.run_agent(local, goal='1. 计算 3+4\n2. 计算 5+6')
        self.assertEqual(report['invocation_attempts'], 1)
        self.assertEqual(report['subtask_results']['s1']['result']['value'], 7)
        self.assertEqual(report['pending_subtasks'][0]['id'], 's2')
        self.assertEqual(report['feedback_decisions'], 1)

    def test_failure_requests_input_and_does_not_accept_failed_result(self):
        local = FeedbackLocal([], ['local_text'], generated=RuntimeError('missing terminology context'), feedback_action='ask_input')
        report = self.run_agent(local, goal='1. 翻译原文', input='bank')
        self.assertEqual(report['status'], 'waiting_input')
        self.assertEqual(report['subtask_results'], {})
        self.assertIn('missing terminology context', report['reason'])

    def test_invalid_feedback_cannot_skip_checks(self):
        local = FeedbackLocal([], ['local_text'], generated={'text': 'bad', 'truncated': True}, feedback_action='continue')
        report = self.run_agent(local, goal='1. 翻译原文', input='Hello')
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(report['subtask_results'], {})
        self.assertIn('概率', report['reason'])

    def test_counter_corruption_is_blocked(self):
        local = FeedbackLocal([], ['text_stats'], feedback_action='stop')
        with patch.object(self.engine, 'invoke_local', return_value={'characters': 999, 'nonempty_lines': 1, 'whitespace_words': 1}):
            report = self.run_agent(local, goal='1. 统计原文字符数', input='abc')
        self.assertEqual(report['subtask_results'], {})
        checks = [e for e in report['events'] if e['event']=='result_checked']
        self.assertEqual(checks[0]['validation']['status'], 'blocked')

    def test_review_needed_is_not_execution_failure(self):
        local = FeedbackLocal([], ['local_text', 'finish'], generated={'text': '你好'})
        report = self.run_agent(local, goal='1. 翻译原文', input='Hello')
        self.assertTrue(report['execution_complete'])
        self.assertIsNone(report['semantic_accuracy'])
        feedback = next(p['state']['feedback'] for op, p in local.calls if p.get('state', {}).get('stage')=='result_feedback')
        self.assertTrue(feedback['usable'])
        self.assertEqual(feedback['validation']['status'], 'needs_review')

    def test_budget_exhaustion_does_not_claim_feedback_or_completion(self):
        self.engine.config['agent_max_steps'] = 1
        report = self.run_agent(FeedbackLocal([], ['calculator']), goal='1. 计算 3+4')
        self.assertFalse(report['execution_complete'])
        self.assertEqual(report['feedback_decisions'], 0)
        self.assertIsNotNone(report['feedback_pending'])

    def test_feedback_replan_preserves_failure_and_remaining_goal(self):
        local = FeedbackLocal([[subtask('s2', '统计原文字符数')]], ['local_text', 'text_stats'],
            generated=RuntimeError('worker failure'), feedback_action='replan')
        report = self.run_agent(local, goal='1. 翻译原文', input='Hello')
        self.assertEqual(report['replans'], 1)
        outline = next(p for op, p in local.calls if op=='outline_agent')
        self.assertEqual(outline['feedback']['recent_feedback'][0]['reason'], 'worker failure')
        self.assertEqual(outline['feedback']['remaining_plan'][0]['goal'], '翻译原文')
