"""Real offline workflow runner, with original requests and complete traces."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from core import Engine, ROOT


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', default='examples/workflow_demo.json')
    parser.add_argument('--backend', choices=['anyjev', 'rules'], default='anyjev')
    parser.add_argument('--label', default='dev')
    args = parser.parse_args()
    request = json.loads((ROOT / args.task).read_text('utf-8'))
    request.update(backend=args.backend, allow_remote=False, network_available=False)
    engine = Engine()
    try:
        report = engine.run(request)
    finally:
        engine.close()
    target = ROOT / 'logs/evaluations' / ('workflow-' + args.label + '-' + args.backend + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
    target.write_text(json.dumps({'request': request, 'report': report, 'semantic_accuracy': None}, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({k: report[k] for k in ('run_id', 'status', 'task_complete', 'total_ms', 'route_reviews', 'invocation_attempts', 'remote_attempts')}, ensure_ascii=False))
    for event in report['events']:
        if event['event'] == 'decision':
            print('decision:', event['step'], event['choice'])
        if event['event'] in ('invocation_failed', 'controller_stop', 'run_interrupted'):
            print(event['event'], event.get('error', event.get('reason')))
    print('Record:', target)
    if report.get('result', {}).get('artifacts'):
        print('Artifacts:', ROOT / 'workspace/runs' / report['run_id'])
