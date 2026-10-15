"""Versioned development/holdout comparisons; always preserve original outputs."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from evaluation_runner import ROOT, IMPLEMENTATION, digest, summarize
from core import Engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='evaluation_data/dev-v031.json')
    parser.add_argument('--profile', choices=['baseline-v030', 'contract', 'rules', 'no-stop-review', 'no-preservation'], default='contract')
    parser.add_argument('--freeze')
    args = parser.parse_args()
    path = ROOT / args.dataset
    dataset = json.loads(path.read_text('utf-8'))
    if dataset['split'].startswith('holdout'):
        if not args.freeze:
            raise ValueError('Holdout requires its versioned freeze manifest.')
        frozen = json.loads((ROOT / args.freeze).read_text('utf-8'))
        if args.profile not in frozen['profiles']:
            raise ValueError('This profile is not registered for the frozen holdout.')
        if frozen['dataset_sha256'] != digest(path):
            raise ValueError('Holdout hash mismatch.')
        for name, value in frozen['implementation_sha256'].items():
            if digest(ROOT / name) != value:
                raise ValueError('Frozen implementation differs: ' + name)
    engine = Engine()
    if args.profile == 'baseline-v030' and engine.config['version'] != '0.3.0':
        raise ValueError('The v0.3.0 baseline must run before implementation changes.')
    backend = 'rules' if args.profile == 'rules' else 'anyjev'
    if args.profile == 'no-stop-review':
        engine.config['stop_conflict_review_enabled'] = False
    if args.profile == 'no-preservation':
        engine.config['preservation_checks_enabled'] = False
    files = set(IMPLEMENTATION) | {'task_contract.py', 'run_iteration.py', 'app.py', 'ui.html', 'start.ps1', 'stop.ps1'}
    snapshot = {name: digest(ROOT / name) for name in sorted(files) if (ROOT / name).exists()}
    target = ROOT / 'logs/evaluations' / ('v031-' + args.profile + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
    rows = []
    def save():
        record = {'suite': dataset['split'], 'profile': args.profile, 'backend': backend,
                  'complete': len(rows) == len(dataset['cases']), 'created_at': datetime.now(timezone.utc).isoformat(),
                  'dataset_sha256': digest(path), 'implementation_sha256': snapshot,
                  'effective_config': engine.config, 'offline': engine.config['offline_mode'],
                  'model_identity': 'independent AnyJev + Qwen; not commercial Jev',
                  **summarize(rows), 'results': rows}
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2), 'utf-8')
        return record
    try:
        for case in dataset['cases']:
            report = engine.run({**case['request'], 'backend': backend, 'allow_remote': False, 'network_available': False})
            decisions = [e for e in report['events'] if e['event'] == 'decision']
            reviews = [e for e in report['events'] if e['event'] == 'route_review_finished']
            routes = [e for e in report['events'] if e['event'] == 'route_finalized']
            initial = decisions[0]['choice'] if decisions else None
            review = reviews[0]['choice'] if reviews else None
            action = report.get('action', 'stop')
            rows.append({**{k: case[k] for k in ('id', 'category', 'request', 'reference', 'basis', 'rubric', 'expected_routes')},
                         'case': case['id'], 'initial_choice': initial, 'initial_route_match': initial in case['expected_routes'],
                         'review_choice': review, 'review_route_match': review in case['expected_routes'] if review else None,
                         'controller_adjustments': [e for e in report['events'] if e['event'] == 'controller_override'],
                         'final_selection': routes[-1]['choice'] if routes else 'stop',
                         'executed_actions': [e['action'] for e in report['events'] if e['event'] == 'invocation_started'],
                         'route_match': action in case['expected_routes'], 'actual_route': action, 'report': report})
            save()
            print(f"{case['id']}: {initial} -> {review} -> {action} / {report['status']} / {report['total_ms']}ms", flush=True)
    finally:
        engine.close()
        record = save()
    print(json.dumps({k: v for k, v in record.items() if k not in ('results', 'implementation_sha256', 'effective_config')}, ensure_ascii=False), flush=True)
    print('Record: ' + str(target), flush=True)
    if record['remote_attempts']:
        raise RuntimeError('Offline violation.')


if __name__ == '__main__':
    main()
