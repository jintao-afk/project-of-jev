import json
import tempfile
import unittest
from pathlib import Path
from core import Engine, ROOT, safe_calculate, validation
from answer_quality import parse_selection, source_units, protected_signals, task_kind, guard_generation
from local_models import Runtime


class FakeLocal:
    def __init__(self, initial, review):
        self.initial, self.review = initial, review
        self.calls = []

    def request(self, op, payload, timeout):
        self.calls.append(op)
        if op == 'decide':
            ids = [c['id'] for c in payload['candidates']]
            # Dispersed scores deliberately trigger review; source policy must win afterwards.
            p = {i: .3 if i == self.initial else .7 / (len(ids)-1) for i in ids}
            return {'probabilities': p, 'backend': 'anyjev'}
        if op == 'review_route':
            return {'choice': self.review}
        return {'text': '模型已返回', 'quality': {'status': 'unverified', 'semantic_verified': False}}

    def close(self):
        pass


class QualityTests(unittest.TestCase):
    def test_evidence_indices_reject_fabrication_and_bool(self):
        units = [{'quote': '未批准。'}]
        for raw in ('{"selected":[2]}', '{"selected":[true]}', '{"selected":[1,1]}', '{"selected":"1"}'):
            with self.assertRaises((ValueError, TypeError)):
                parse_selection(raw, units)
        self.assertEqual(parse_selection('{"selected":[1]}', units), [1])

    def test_whole_sentences_keep_qualifiers(self):
        self.assertEqual(source_units('未批准采购20台，仅允许测试2台。能耗未知。'),
                         ['未批准采购20台，仅允许测试2台。', '能耗未知。'])

    def test_summary_retains_negative_scope_even_if_model_omits_it(self):
        runtime = Runtime(str(ROOT), {})
        runtime._generate = lambda *args, **kwargs: {'text': '{"selected":[2]}', 'truncated': False, 'usage': {}}
        units = [{'source_id': 'user_input', 'source_number': 1, 'quote': '返回率不是正确率。'},
                 {'source_id': 'user_input', 'source_number': 1, 'quote': '记录共有8条。'}]
        result = runtime.select_evidence('总结原文，保留限制。', units, summary=True)
        self.assertEqual(result['evidence_selection']['model_selected'], [2])
        self.assertEqual(result['evidence_selection']['program_required'], [1])
        self.assertEqual([e['quote'] for e in result['evidence']], [u['quote'] for u in units])
        self.assertFalse(result['quality']['semantic_verified'])

    def test_partial_checks_cannot_claim_completion(self):
        r = validation({'text': '正确词语但虚构内容', 'sources': [{'id': 'x'}]}, {'contains': ['正确词语']})
        self.assertEqual(r['status'], 'needs_review')
        self.assertTrue(r['declared_checks_passed'])
        self.assertFalse(r['semantic_verified'])
        self.assertEqual(validation({'matches': [{'id': 'x'}]}, {'required_ids': ['x']})['status'], 'needs_review')

    def test_guard_rejection_does_not_trigger_ungrounded_recovery(self):
        result = {'text': '原文暂保留', 'quality': {'status': 'rejected_draft'}}
        self.assertEqual(validation(result, {'contains': ['原文']})['scope'], 'quality_guard_rejection')

    def test_numeric_and_polarity_signals(self):
        self.assertTrue(protected_signals('未批准2台，周三通知。', '批准5台，周四通知。', 'rewrite'))
        self.assertFalse(protected_signals('共有7台设备。', '1. 数量：7台设备。', 'extraction'))
        self.assertFalse(protected_signals('邮箱contact@example.invalid。', '邮箱：contact@example.invalid', 'extraction'))
        self.assertTrue(protected_signals('邮箱a@example.invalid。', '邮箱：b@example.invalid', 'extraction'))

    def test_source_contract_after_review(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp') as folder:
            root = Path(folder)
            (root/'config.json').write_text((ROOT/'config.json').read_text('utf-8'), 'utf-8')
            engine = Engine(root)
            engine.model_ready = lambda role: True
            engine.local = FakeLocal('local_text', 'knowledge_qa')
            report = engine.run({'goal': '润色输入，保留事实。', 'input': 'Jev是模块名称。'})
            self.assertEqual(report['action'], 'local_text')
            trace = [e['event'] for e in report['events']]
            self.assertLess(trace.index('route_review_finished'), trace.index('controller_override'))
            self.assertEqual(report['remote_attempts'], 0)

    def test_source_policy_does_not_launder_failed_qa(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp') as folder:
            root = Path(folder)
            (root/'config.json').write_text((ROOT/'config.json').read_text('utf-8'), 'utf-8')
            engine = Engine(root)
            engine.model_ready = lambda role: role == 'decision'
            engine.local = FakeLocal('local_text', 'local_text')
            report = engine.run({'goal': '本项目的依据是什么？'})
            self.assertEqual(report['status'], 'stopped')
            self.assertEqual(report['successful_calls'], 0)

    def test_missing_original_no_inference(self):
        runtime = Runtime(str(ROOT), {})
        runtime._generate = lambda *a, **k: self.fail('Missing material must not generate')
        self.assertEqual(runtime.generate({'goal': '翻译成日语。', 'text': ''})['answer_mode'], 'missing_material')

    def test_rewrite_aliases(self):
        for goal in ('润色这段话', '整理为简洁表述', '重写以下内容', '改写原文'):
            self.assertEqual(task_kind(goal), 'rewrite')

    def test_text_model_cannot_assert_actuation(self):
        result = guard_generation({'text': '好的，已将空调调至23度。'}, '把空调调至23度', '', 'general_qa')
        self.assertEqual(result['answer_mode'], 'unsupported_operation')
        self.assertNotIn('好的，已', result['text'])
        explanation = guard_generation({'text': '命令语法示例：```del file```'}, '解释如何删除文件', '', 'general_qa')
        self.assertNotIn('answer_mode', explanation)

    def test_calculator_rejects_code_and_bad_results(self):
        for value in ('__import__("os")', '2**100', '1/0', '1e300*1e300'):
            with self.assertRaises((ValueError, ArithmeticError)):
                safe_calculate(value)
        self.assertEqual(safe_calculate('(37-13)*4/8'), 12)


if __name__ == '__main__':
    unittest.main()
