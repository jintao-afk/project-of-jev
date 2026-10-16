import json
import tempfile
import unittest
from pathlib import Path

from agent import parse_plan
from core import Engine, ROOT


def subtask(key='s1', goal='计算 (18+24)/6', source='$input', **params):
    return {'id': key, 'goal': goal, 'input': source, 'parameters': params}


class FakeLocal:
    """Deterministic test double, never reported as actual model inference."""
    def __init__(self, plans, choices, generated=None, review='stop'):
        self.plans_list = plans
        self.plans = iter(plans)
        self.choices = iter(choices)
        self.generated = generated
        self.review = review
        self.calls = []
        self.first_decision = True
        self.outline_index = 0
        self.active_plan = None

    def request(self, operation, payload, timeout):
        self.calls.append((operation, payload))
        if operation == 'outline_agent':
            self.active_plan = None
            plan = self.plans_list[self.outline_index]
            if not isinstance(plan, list):
                plan = next((p for p in self.plans_list if isinstance(p, list)), [subtask()])
            self.outline_index += 1
            return {'text': json.dumps({'objectives': [s['goal'] for s in plan]}), 'truncated': False}
        if operation == 'plan_agent':
            if self.active_plan is None:
                self.active_plan = next(self.plans)
            value = self.active_plan
            if isinstance(value, str):
                self.active_plan = None
                return {'text': value, 'truncated': False}
            item = next(s for s in value if s['goal'] == payload['objective'])
            return {'text': json.dumps({'input': item['input'], 'parameters': item['parameters']}), 'truncated': False}
        if operation == 'decide_agent':
            if payload['state'].get('stage') == 'input_binding':
                source = payload['state']['current_subtask']['input']
                if '上一步' in payload['state']['current_subtask']['goal']:
                    source = '$'+next(reversed(payload['state']['available_results']))
                return {'probabilities': {c['id']: 1.0 if c['id']==source else 0.0 for c in payload['candidates']}, 'backend': 'test_double'}
            if self.first_decision and payload['state'].get('stage')=='whole_task_capability_check':
                self.first_decision = False
                return {'probabilities': {c['id']: 1.0 if c['id']=='plan' else 0.0 for c in payload['candidates']}, 'backend': 'test_double'}
            choice = next(self.choices)
            ids = [c['id'] for c in payload['candidates']]
            assert choice in ids, (choice, ids)
            return {'probabilities': {key: 1.0 if key == choice else 0.0 for key in ids}, 'backend': 'test_double'}
        if operation == 'review_agent':
            return {'choice': self.review, 'reason': 'test double'}
        if operation == 'generate':
            if isinstance(self.generated, Exception):
                raise self.generated
            return self.generated
        raise AssertionError(operation)

    def close(self):
        pass


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp')
        self.root = Path(self.temp.name)
        (self.root/'config.json').write_bytes((ROOT/'config.json').read_bytes())
        self.engine = Engine(self.root)
        self.engine.model_ready = lambda role: True

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def run_agent(self, local, **extra):
        self.engine.local = local
        return self.engine.run({'mode': 'agent', 'goal': '完成两项任务', 'input': '原文', **extra})

    def test_plan_references_are_bounded_and_original_material_is_not_replaced(self):
        good = [subtask(expression='2+3'), subtask('s2', '统计结果字符数', '$s1')]
        self.assertEqual(parse_plan(json.dumps({'steps': good}), {}), good)
        for bad in ([subtask(source='编造的资料')], [subtask(source='$s2')],
                    [subtask(), subtask()], [subtask(command='del *')],
                    [subtask(source='$input.value')], [subtask(query='$s1')]):
            with self.assertRaises(ValueError):
                parse_plan(json.dumps({'steps': bad}), {})

    def test_real_program_tools_and_result_dependency_do_not_claim_semantic_completion(self):
        plan = [subtask(expression='(18+24)/6'), subtask('s2', '统计结果字符数', '$s1')]
        result = self.run_agent(FakeLocal([plan], ['calculator', 'text_stats', 'finish']))
        self.assertTrue(result['execution_complete'])
        self.assertFalse(result['task_complete'])
        self.assertEqual(result['subtask_results']['s1']['result']['value'], 7.0)
        self.assertEqual(result['subtask_results']['s2']['result']['characters'], 3)
        self.assertEqual(result['remote_attempts'], 0)
        self.assertEqual(result['decision_calls'], 5)
        self.assertEqual(len(result['plans']), 1)
        self.assertEqual(len(result['plans'][0]['steps']), 2)
        self.assertEqual(len(next(e for e in result['events'] if e['event']=='plan_accepted')['plan']), 2)
        self.assertEqual(result['status'], 'needs_review')

    def test_failed_call_is_feedback_then_replan_preserves_completed_results(self):
        plan = [subtask(expression='2+3'), subtask('s2', '解释结果', '$s1')]
        revised = [subtask('s3', '统计结果字符数', '$s1')]
        local = FakeLocal([plan, revised], ['calculator', 'local_text', 'replan', 'text_stats', 'finish'], generated=RuntimeError('GPU fault'))
        result = self.run_agent(local)
        self.assertTrue(result['execution_complete'])
        self.assertEqual(result['replans'], 1)
        self.assertEqual(set(result['subtask_results']), {'s1', 's3'})
        requests = [payload for op, payload in local.calls if op == 'decide_agent' and payload['state'].get('stage') != 'input_binding']
        self.assertTrue(requests[3]['state']['recent_feedback'])
        self.assertNotIn('local_text', [c['id'] for c in requests[3]['candidates']])

    def test_rejected_draft_is_not_used_as_input_for_next_step(self):
        plan = [subtask(goal='改写原文'), subtask('s2', '统计改写结果', '$s1')]
        local = FakeLocal([plan], ['local_text', 'stop'], generated={'text': '原文', 'quality': {'status': 'rejected_draft'}})
        result = self.run_agent(local)
        self.assertFalse(result['execution_complete'])
        self.assertEqual(result['subtask_results'], {})
        self.assertTrue(any(e['event'] == 'result_blocked' for e in result['events']))

    def test_stop_review_can_continue_but_never_silently_forces_rules(self):
        local = FakeLocal([[subtask(expression='2+3')]], ['stop', 'finish'], review='calculator')
        result = self.run_agent(local)
        self.assertTrue(result['execution_complete'])
        self.assertEqual(result['route_reviews'], 1)
        self.assertEqual([e['choice'] for e in result['events'] if e['event'] == 'decision'], ['plan', 'stop', 'finish'])
        self.assertFalse(any(e['event'] == 'controller_override' for e in result['events']))

    def test_stop_keeps_partial_outputs_and_pending_goal(self):
        plan = [subtask(expression='2+3'), subtask('s2', '打开设备', '$input')]
        result = self.run_agent(FakeLocal([plan], ['calculator', 'stop']))
        self.assertFalse(result['execution_complete'])
        self.assertIn('s1', result['subtask_results'])
        self.assertEqual(result['pending_subtasks'][0]['id'], 's2')
        self.assertEqual(result['invocation_attempts'], 1)

    def test_invalid_plan_repair_and_failure_records(self):
        result = self.run_agent(FakeLocal(['not json', [subtask(expression='2+3')]], ['calculator', 'finish']))
        self.assertTrue(result['execution_complete'])
        self.assertTrue(any(e['event'] == 'plan_rejected' for e in result['events']))
        result = self.run_agent(FakeLocal(['bad', 'bad'], []))
        self.assertFalse(result['execution_complete'])
        self.assertEqual(result['invocation_attempts'], 0)
        self.assertEqual(sum(e['event']=='plan_rejected' for e in result['events']), 2)

    def test_no_remote_backend_and_no_missing_model_fallback(self):
        with self.assertRaises(ValueError):
            self.run_agent(FakeLocal([], []), backend='jev_api')
        self.engine.model_ready = lambda role: False
        result = self.run_agent(FakeLocal([], []))
        self.assertEqual(result['invocation_attempts'], 0)
        self.assertIn('未准备', result['reason'])

    def test_numbered_user_tasks_skip_model_planning_and_preserve_each_requirement(self):
        result = self.run_agent(FakeLocal([], ['calculator', 'calculator', 'finish']),
            goal='1. 计算 (18+24)/6\n2. 计算 (9+15)*2', input='')
        self.assertTrue(result['execution_complete'])
        self.assertEqual([v['result']['value'] for v in result['subtask_results'].values()], [7, 48])
        self.assertEqual(result['plans'][0]['source'], 'user_numbered_requirements')
        self.assertEqual(len(result['plans'][0]['steps']), 2)

    def test_counting_a_summary_is_not_overridden_as_another_summary(self):
        local = FakeLocal([], ['local_text', 'text_stats', 'finish'], generated={'text': '简短总结', 'quality': {'status': 'source_spans_verified'}})
        result = self.run_agent(local, goal='1. 总结原文\n2. 统计上一步总结结果的字符数')
        self.assertTrue(result['execution_complete'])
        self.assertEqual(result['subtask_results']['s2']['service'], 'text_stats')
        self.assertEqual(result['subtask_results']['s2']['result']['characters'], 4)
        self.assertEqual(result['input_bindings']['s2'], '$s1')


if __name__ == '__main__':
    unittest.main()
