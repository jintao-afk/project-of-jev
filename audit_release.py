"""Audit saved R1 CSV evidence with independent Fraction arithmetic; no inference."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from core import ROOT
from evaluate_workflow import judge


def main():
    pointer_path = ROOT/'logs/r1-verification.local.json'
    pointer = json.loads(pointer_path.read_text('utf-8'))
    source = ROOT/pointer['complete_file']
    if not source.resolve().is_relative_to((ROOT/'logs').resolve()):
        raise ValueError('验收记录不在项目日志目录。')
    complete = json.loads(source.read_text('utf-8'))
    case = next(c for c in complete['records'] if c['name']=='csv-to-summary-to-count')
    child = case['report']['subtask_results']['s1']['result']['workflow_run']
    log_path = Path(child['log_reference']['path'])
    if not log_path.resolve().is_relative_to((ROOT/'logs').resolve()):
        raise ValueError('子流程原始证据路径越界。')
    raw = log_path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=child['log_reference']['sha256']:
        raise ValueError('子流程原始证据已变化。')
    report = json.loads(raw)
    review = judge({'expected': 'report'}, report)
    if not review['declared_contract_passed']:
        raise AssertionError(review['checks'])
    output = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'saved CSV artifact: all declared statistics, full threshold rows, comparison, source hashes and verify-before-finish; not natural-language semantic accuracy',
        'reference': 'independent Fraction implementation in evaluate_workflow.py, separate from production Decimal',
        'acceptance_record': str(source.relative_to(ROOT)), 'acceptance_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'workflow_log': str(log_path.relative_to(ROOT)), 'workflow_sha256': child['log_reference']['sha256'],
        'review': review, 'semantic_accuracy': None}
    target = ROOT/'logs'/('r1-numeric-audit-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.json')
    with target.open('x', encoding='utf-8') as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)
    pointer['audit_file'] = str(target.relative_to(ROOT))
    pointer_path.write_text(json.dumps(pointer, ensure_ascii=False), 'utf-8')
    print(json.dumps({'all_declared_csv_checks': review['checks'], 'record': str(target)}, ensure_ascii=False))


if __name__=='__main__':
    main()
