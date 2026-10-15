"""Development-only paired wording probes; results may not count as final holdout."""
import json
import hashlib
from datetime import datetime, timezone
from core import Engine, ROOT


def main():
    path = ROOT/'evaluation_data/probes.json'
    cases = json.loads(path.read_text('utf-8'))
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    target = ROOT/'logs/evaluations'/('wording-probes-' + stamp + '.json')
    engine, rows = Engine(), []
    try:
        for case in cases:
            report = engine.run({**case['request'], 'backend': 'anyjev', 'allow_remote': False, 'network_available': False})
            rows.append({**case, 'report': report})
            target.write_text(json.dumps({'created_at': datetime.now(timezone.utc).isoformat(),
                                         'dataset_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                         'split': 'development_wording_probes', 'results': rows}, ensure_ascii=False, indent=2), 'utf-8')
            print(case['id'], report.get('action', 'stop'), report.get('result', {}).get('text', report.get('reason')), flush=True)
    finally:
        engine.close()
    print(target)


if __name__ == '__main__':
    main()
