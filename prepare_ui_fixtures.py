"""Preserve compact real-response fixtures so UI replay needs no ignored logs."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if __name__ == '__main__':
    development = json.loads((ROOT / 'logs/evaluations/dev-anyjev-frozen-dev-20261014-130616-954080.json').read_text('utf-8'))
    iteration = json.loads((ROOT / 'logs/evaluations/v031-contract-20261015-121428-916789.json').read_text('utf-8'))
    workflow = json.loads((ROOT / 'logs/evaluations/workflow-development-anyjev-20261015-135328-216393.json').read_text('utf-8'))
    fixture = {'method': 'Exact saved real responses; not new inference or independent quality judgments',
               'calc': json.loads((ROOT / 'reports/ui-run-v030.json').read_text('utf-8')),
               'cases': {r['case']: r['report'] for r in development['results'] if r['case'] in {'d03','d24','d11','d15','d17'}},
               'iteration': {r['case']: r['report'] for r in iteration['results'] if r['case'] in {'c01','c11'}},
               'workflow': workflow['report']}
    target = ROOT / 'tests/fixtures/ui-responses.json'
    with target.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(fixture, ensure_ascii=False, indent=2))
    print(target)
