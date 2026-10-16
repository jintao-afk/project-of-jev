"""Freeze a new workflow version without modifying older evaluation releases."""
import json
from datetime import datetime, timezone
from evaluate_workflow import ROOT, IMPLEMENTATION, digest

if __name__ == '__main__':
    target = ROOT / 'evaluation_data/release-v040.json'
    data = {'version': '0.4.0', 'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
            'holdout_sha256': digest(ROOT / 'evaluation_data/workflow-final.json'),
            'implementation_sha256': {name: digest(ROOT / name) for name in IMPLEMENTATION},
            'fixture_sha256': {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted((ROOT / 'tests/fixtures/workflow-final').glob('*'))},
            'policy': 'Small developer-authored holdout; do not tune this frozen version on results; semantic accuracy remains separate.'}
    with target.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2))
    print(target)
