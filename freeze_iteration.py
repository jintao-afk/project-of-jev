"""Create a separate v0.3.1 holdout freeze; never replace historical releases."""
import json
from datetime import datetime, timezone
from evaluation_runner import ROOT, IMPLEMENTATION, digest


if __name__ == '__main__':
    target = ROOT / 'evaluation_data/release-v031.json'
    if target.exists():
        raise SystemExit('The v0.3.1 release already exists; never overwrite it.')
    files = set(IMPLEMENTATION) | {'app.py', 'ui.html', 'start.ps1', 'stop.ps1', 'open.ps1',
                                  '打开工作台.cmd', 'run_iteration.py', 'freeze_iteration.py',
                                  'environment-lock.local.json', 'tests/test_contract.py', 'tests/test_quality.py'}
    result = {'version': json.loads((ROOT / 'config.json').read_text('utf-8'))['version'],
              'frozen_at': datetime.now(timezone.utc).isoformat(),
              'dataset': 'evaluation_data/holdout-v031.json',
              'dataset_sha256': digest(ROOT / 'evaluation_data/holdout-v031.json'),
              'development_sha256': digest(ROOT / 'evaluation_data/dev-v031.json'),
              'implementation_sha256': {name: digest(ROOT / name) for name in sorted(files)},
              'profiles': ['contract', 'rules'],
              'policy': 'No tuning after holdout. Future development using failures requires a new holdout/version.',
              'identity': 'independent AnyJev + Qwen; not commercial Jev',
              'limits': 'Small developer-authored holdout, not external blinded or human double-labeled evaluation.'}
    with target.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2))
    print(target)
