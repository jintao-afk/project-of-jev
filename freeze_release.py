"""Freeze implementation and final data once; never regenerate from final results."""
import json
from datetime import datetime, timezone
from evaluation_runner import ROOT, IMPLEMENTATION, digest


if __name__ == '__main__':
    target = ROOT / 'evaluation_data/release.json'
    if target.exists():
        raise SystemExit('A release already exists; do not overwrite the holdout freeze.')
    files = (*IMPLEMENTATION, 'app.py', 'ui.html', 'start.ps1', 'stop.ps1', 'evaluate.py')
    release = {'version': json.loads((ROOT/'config.json').read_text('utf-8'))['version'],
               'frozen_at': datetime.now(timezone.utc).isoformat(),
               'holdout_sha256': digest(ROOT/'evaluation_data/final.json'),
               'development_sha256': digest(ROOT/'evaluation_data/dev.json'),
               'implementation_sha256': {name: digest(ROOT/name) for name in files},
               'policy': 'Final results must not tune this version; downgrade to regression before using them for next-version development.',
               'identity': 'Independent AnyJev + Qwen, not commercial Jev',
               'blinding_limit': 'Developer-authored holdout, not external blinded evaluation.'}
    target.write_text(json.dumps(release, ensure_ascii=False, indent=2), 'utf-8')
    print(target)
