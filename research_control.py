"""Local adaptations inspired by CRITIC and Reflexion; no upstream code copied.

Partial executable evidence and bounded, task-local failure memory, not semantic judges.
See reports/research-adaptation-20261016.md for attribution and limitations.
"""
import ast
import hashlib
import json
import math
import re
from decimal import Decimal
from fractions import Fraction

from answer_quality import protected_signals, source_units, task_kind
from task_contract import preservation_issues


def feedback_view(feedback):
    """Bound only the model view; full checks remain in invocation/result events."""
    def compact(value, depth=0):
        if isinstance(value, str):
            return value[:180]
        if isinstance(value, list):
            return [compact(v, depth+1) for v in value[:8]] if depth < 5 else '[details in log]'
        if isinstance(value, dict):
            return {k: compact(v, depth+1) for k, v in value.items()} if depth < 5 else '[details in log]'
        return value
    return {**compact(feedback), 'view_scope': 'bounded_preview; full evidence retained in result_checked event'}


def invocation_fingerprint(service, task, arguments):
    data = {'service': service, 'goal': task['goal'], 'input': task.get('input', ''),
            'arguments': arguments}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False).encode('utf-8')).hexdigest()


def validate_memory(memory):
    if not isinstance(memory, list) or len(memory) > 48:
        raise ValueError('失败记忆格式或数量不合格。')
    fields = {'fingerprint', 'goal', 'service', 'reason', 'run_id'}
    for item in memory:
        if not isinstance(item, dict) or set(item) != fields or any(not isinstance(v, str) for v in item.values()):
            raise ValueError('失败记忆字段不合格。')
        if not re.fullmatch(r'[a-f0-9]{64}', item['fingerprint']) or not re.fullmatch(r'[a-f0-9]{32}', item['run_id']):
            raise ValueError('失败记忆标识不合格。')
        if not 0 < len(item['goal']) <= 500 or len(item['reason']) > 500 or len(item['service']) > 64:
            raise ValueError('失败记忆长度不合格。')
    return memory


def remember_failure(memory, service, task, arguments, reason, run_id):
    fingerprint = invocation_fingerprint(service, task, arguments)
    if not any(item['fingerprint'] == fingerprint for item in memory):
        memory.append({'fingerprint': fingerprint, 'goal': task['goal'], 'service': service,
                       'reason': reason[:500], 'run_id': run_id})
    # Four persisted phases, each limited to twelve calls by default.
    del memory[:-48]


def rational_reference(expression):
    """Independent arithmetic representation, bounded to + - * /, not eval."""
    if not isinstance(expression, str) or not 0 < len(expression) <= 200:
        raise ValueError('reference expression length')
    tree = ast.parse(expression, mode='eval')
    if sum(1 for _ in ast.walk(tree)) > 60:
        raise ValueError('reference expression complexity')
    def visit(node, depth=0):
        if depth > 12:
            raise ValueError('reference expression depth')
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = Fraction(str(node.value))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand, depth+1) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult, ast.Div):
            a, b = visit(node.left, depth+1), visit(node.right, depth+1)
            if isinstance(node.op, ast.Add): value = a+b
            elif isinstance(node.op, ast.Sub): value = a-b
            elif isinstance(node.op, ast.Mult): value = a*b
            else: value = a/b
        else:
            raise ValueError('not covered by rational reference')
        if abs(value) > 10**12:
            raise ValueError('reference range')
        return value
    return visit(tree.body)


def evidence_checks(service, task, arguments, result, root):
    """Checks use input/program data; model assertions never establish correctness."""
    checks = []
    source = task.get('input', '')
    if service == 'calculator':
        try:
            reference = rational_reference(arguments['expression'])
        except (ValueError, ArithmeticError, SyntaxError):
            checks.append({'check': 'rational_arithmetic', 'status': 'not_checked',
                           'reason': 'Independent reference covers bounded + - * / only.'})
        else:
            value = result.get('value')
            valid = type(value) in (int, float) and math.isfinite(value) and math.isclose(value, float(reference), rel_tol=1e-12, abs_tol=1e-12)
            checks.append({'check': 'rational_arithmetic', 'status': 'passed' if valid else 'blocked',
                           'expected_fraction': str(reference), 'actual': value,
                           'scope': 'numeric_agreement_with_tolerance_only'})
    if service == 'text_stats':
        text = arguments['text']
        expected = {'characters': len(text), 'nonempty_lines': sum(bool(s.strip()) for s in text.splitlines()),
                    'whitespace_words': len(text.split())}
        for field, value in expected.items():
            checks.append({'check': field, 'status': 'passed' if type(result.get(field)) is int and result[field] == value else 'blocked',
                           'expected': value, 'actual': result.get(field)})
    if service == 'local_text' and result.get('answer_mode') != 'verified_source_quotes':
        output = result.get('draft', result.get('text', ''))
        kind = task_kind(task['goal'])
        if isinstance(output, str):
            issues = protected_signals(source, output, kind) + preservation_issues(source, output, kind)
            for issue in issues:
                if issue['check'] in ('added_numeric_literal', 'missing_numeric_literal'):
                    counterpart = source if issue['check']=='added_numeric_literal' else output
                    values = {Decimal(v) for v in re.findall(r'\d+(?:\.\d+)?', counterpart)}
                    remaining = [v for v in issue['values'] if Decimal(v) not in values]
                    if not remaining:
                        continue
                    issue = {**issue, 'values': remaining}
                checks.append({**issue, 'status': 'blocked', 'origin': 'program_source_comparison'})
    if result.get('answer_mode') == 'verified_source_quotes':
        evidence = result.get('evidence')
        documents = {}
        if service == 'knowledge_qa':
            documents = {d['id']: d['text'] for d in json.loads((root/'knowledge.json').read_text('utf-8'))}
        verified = isinstance(evidence, list) and bool(evidence)
        if verified:
            for item in evidence:
                if not isinstance(item, dict):
                    verified = False
                    break
                quote = item.get('quote')
                original = source if item.get('source_id') == 'user_input' and service == 'local_text' else documents.get(item.get('source_id'))
                valid = type(item.get('source_number')) is int and item['source_number'] > 0 and isinstance(quote, str) and bool(quote) and original is not None and (
                    quote in source_units(original) if service == 'local_text' else quote == original)
                checks.append({'check': 'source_quote', 'source_id': item.get('source_id'),
                    'quote': quote, 'status': 'passed' if valid else 'blocked',
                    'scope': 'exact_source_correspondence_not_relevance_or_truth'})
                verified = verified and valid
        # Reconstruct the entire allowed rendering; a true quote does not license extra claims.
        rendered = '\n'.join('“'+e['quote']+'” ['+str(e['source_number'])+']' for e in evidence) if verified else ''
        prefixes = ('原文要点（完整句摘录）：\n', '资料可提供以下原文依据：\n')
        complete = verified and result.get('text') in [p+rendered for p in prefixes]
        checks.append({'check': 'quote_only_rendering', 'status': 'passed' if complete else 'blocked',
                       'scope': 'no_unattributed_text_in_extract_only_answer'})
    # Preserve precise worker guard findings; they are program checks, not a model verdict.
    for issue in result.get('quality', {}).get('issues', [])[:20]:
        checks.append({'check': 'worker_guard', 'status': 'blocked', 'detail': issue})
    return checks
