"""Separate routing acceptance from declared output checks and semantic review."""
import argparse, json, os, time
from pathlib import Path
os.environ.update(PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_PROGRESS_BARS='1')
from core import Engine, ROOT

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite',choices=['smoke','acceptance'],default='acceptance')
    args=parser.parse_args()
    cases=json.loads((ROOT/'acceptance_cases.json').read_text('utf-8'))
    if args.suite=='smoke':cases=cases[:3]
    engine=Engine();rows=[]
    try:
        for case in cases:
            report=engine.run({**case['request'],'backend':'anyjev','allow_remote':False,'network_available':False})
            action=report.get('action','stop')
            raw_decisions=[e for e in report['events'] if e['event']=='decision']
            raw_choice=raw_decisions[-1]['choice'] if raw_decisions else None
            row={'case':case['id'],'expected_routes':case['expected_routes'],'actual_route':action,
                 'raw_model_choice':raw_choice,'raw_model_route_match':raw_choice in case['expected_routes'],
                 'route_match':action in case['expected_routes'],'semantic_review':'pending',
                 'review_guidance':case['review_guidance'],'report':report}
            rows.append(row)
            print(case['id']+': '+action+' / '+report['status'],flush=True)
    finally:engine.close()
    summary={'suite':args.suite,'model':engine.config['decision_model'],'offline':engine.config['offline_mode'],
             'cases':len(rows),'route_matches':sum(r['route_match'] for r in rows),
             'raw_model_route_matches':sum(r['raw_model_route_match'] for r in rows),
             'controller_adjustments':sum(e['event']=='controller_override' for r in rows for e in r['report']['events']),
             'declared_checks_passed':sum(r['report']['task_complete'] for r in rows),
             'remote_attempts':sum(r['report']['remote_attempts'] for r in rows),
             'semantic_accuracy':None,'note':'路由匹配和声明验收分开统计；语义正确性尚待人工标注。', 'results':rows}
    folder=ROOT/'logs/evaluations';folder.mkdir(exist_ok=True)
    target=folder/(args.suite+'-'+time.strftime('%Y%m%d-%H%M%S')+'.json')
    target.write_text(json.dumps(summary,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='results'},ensure_ascii=False),flush=True)
    print('Evaluation record: '+str(target),flush=True)
    if summary['remote_attempts']:raise RuntimeError('Offline evaluation issued remote requests.')
    if not any(r['report'].get('result', {}).get('model') == engine.config['decision_model']
               and r['report'].get('result', {}).get('text') for r in rows):
        raise RuntimeError('No text generation from the configured model was observed; inspect evaluation logs.')

if __name__=='__main__':main()
