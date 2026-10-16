"""Compare closed-loop task delivery with independently computed CSV references.

Fraction arithmetic is separate from the worker's Decimal statistics. This is a
declared dataset/report contract check, never an unrestricted semantic judge.
"""
import argparse
import csv
import hashlib
import json
import shutil
import statistics
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from core import Engine, ROOT


IMPLEMENTATION = ('workflow.py', 'core.py', 'local_models.py', 'app.py', 'ui.html', 'config.json',
    'answer_quality.py', 'task_contract.py', 'model_paths.py', 'offline_environment.py',
    'models/model-lock.json', 'evaluate_workflow.py', 'start.ps1', 'stop.ps1', 'open.ps1', '打开工作台.cmd',
    'tests/test_workflow.py', 'tests/ui_replay.cjs', 'tests/fixtures/ui-responses.json')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def independent_reference(path, column, status):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    values, missing, invalid = [], [], []
    for line, row in enumerate(rows, 2):
        raw = row[column].strip()
        if not raw:
            missing.append(line)
            continue
        try:
            number = Fraction(raw)
            if abs(number) > 10**12:
                raise ValueError()
            values.append((line, number))
        except (ValueError, ZeroDivisionError):
            invalid.append(line)
    numbers = [value for _, value in values]
    return {'rows': len(rows), 'numbers': numbers, 'values': values,
            'missing_rows': missing, 'invalid_rows': invalid,
            'status_counts': dict(Counter(row[status] for row in rows)) if status else {}}


def judge(case, report):
    expected = case['expected']
    actions = [e.get('action') for e in report['events'] if e['event'] == 'invocation_started']
    errors = [e.get('error', '') for e in report['events'] if e['event'] == 'invocation_failed']
    if expected.endswith('_stop'):
        expected_error = '缺少声明的字段' if expected == 'missing_column_stop' else '请选择1至2份CSV'
        passed = not report['task_complete'] and expected_error in '\n'.join(errors) and 'finish' not in actions
        return {'declared_contract_passed': passed, 'checks': {'correct_failure_and_no_delivery': passed},
                'semantic_verified': False, 'advisory_review': 'not_applicable'}
    checks = {'delivered': report['task_complete'], 'offline': report['remote_attempts'] == 0,
              'verify_before_finish': 'verify' in actions and 'finish' in actions and actions.index('verify') < actions.index('finish')}
    target = ROOT / 'workspace/runs' / report['run_id'] / 'report.json'
    if not report['task_complete'] or not target.exists():
        return {'declared_contract_passed': False, 'checks': checks, 'semantic_verified': False}
    result = json.loads(target.read_text('utf-8'))
    spec = result['contract']
    references = {}
    tolerance = Fraction(1, 2_000_000)  # six-decimal reporting precision
    for name in result['source_files']:
        path = ROOT / 'workspace/inbox' / spec['input_dir'] / name
        reference = independent_reference(path, spec['value_column'], spec['status_column'])
        references[name] = reference
        actual = result['statistics'][name]
        numbers = reference['numbers']
        correct = all(actual[key] == reference[key] for key in ('rows', 'missing_rows', 'invalid_rows', 'status_counts'))
        correct = correct and actual['numeric_rows'] == len(numbers) and result['source_files'][name]['sha256'] == digest(path)
        for key, value in (('minimum', min(numbers)), ('maximum', max(numbers)), ('mean', sum(numbers)/len(numbers)), ('median', statistics.median(numbers))):
            correct = correct and abs(Fraction(actual[key])-value) <= tolerance
        if spec['threshold'] is not None:
            selected = [(line, value) for line, value in reference['values'] if value > Fraction(spec['threshold'])]
            threshold = result['threshold_checks'][name]
            correct = correct and threshold['count'] == len(selected)
            correct = correct and [(row['source_row'], Fraction(row['value'])) for row in threshold['matches']] == selected
        checks[name + ':independent_numbers_rows_and_hash'] = correct
    if result['comparison']:
        comparison = result['comparison']; a = references[comparison['first']]; b = references[comparison['second']]
        checks['comparison'] = comparison['rows_delta'] == b['rows']-a['rows'] and abs(Fraction(comparison['mean_delta'])-(sum(b['numbers'])/len(b['numbers'])-sum(a['numbers'])/len(a['numbers']))) <= tolerance
    if case.get('include_suggestions'):
        checks['suggestions_not_claimed_verified'] = report['status'] == 'needs_review' and result.get('model_suggestions', {}).get('quality', {}).get('semantic_verified') is False
    return {'declared_contract_passed': all(checks.values()), 'checks': checks,
            'semantic_verified': False, 'advisory_review': 'pending_independent_review' if case.get('include_suggestions') else 'not_applicable'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--split', choices=['dev', 'final'], default='dev')
    parser.add_argument('--backend', choices=['anyjev', 'rules'], default='anyjev')
    args = parser.parse_args()
    path = ROOT / 'evaluation_data' / ('workflow-' + args.split + '.json')
    dataset = json.loads(path.read_text('utf-8'))
    snapshot = {name: digest(ROOT / name) for name in IMPLEMENTATION}
    if args.split == 'final':
        freeze = json.loads((ROOT / 'evaluation_data/release-v040.json').read_text('utf-8'))
        if freeze['holdout_sha256'] != digest(path) or snapshot != freeze['implementation_sha256']:
            raise ValueError('Holdout or implementation differs from frozen v0.4.0.')
        for name, value in freeze['fixture_sha256'].items():
            if digest(ROOT / name) != value:
                raise ValueError('Frozen fixture changed: ' + name)
    engine = Engine(); rows = []
    target = ROOT / 'logs/evaluations' / ('workflow-' + args.split + '-' + args.backend + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
    def save():
        report = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'split': dataset['split'],
                  'backend': args.backend, 'dataset_sha256': digest(path), 'implementation_sha256': snapshot,
                  'cases': len(rows), 'complete': len(rows) == len(dataset['cases']),
                  'declared_contract_passes': sum(row['review']['declared_contract_passed'] for row in rows),
                  'delivered_cases': sum(row['report']['task_complete'] for row in rows),
                  'remote_attempts': sum(row['report']['remote_attempts'] for row in rows),
                  'semantic_accuracy': None, 'review_method': 'Independent Fraction arithmetic and source hashes; not Qwen self-rating or complete semantic evaluation.',
                  'results': rows}
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        return report
    try:
        for case in dataset['cases']:
            folder = ROOT / 'workspace/inbox' / case['input_dir']
            folder.mkdir(parents=True, exist_ok=True)
            for name in case.get('fixtures', []):
                shutil.copy2(ROOT / name, folder / Path(name).name)
            request = {'mode': 'workflow', 'backend': args.backend, 'goal': case['goal'],
                       'allow_remote': False, 'network_available': False,
                       'workflow': {k: case[k] for k in ('input_dir', 'files', 'value_column', 'status_column', 'threshold', 'include_suggestions') if k in case}}
            report = engine.run(request)
            review = judge(case, report)
            rows.append({'case': case['id'], 'request': request, 'expected': case['expected'], 'report': report, 'review': review})
            save()
            print(case['id'], report['status'], report['invocation_attempts'], 'steps', 'contract=', review['declared_contract_passed'], flush=True)
    finally:
        engine.close(); result = save()
    print(json.dumps({k: v for k, v in result.items() if k not in ('results', 'implementation_sha256')}, ensure_ascii=False), flush=True)
    print(target, flush=True)


if __name__ == '__main__':
    main()
