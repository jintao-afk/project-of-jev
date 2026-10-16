"""Real local development trials, with one disclosed invocation fault; not a holdout."""
import hashlib
import json
from datetime import datetime
from core import Engine, ROOT


def main():
    implementation = {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in
        ('agent.py','research_control.py','task_store.py','local_models.py','verify_research.py')}
    engine = Engine(ROOT)
    if not engine.config['offline_mode']:
        raise RuntimeError('Offline mode required')
    records = []
    cases = [
        ('arithmetic', {'mode':'agent', 'goal':'1. 计算 (64-19)/5\n2. 计算 0.1+0.2', 'input':''}),
        ('rewrite', {'mode':'agent', 'goal':'1. 将原文改写成正式通知，不增加事实', 'input':'培训安排在周二，参加人数18人。地点待定，原因未提供。'}),
        ('summary', {'mode':'agent', 'goal':'1. 总结原文\n2. 统计上一步总结的字符数', 'input':'本轮检查共12项，完成9项。剩余3项尚未完成，原因未说明。'}),
        ('reference', {'mode':'agent', 'goal':'1. 根据本地资料回答：本项目决策模块与调用程序如何分工？', 'input':''}),
        ('injected_failure', {'mode':'agent', 'goal':'1. 将原文翻译成中文', 'input':'The inspection date has not been confirmed.'}),
    ]
    original = engine.invoke_local
    try:
        for name, task in cases:
            injected = []
            if name == 'injected_failure':
                def invoke(action, subtask, arguments, timeout):
                    if action == 'local_text' and not injected:
                        injected.append(True)
                        raise RuntimeError('DEVELOPMENT_FAULT_INJECTION: text worker unavailable')
                    return original(action, subtask, arguments, timeout)
                engine.invoke_local = invoke
            report = engine.run(task)
            records.append({'case':name, 'request':task, 'fault_injected':bool(injected), 'report':report})
            print(json.dumps({'case':name, 'status':report['status'], 'reason':report['reason'],
                'feedback':[e['choice'] for e in report['events'] if e['event']=='feedback_decision'],
                'calls':report['invocation_attempts'], 'replans':report['replans'],
                'run_id':report['run_id'], 'total_ms':report['total_ms']}, ensure_ascii=False), flush=True)
    finally:
        engine.close()
        path = ROOT/'logs'/('research-smoke-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
        path.write_text(json.dumps({'purpose':'development, not independent semantic evaluation',
            'implementation_sha256':implementation,
            'source_unchanged_during_run':all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==value for n,value in implementation.items()),
            'records':records}, ensure_ascii=False, indent=2), 'utf-8')
        print(str(path), flush=True)


if __name__ == '__main__':
    main()
