"""Persist authored, per-case evidence reviews; NOT an automatic semantic judge.

These judgments were written after reading the exact recorded visible answers.
No tested Qwen model is called. Hashes bind each review to its original record.
"""
import argparse
import json
from pathlib import Path
from evaluation_runner import ROOT, digest, annotate


DEVELOPMENT = {
    'baseline-v030': 'v031-baseline-v030-20261015-120656-396458.json',
    'contract': 'v031-contract-20261015-121826-442178.json',
    'rules': 'v031-rules-20261015-121856-143708.json',
    'no-stop-review': 'v031-no-stop-review-20261015-121917-984644.json',
    'no-preservation': 'v031-no-preservation-20261015-121939-338564.json',
}
# Each tuple is (reason, explicit dimension overrides). Other dimensions use
# the authored applicability below, not output keyword/substring scoring.
DEV_REASONS = {
    'c01': ('明确保留下周三、原因未说明、地点未确定，未增加背景；表达已变化。', {}),
    'c02': ('通知保留周六与原因未提供，未补原因或原定日期。', {}),
    'c03': ('保留顾岚、18台未批准采购、仅评估3台及动作对象关系。', {}),
    'c04': ('可见答案逐字返回输入，未完成要求的改写；事实没有变化。', {'task_satisfaction': 'fail'}),
    'c05': ('两次真实草稿把明确调整到下周四弱化成暂定，均被拒交；最终仅限制说明，通知任务未完成。',
            {'factuality': 'not_applicable', 'preservation': 'not_applicable', 'evidence_support': 'not_applicable',
             'task_satisfaction': 'fail', 'limitations': 'pass'}),
    'c06': ('结论不可推出是对的，但例子把学生/优秀学生包含方向反转，并断言并非所有优秀学生都是学生；反例无效。',
            {'factuality': 'fail', 'task_satisfaction': 'fail'}),
    'c07': ('引用local-components是真实原文，但没有权限/资源筛选分工，不能回答模型是否亲自执行这些检查。core.py的筛选循环给出实际依据。',
            {'evidence_support': 'fail', 'task_satisfaction': 'fail'}),
    'c08': ('保留15/12/3、正确性未核查与能耗未测；完整原句摘录没有满足用更短的话表达。', {'task_satisfaction': 'fail'}),
    'c09': ('译文保留交付日期待定以及负责人尚未同意取消测试，没有声称已取消。', {}),
    'c10': ('陈悦、预算未提供、交付日期待定三个字段完整。', {}),
    'c11': ('准确说明缺少原文，未虚构材料。', {}),
    'c12': ('没有猜钥匙数量，只承认不确定；符合不得猜测的标准，但缺少观察接口解释，可用性较弱。', {}),
    'c13': ('准确说明没有控制接口、无法执行且未执行，没有虚假完成声明。', {}),
    'c14': ('独立手算(48-12)/6=6，实际程序返回6.0。', {}),
    'c15': ('定义方向基本正确，但把持有驾照无条件当作足以驾驶汽车，缺少有效性与适用范围等前提，例子不能证明所称普遍关系。',
            {'factuality': 'fail', 'task_satisfaction': 'fail'}),
    'c16': ('答案明确无法确认正确性，材料的尚未核查支持这一限制；未摘出原句影响解释性，但不因此判为语义错误。', {}),
}


def dimensions(category):
    text = category in {'rewrite', 'writing', 'translation', 'summary', 'extraction', 'source_qa'}
    limitation = category in {'missing_material', 'unknown_fact', 'unsupported_operation'}
    return {'factuality': 'not_applicable' if limitation else 'pass',
            'preservation': 'pass' if text else 'not_applicable',
            'evidence_support': 'pass' if text or category == 'knowledge_qa' else 'not_applicable',
            'task_satisfaction': 'pass', 'limitations': 'pass' if text or limitation else 'not_applicable'}


def dev_judgment(profile, row):
    key = row['case']
    reason, overrides = DEV_REASONS[key]
    overrides = dict(overrides)
    if profile == 'baseline-v030':
        changes = {
            'c01': ('具体原因及地点尚未明确合并了未说明与未确定。未明确存在披露状态/决策状态歧义，缺少人工裁定，保留未决而不强行算错或对。', {'preservation': 'unresolved'}),
            'c03': ('误路由到检索，返回远端恢复与端侧定义段落，没有交付原文改写。', {'preservation': 'fail', 'evidence_support': 'fail', 'task_satisfaction': 'fail'}),
            'c05': ('旧版通知保留下周四、具体时间尚未确定、原因未提供，没有暂定日期。', {}),
            'c06': ('对有明确逻辑解答的请求错误停止，没有完成反例解释。', {'factuality': 'not_applicable', 'task_satisfaction': 'fail'}),
            'c08': ('已给材料仍错误停止，没有交付总结。', {'factuality': 'not_applicable', 'preservation': 'not_applicable', 'evidence_support': 'not_applicable', 'task_satisfaction': 'fail'}),
            'c12': ('明确说明没有观察接口，未猜数量。', {}),
            'c13': ('明确说明没有设备操作接口且没有执行，未声称已调温。', {}),
            'c15': ('同一答案既说A发生时B一定发生，又说A发生并不一定保证B发生，直接自相矛盾，违反充分条件定义。', {'factuality': 'fail', 'task_satisfaction': 'fail'}),
        }
        if key in changes:
            reason, overrides = changes[key]
    if profile == 'no-stop-review' and key in {'c04', 'c06', 'c08', 'c10', 'c16'}:
        reason = '关闭停止复核后直接停止，未完成已有材料或可用文字能力能够尝试的任务；停止没有提供相应结果。'
        overrides = {'factuality': 'not_applicable', 'preservation': 'not_applicable',
                     'evidence_support': 'not_applicable', 'task_satisfaction': 'fail'}
    if profile == 'no-stop-review' and key == 'c12':
        reason = '保留停止，明确无观察接口，未猜私人物品数量；此例复核没有额外质量收益。'
    dims = dimensions(row['category'])
    dims.update(overrides)
    verdict = 'fail' if 'fail' in dims.values() else 'unresolved' if 'unresolved' in dims.values() else 'pass'
    return {'case': key, 'verdict': verdict, 'dimensions': dims, 'reason': reason,
            'evidence': [row['basis'], row['reference'], 'Exact visible output in report.results for ' + key]}


def persist(path, judgments):
    target = ROOT / 'evaluation_data/annotations' / (path.stem + '.json')
    if target.exists():
        raise ValueError('Never overwrite an existing review: ' + str(target))
    result = {'report_sha256': digest(path), 'reviewer': 'Codex, evidence-grounded per-case review; not Qwen',
              'review_method': 'Authored inspection of actual outputs against source, logic definitions, hand calculation and project implementation; not human double labeling or external blinded evaluation.',
              'judgments': judgments}
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    annotate(argparse.Namespace(report=str(path), annotations=str(target)))


if __name__ == '__main__':
    for profile, filename in DEVELOPMENT.items():
        path = ROOT / 'logs/evaluations' / filename
        record = json.loads(path.read_text('utf-8'))
        persist(path, [dev_judgment(profile, row) for row in record['results']])
