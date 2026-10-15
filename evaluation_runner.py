"""Separate routing, execution, local checks and independently grounded review."""
import argparse
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from offline_environment import configure

ROOT = Path(__file__).resolve().parent
configure(ROOT)
from core import Engine


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


IMPLEMENTATION = ('core.py', 'local_models.py', 'config.json', 'request_normalization.py',
                  'model_paths.py', 'evaluation_runner.py', 'answer_quality.py', 'offline_environment.py',
                  'knowledge.json', 'models/model-lock.json', 'task_contract.py')


def summarize(rows):
    durations = [r['report']['total_ms'] for r in rows]
    ram = [e['available_ram_mb'] for r in rows for e in r['report']['events'] if e.get('available_ram_mb') is not None]
    peaks = [e.get('result', e).get('resources', {}).get('cuda_peak_allocated_mb')
             for r in rows for e in r['report']['events']]
    peaks = [p for p in peaks if p is not None]
    return {
        'cases': len(rows),
        'initial_decision_cases': sum(r['initial_choice'] is not None for r in rows),
        'preflight_or_other_no_decision_cases': sum(r['initial_choice'] is None for r in rows),
        'initial_route_matches': sum(r['initial_route_match'] for r in rows),
        'reviewed_cases': sum(r['review_choice'] is not None for r in rows),
        'review_route_matches': sum(r['review_route_match'] is True for r in rows),
        'controller_adjustments': sum(len(r['controller_adjustments']) for r in rows),
        'final_route_matches': sum(r['route_match'] for r in rows),
        'successful_calls': sum(r['report']['successful_calls'] for r in rows),
        'returned_cases': sum('result' in r['report'] for r in rows),
        'needs_review_cases': sum(r['report']['status'] == 'needs_review' for r in rows),
        'declared_checks_passed': sum(r['report'].get('validation', {}).get('declared_checks_passed',
                                      r['report'].get('task_complete', False)) for r in rows),
        'verified_complete_cases': sum(r['report']['task_complete'] for r in rows),
        'text_service_generations': sum(r['report'].get('generation_calls', 0) for r in rows),
        'generation_recovery_cases': sum(r['report'].get('result', {}).get('recovery', {}).get('attempted', False) for r in rows),
        'remote_attempts': sum(r['report']['remote_attempts'] for r in rows),
        'latency_ms': {'min': min(durations), 'median': statistics.median(durations),
                       'max': max(durations)} if rows else None,
        'resource_observations': {'minimum_available_ram_mb': min(ram) if ram else None,
                                  'worker_peak_cuda_allocated_mb': max(peaks) if peaks else None,
                                  'scope': 'RAM snapshots and cumulative worker Torch allocation peak, not energy or device total'},
        'semantic_accuracy': None, 'semantic_review': 'pending_independent_annotation',
    }


def evaluate(args):
    path = ROOT / ('acceptance_cases.json' if args.suite in ('acceptance', 'smoke')
                   else 'evaluation_data/' + args.suite + '.json')
    data = json.loads(path.read_text('utf-8'))
    cases = data if isinstance(data, list) else data['cases']
    if args.suite == 'smoke':
        cases = cases[:3]
    if args.suite == 'final':
        release = ROOT / 'evaluation_data/release.json'
        if not args.release or not release.exists():
            raise ValueError('Final holdout requires --release and a frozen release.json.')
        frozen = json.loads(release.read_text('utf-8'))
        if frozen['holdout_sha256'] != digest(path):
            raise ValueError('Holdout differs from frozen hash.')
        for name, value in frozen['implementation_sha256'].items():
            if digest(ROOT / name) != value:
                raise ValueError('Implementation differs from release: ' + name)
    if args.limit:
        if args.suite == 'final':
            raise ValueError('Final evaluation must run the whole suite.')
        cases = cases[:args.limit]
    folder = ROOT / 'logs/evaluations'
    folder.mkdir(exist_ok=True)
    stamp = datetime.now().astimezone().strftime('%Y%m%d-%H%M%S-%f')
    target = folder / f'{args.suite}-{args.backend}-{args.label}-{stamp}.json'
    engine, rows = Engine(), []
    snapshot = {name: digest(ROOT / name) for name in IMPLEMENTATION if (ROOT / name).exists()}
    def save(complete):
        report = {'suite': args.suite, 'backend': args.backend, 'label': args.label,
                  'created_at': datetime.now(timezone.utc).isoformat(), 'complete': complete,
                  'dataset_sha256': digest(path), 'implementation_sha256': snapshot,
                  'model': engine.config['decision_model'], 'offline': engine.config['offline_mode'],
                  'model_identity': 'independent AnyJev + Qwen, not commercial Jev',
                  'note': '路由、调用、局部验收与语义正确性分开；needs_review不等于调用失败。',
                  **summarize(rows), 'results': rows}
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        return report
    try:
        for case in cases:
            report = engine.run({**case['request'], 'backend': args.backend,
                                 'allow_remote': False, 'network_available': False})
            decisions = [e for e in report['events'] if e['event'] == 'decision']
            reviews = [e for e in report['events'] if e['event'] == 'route_review_finished']
            initial = decisions[0]['choice'] if decisions else None
            reviewed = reviews[0]['choice'] if reviews else None
            action = report.get('action', 'stop')
            final_routes = [e for e in report['events'] if e['event'] == 'route_finalized']
            rows.append({'case': case['id'], 'category': case.get('category'),
                         'request': case['request'], 'expected_routes': case['expected_routes'],
                         'reference': case.get('reference'), 'basis': case.get('basis'),
                         'rubric': case.get('rubric', case.get('review_guidance')),
                         'initial_choice': initial, 'initial_route_match': initial in case['expected_routes'],
                         'review_choice': reviewed,
                         'review_route_match': reviewed in case['expected_routes'] if reviewed else None,
                         'controller_adjustments': [e for e in report['events'] if e['event'] == 'controller_override'],
                         'route_trace': [e for e in report['events'] if e['event'] in
                                         ('decision', 'route_review_finished', 'controller_override', 'route_finalized')],
                         'final_selection': final_routes[-1]['choice'] if final_routes else 'stop',
                         'executed_actions': [e['action'] for e in report['events'] if e['event'] == 'invocation_started'],
                         'execution_trace': [e for e in report['events'] if e['event'] in
                                             ('invocation_started', 'invocation_finished', 'invocation_failed', 'controller_stop')],
                         'outcome_route': action,
                         'actual_route': action, 'route_match': action in case['expected_routes'],
                         'semantic_review': 'pending', 'report': report})
            save(False)
            print(f"{case['id']}: {initial} -> {action} / {report['status']} / {report['total_ms']} ms", flush=True)
    finally:
        engine.close()
        summary = save(len(rows) == len(cases))
    print(json.dumps({k: v for k, v in summary.items() if k not in ('results', 'implementation_sha256')},
                     ensure_ascii=False), flush=True)
    print('Evaluation record: ' + str(target), flush=True)
    if summary['remote_attempts']:
        raise RuntimeError('Offline evaluation issued remote requests.')


