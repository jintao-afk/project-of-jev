"""Fresh development smoke using actual offline AnyJev + Qwen; no holdout scoring."""
import hashlib
import json
import argparse
from datetime import datetime
from core import Engine, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fault-only', action='store_true', help='Inject one tool failure; keep actual model decisions')
    args = parser.parse_args()
    engine = Engine(ROOT)
    if not engine.config['offline_mode']:
        raise RuntimeError('Offline mode required')
    records = []
    cases = [
        {'mode': 'agent', 'goal': '1. 计算 (35+13)/6\n2. 计算 17*3-4', 'input': ''},
        {'mode': 'agent', 'goal': '1. 翻译原文\n2. 统计上一步翻译结果的字符数', 'input': 'The meeting is on Friday. The room is not yet confirmed.'},
        {'mode': 'agent', 'goal': '1. 翻译原文', 'input': ''},
        {'mode': 'agent', 'goal': '1. 计算 1/0', 'input': ''},
    ]
    if args.fault_only:
        cases = [{'mode': 'agent', 'goal': '1. 翻译原文', 'input': 'Please confirm the appointment time.'}]
        original = engine.invoke_local
        injected = []
        def failing_once(action, task, parameters, timeout):
            if action == 'local_text' and not injected:
                injected.append(True)
                raise RuntimeError('DEVELOPMENT_FAULT_INJECTION: text worker unavailable')
            return original(action, task, parameters, timeout)
        engine.invoke_local = failing_once
    try:
        for task in cases:
            report = engine.run(task)
            records.append({'request': task, 'report': report, 'fault_injection': args.fault_only})
            print(json.dumps({'goal': task['goal'], 'status': report['status'], 'reason': report['reason'],
                'feedback': [e['choice'] for e in report['events'] if e['event']=='feedback_decision'],
                'run_id': report['run_id'], 'total_ms': report['total_ms']}, ensure_ascii=False), flush=True)
    finally:
        engine.close()
        path = ROOT/'logs'/('feedback-smoke-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json')
        path.write_text(json.dumps({'purpose': 'development smoke; not independent test or semantic score',
            'implementation_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                for name in ('agent.py', 'local_models.py', 'verify_feedback.py')}, 'records': records}, ensure_ascii=False, indent=2), 'utf-8')
        print(str(path), flush=True)


if __name__ == '__main__':
    main()
