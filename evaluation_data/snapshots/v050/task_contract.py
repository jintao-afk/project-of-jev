"""Explicit, auditable program contracts; neither semantic parsing nor truth oracle."""
import re


TEXT_PATTERNS = (
    ('translation', r'翻译|翻成|译为|译成|转换成.*[语文]'),
    ('summary', r'总结|概括|提炼|归纳|压缩|用更短的话|缩短.{0,8}(?:文字|内容|记录)'),
    ('extraction', r'提取|抽取|找出|列出'),
    ('rewrite', r'改写|重写|润色|整理为|换一种(?:说法|表达)|说得.{0,6}(?:正式|自然|通顺)|改得.{0,6}(?:正式|自然|通顺)'),
    ('source_qa', r'(?:根据|依据|仅用|只用|基于|仅参考).*(?:下述|下面|以下|给定|输入|这段|材料|原文)'),
    ('writing', r'写|拟.*(?:通知|通告)|起草'),
)
SOURCE_OPERATIONS = {'translation', 'summary', 'rewrite', 'extraction', 'source_qa'}
FIELDS = {
    'reason': r'(?:延期)?原因|缘由',
    'delivery_date': r'交付日期|交货日期|交期',
    'time': r'具体时间|具体时刻|时间|时刻',
    'place': r'地点|场地',
    'budget': r'预算|经费',
    'owner': r'负责人',
    'energy': r'能耗|功耗',
    'correctness': r'正确性|答案质量|质量评价',
}
STATES = (
    ('unverified', r'(?:尚未|还未|未)(?:核查|验证|检查|评估|评价)'),
    ('unmeasured', r'(?:尚未|还未|未)(?:测量|实测|测定)|未测'),
    ('undecided', r'(?:尚未|还未|未)(?:确定|决定)|待定|未定'),
    ('undisclosed', r'(?:尚未|还未|未)(?:公布|公开|发布)'),
    ('unprovided', r'(?:尚未|还未|未)(?:说明|提供|给出|交代)|不详'),
    ('unknown', r'未知|不清楚|不知道'),
)
NEGATION = r'没有|尚未|还未|并未|不曾|未|不能|不'
ACTIONS = r'批准|同意|授权|允许|取消|完成|通过|采购|购入'


def classify_text(goal):
    for kind, pattern in TEXT_PATTERNS:
        if re.search(pattern, goal):
            return kind
    return 'general_qa'


def clauses(text):
    return [part.strip() for part in re.split(r'[，,。！？!?；;\n]', text) if part.strip()]


def state_slots(text):
    slots = []
    for clause in clauses(text):
        states = [(m.start(), m.end(), state, m.group()) for state, pattern in STATES
                  for m in re.finditer(pattern, clause)]
        for field, pattern in FIELDS.items():
            for match in re.finditer(pattern, clause):
                if not states:
                    continue
                closest = min(states, key=lambda item: min(abs(item[0] - match.end()), abs(item[1] - match.start())))
                slots.append({'field': field, 'state': closest[2], 'source_clause': clause,
                              'state_span': closest[3]})
    return [dict(item) for i, item in enumerate(slots)
            if (item['field'], item['state']) not in {(s['field'], s['state']) for s in slots[:i]}]


def polarity_slots(text):
    slots = []
    for clause in clauses(text):
        for match in re.finditer(r'(' + NEGATION + r').{0,5}?(' + ACTIONS + r')', clause):
            # Quantities are bound to this assertion, not just a document-wide set.
            quantities = re.findall(r'\d+(?:\.\d+)?', clause)
            slots.append({'action': match.group(2), 'negative': True,
                          'quantities': quantities, 'source_clause': clause})
    return slots


def unsupported_execution(goal):
    if re.search(r'如何|怎么|解释|教程|举例|语法|能否|是否能', goal):
        return False
    return bool(re.search(r'(?:删除|清空).{0,20}(?:文件|目录|磁盘|[CDE]盘)|'
                          r'(?:打开|关闭|调至|调到|调成|解锁|锁上|锁好).{0,15}(?:空调|门锁|房门)|'
                          r'(?:空调|门锁|房门).{0,15}(?:调至|调到|调成|打开|关闭|解锁|锁上)', goal, re.I))


def build_contract(task, reference_required=False):
    goal = task['goal']
    kind = classify_text(goal)
    source = task.get('parameters', {}).get('text', task.get('input', ''))
    # validate_task handles the request envelope; parameter errors stay explicit.
    source = source if isinstance(source, str) else ''
    has_source = bool(source.strip())
    expression = task.get('parameters', {}).get('expression')
    if expression is not None:
        operation, preferred = 'calculation', 'calculator'
    elif re.search(r'统计|字符数|词数', goal):
        operation, preferred = 'text_stats', 'text_stats'
    elif re.search(r'检索|查找|查询', goal) and not has_source and not re.search(r'回答|解释|说明', goal):
        operation, preferred = 'retrieve', 'retrieve'
    elif reference_required:
        operation, preferred = 'reference_qa', 'knowledge_qa'
    else:
        operation, preferred = kind, 'local_text'
    blocked = None
    if kind == 'general_qa' and unsupported_execution(goal):
        blocked = 'unsupported_operation'
    elif kind in SOURCE_OPERATIONS and not has_source and not reference_required:
        blocked = 'missing_material'
    facts = source or (goal if kind == 'writing' else '')
    return {'schema_version': 1, 'method': 'explicit_program_contract_v1',
            'operation': operation, 'text_operation': kind, 'preferred_capability': preferred,
            'has_source': has_source, 'evidence_required': reference_required or kind == 'source_qa',
            'blocked_reason': blocked, 'state_slots': state_slots(facts),
            'negative_assertions': polarity_slots(facts),
            'literal_numbers': sorted(set(re.findall(r'\d+(?:\.\d+)?', facts))),
            'output_constraints': {'single_sentence': bool(re.search(r'一句话|一句(?:表述|说明)', goal)),
                                   'preserve_information': kind in ('rewrite', 'translation', 'extraction'),
                                   'no_added_facts': kind in SOURCE_OPERATIONS | {'writing'}},
            'limitations': '有限显式措辞与字段规则；可能漏识别或误分类，不是完整语义解析或正确性证明。'}


def preservation_issues(source, output, kind):
    if kind not in ('rewrite', 'writing', 'summary', 'extraction'):
        return []
    issues = []
    out_slots = {(s['field'], s['state']) for s in state_slots(output)}
    for slot in state_slots(source):
        if (slot['field'], slot['state']) not in out_slots:
            issues.append({'check': 'missing_or_changed_state', 'field': slot['field'],
                           'expected_state': slot['state'], 'source_clause': slot['source_clause']})
    if kind == 'rewrite':
        output_negatives = polarity_slots(output)
        for assertion in polarity_slots(source):
            if not any(s['action'] == assertion['action'] and s['quantities'] == assertion['quantities']
                       for s in output_negatives):
                issues.append({'check': 'lost_or_rebound_negative_assertion', **assertion})
    return issues


def stop_review_reason(contract, available):
    if contract['blocked_reason']:
        return None
    preferred = contract['preferred_capability']
    if preferred not in available:
        return None
    if contract['text_operation'] in SOURCE_OPERATIONS and not contract['has_source']:
        return None
    return {'preferred_capability': preferred, 'operation': contract['operation'],
            'reason': '存在与显式任务类型匹配的可用能力；复核能否处理，不强制回答或证明事实已知。'}
