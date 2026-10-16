"""Real offline development smoke checks, not a benchmark or semantic evaluator."""
import argparse
import hashlib
import json
import urllib.request
from datetime import datetime, timezone

from core import ROOT


def http(path, task=None):
    body = json.dumps(task, ensure_ascii=False).encode('utf-8') if task is not None else None
    req = urllib.request.Request('http://127.0.0.1:8765'+path, data=body,
        headers={'Content-Type': 'application/json; charset=utf-8'})
    with urllib.request.urlopen(req, timeout=310) as response:
        return json.loads(response.read())


CASES = {
    'arithmetic': json.loads((ROOT/'examples/agent_calculation.json').read_text('utf-8')),
    'summary-chain': json.loads((ROOT/'examples/agent_summary.json').read_text('utf-8')),
    'retrieval-chain': {'mode': 'agent', 'goal': '1. 检索本地资料中关于决策模块分工的原文\n2. 总结上一步检索结果', 'input': ''},
    'unsupported': {'mode': 'agent', 'goal': '连接我家的摄像头，查看此刻客厅是否有人，并关闭客厅灯。', 'input': ''},
    'missing-source': {'mode': 'agent', 'goal': '把我提供的英文原文翻译成中文，然后统计翻译结果的字符数。', 'input': ''},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', nargs='+', choices=CASES, default=list(CASES))
    args = parser.parse_args()
    status = http('/v1/status')
    if status['version'] != '0.5.0' or not status['offline_mode']:
        raise SystemExit('Expected offline v0.5.0 running service')
    records = []
    for name in args.cases:
        task = CASES[name]
        report = http('/v1/run', task)
        tools = [e['action'] for e in report['events'] if e['event'] == 'invocation_started']
        checks = {'remote_calls_zero': report['remote_attempts'] == 0,
                  'no_semantic_completion_claim': report['task_complete'] is False and report['semantic_accuracy'] is None}
        if name == 'arithmetic':
            values = [v['result'].get('value') for v in report['subtask_results'].values() if v['service'] == 'calculator']
            checks['two_explicit_results_7_and_48'] = values == [7, 48]
        if name == 'summary-chain':
            summaries = [v['result'] for v in report['subtask_results'].values() if v['service'] == 'local_text']
            counts = [v['result'] for v in report['subtask_results'].values() if v['service'] == 'text_stats']
            checks['summary_to_counter_dependency'] = bool(summaries and counts and counts[-1]['characters'] == len(summaries[0]['text']))
            checks['source_quote_correspondence_only'] = bool(summaries and summaries[0].get('evidence') and all(e['quote'] in task['input'] for e in summaries[0]['evidence']))
        if name == 'retrieval-chain':
            checks['local_reference_service_invoked'] = bool(set(tools) & {'retrieve', 'knowledge_qa'})
            results = report['subtask_results']
            checks['retrieval_output_bound_to_summary'] = bool(len(results)==2 and report.get('input_bindings', {}).get('s2')=='$s1' and results['s2']['service']=='local_text')
        if name in ('unsupported', 'missing-source'):
            checks['stopped_without_substitute_answer'] = report['status'] == 'stopped' and not report['subtask_results']
        rawpath = ROOT/'logs'/f"{report['run_id']}.json"
        record = {'case': name, 'request': task, 'status': report['status'],
            'execution_complete': report['execution_complete'], 'checks': checks,
            'services': tools, 'initial_choices': [e['choice'] for e in report['events'] if e['event']=='decision'],
            'route_reviews': report['route_reviews'], 'replans': report['replans'], 'total_ms': report['total_ms'],
            'input_bindings': report.get('input_bindings'),
            'program_adjustments': [e for e in report['events'] if e['event']=='controller_override'],
            'input_source_choices': [e for e in report['events'] if e['event']=='input_source_decision'],
            'resource_peaks': [e['resources'] for e in report['events'] if 'resources' in e][-1:],
            'result': report['result'], 'reason': report['reason'],
            'log_file': str(rawpath.relative_to(ROOT)), 'log_sha256': hashlib.sha256(rawpath.read_bytes()).hexdigest(),
            'semantic_accuracy': None}
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'version': '0.5.0',
        'purpose': 'development integration smoke, no rules comparison; cases may be used to repair this version',
        'quality_scope': 'specific arithmetic, dependency and limitation checks only, not complete semantic accuracy',
        'implementation_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
            'agent.py', 'core.py', 'local_models.py', 'app.py', 'ui.html', 'config.json', 'verify_agent.py')},
        'browser_visual_verification': 'not_performed', 'records': records}
    target = ROOT/'reports'/f'agent-smoke-v050-{stamp}.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), 'utf-8')
    print('SAVED '+str(target), flush=True)


if __name__ == '__main__':
    main()