def annotate(args):
    report_path = Path(args.report)
    report = json.loads(report_path.read_text('utf-8'))
    annotation = json.loads(Path(args.annotations).read_text('utf-8'))
    if annotation['report_sha256'] != digest(report_path):
        raise ValueError('Annotations are not bound to this exact report.')
    judgments = {j['case']: j for j in annotation['judgments']}
    if len(judgments) != len(annotation['judgments']) or set(judgments) != {r['case'] for r in report['results']}:
        raise ValueError('Annotations must cover each case exactly once.')
    for j in judgments.values():
        if j['verdict'] not in ('pass', 'fail', 'unresolved') or not j.get('reason') or not j.get('evidence'):
            raise ValueError('Each annotation needs verdict, reason and independent evidence.')
        dimensions = j.get('dimensions', {})
        if set(dimensions) != {'factuality', 'preservation', 'evidence_support', 'task_satisfaction', 'limitations'}:
            raise ValueError('Each annotation must grade all five dimensions, using not_applicable when appropriate.')
        if any(v not in ('pass', 'fail', 'unresolved', 'not_applicable') for v in dimensions.values()):
            raise ValueError('Unknown dimension verdict.')
        derived = 'fail' if 'fail' in dimensions.values() else 'unresolved' if 'unresolved' in dimensions.values() else 'pass'
        if j['verdict'] != derived:
            raise ValueError('Overall verdict disagrees with dimension verdicts.')
    count = len(judgments)
    passed = sum(j['verdict'] == 'pass' for j in judgments.values())
    failed = sum(j['verdict'] == 'fail' for j in judgments.values())
    unresolved = count - passed - failed
    result = {'report': str(report_path), 'report_sha256': digest(report_path),
              'reviewer': annotation['reviewer'], 'review_method': annotation['review_method'],
              'cases': count, 'semantic_pass': passed, 'semantic_fail': failed,
              'semantic_unresolved': unresolved,
              'semantic_accuracy': passed / count if not unresolved and count else None,
              'factuality': {v: sum(j['dimensions']['factuality'] == v for j in judgments.values())
                             for v in ('pass', 'fail', 'unresolved', 'not_applicable')},
              'task_satisfaction': {v: sum(j['dimensions']['task_satisfaction'] == v for j in judgments.values())
                                    for v in ('pass', 'fail', 'unresolved', 'not_applicable')},
              'coverage': (passed + failed) / count if count else 0,
              'note': '独立于被测Qwen的依据核查；非外部盲评。semantic_accuracy为五维综合质量比例，事实性单独列出；任务未完成计失败，正确拒答可通过。',
              'judgments': annotation['judgments']}
    target = report_path.with_name(report_path.stem + '-reviewed.json')
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'judgments'}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', choices=['smoke', 'acceptance', 'dev', 'final'], default='dev')
    parser.add_argument('--backend', choices=['anyjev', 'rules'], default='anyjev')
    parser.add_argument('--label', default='run')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--release', action='store_true')
    parser.add_argument('--report')
    parser.add_argument('--annotations')
    args = parser.parse_args()
    annotate(args) if args.annotations else evaluate(args)


if __name__ == '__main__':
    main()
