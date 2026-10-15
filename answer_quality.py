"""Executable partial guards, never a general semantic correctness oracle."""
import json
import re
from task_contract import classify_text, preservation_issues

def task_kind(goal):
    return classify_text(goal)


def source_units(text):
    # Keep negation/qualifiers within whole sentences; do not select arbitrary substrings.
    return [m.group().strip() for m in re.finditer(r'[^。！？\n]+[。！？]?|[^\n]+$', text) if m.group().strip()]


def parse_selection(raw, units):
    text = raw.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    data = json.loads(text)
    ids = data.get('selected') if isinstance(data, dict) else None
    if not isinstance(ids, list) or len(ids) > 8 or any(type(i) is not int or i < 1 or i > len(units) for i in ids):
        raise ValueError('证据选择必须是至多8个有效原句编号。')
    if len(ids) != len(set(ids)):
        raise ValueError('证据编号重复。')
    return ids


def protected_signals(source, output, kind):
    issues = []
    if kind not in ('rewrite', 'writing', 'summary', 'extraction'):
        return issues
    source_numbers = set(re.findall(r'\d+(?:\.\d+)?', source))
    # List labels are formatting, not quantities.
    factual_output = re.sub(r'^\s*\d+[.)、]\s+', '', output, flags=re.M)
    output_numbers = set(re.findall(r'\d+(?:\.\d+)?', factual_output))
    if output_numbers - source_numbers:
        issues.append({'check': 'added_numeric_literal', 'values': sorted(output_numbers - source_numbers)})
    if kind == 'rewrite' and source_numbers - output_numbers:
        issues.append({'check': 'missing_numeric_literal', 'values': sorted(source_numbers - output_numbers)})
    # Conservative lexical indicators, not entailment or named-entity completeness.
    for pattern, label in ((r'(?:本|下|上)?周[一二三四五六日天]|\d{1,2}[:：]\d{2}', 'time'),
                           (r'[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', 'email')):
        src, out = set(re.findall(pattern, source)), set(re.findall(pattern, output))
        if out - src:
            issues.append({'check': 'added_' + label, 'values': sorted(out - src)})
        if kind == 'rewrite' and src - out:
            issues.append({'check': 'missing_' + label, 'values': sorted(src - out)})
    for phrase in ('原定', '原计划', '由于', '因为', '经研究', '经讨论', '因故', '因事', '决定'):
        if phrase in output and phrase not in source:
            issues.append({'check': 'unsupported_context_marker', 'value': phrase})
    for match in re.finditer(r'(暂定|拟定|预计|可能).{0,6}(?:下|本|上)?周[一二三四五六日天]', output):
        if match.group(1) not in source:
            issues.append({'check': 'added_tentative_time_marker', 'value': match.group()})
    if kind == 'rewrite' and re.search(r'没有|尚未|未批准|未同意|不能|不允许', source):
        if not re.search(r'没有|尚未|未|不能|不允许', output):
            issues.append({'check': 'lost_negation_indicator'})
    return issues


def guard_generation(result, goal, source, kind, preservation=True):
    issues = protected_signals(source, result['text'], kind)
    if preservation:
        issues.extend(preservation_issues(source, result['text'], kind))
    if kind == 'general_qa':
        # local_text has no actuation capability. Detect a subset of asserted
        # completion claims, regardless of the selected backend or confidence.
        completed_operation = re.search(
            r'(?:已经|已|成功|完成).{0,16}(?:删除|调至|调到|锁好|锁上|解锁|发送|打开文件|关闭空调)', result['text'])
        requested_execution = re.search(r'执行|删除|调到|调至|锁上|锁好|解锁', goal)
        command_draft = re.search(r'```|\bdel\s|Remove-Item|\brm\s', result['text'], re.I)
        explanation = re.search(r'如何|怎么|解释|教程|举例', goal)
        if completed_operation or (requested_execution and command_draft and not explanation):
            issues.append({'check': 'unsupported_actuation_or_execution_claim'})
    result['quality'] = {'method': 'literal_and_field_state_contract_v2' if preservation else 'protected_literal_and_context_signals_v1',
                         'status': 'rejected_draft' if issues else 'unverified',
                         'issues': issues, 'semantic_verified': False,
                         'limitations': '检查有限数字、时间、邮箱、背景、字段未知状态和否定关系；不能证明语义等价或完整事实性。'}
    if issues:
        result['draft'] = result['text']
        if any(i['check'] == 'unsupported_actuation_or_execution_claim' for i in issues):
            result['text'] = '本地文本服务没有设备控制或文件操作接口，无法执行或确认此操作；执行声明或命令草稿未交付。'
            result['answer_mode'] = 'unsupported_operation'
        elif kind == 'rewrite' and source.strip():
            result['text'] = '改写草稿触发事实保护检查，暂保留原文，未完成改写：\n' + source
            result['answer_mode'] = 'original_preserved_after_rejection'
        else:
            result['text'] = '生成草稿出现无法由输入确认的信息，已停止交付草稿。请核对或补充资料。'
            result['answer_mode'] = 'withheld_draft'
    return result
