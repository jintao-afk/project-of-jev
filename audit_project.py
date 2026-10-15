"""Verify recorded model hashes and paths without loading or downloading weights."""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from offline_environment import configure
ROOT = Path(__file__).resolve().parent
configure(ROOT)
from model_paths import model_dir, model_ready


def main():
    config = json.loads((ROOT/'config.json').read_text('utf-8'))
    lock = json.loads((ROOT/'models/model-lock.json').read_text('utf-8'))
    models = {}
    for role in ('decision', 'retrieval'):
        folder = model_dir(ROOT, config, role)
        files = []
        for entry in lock[role]['files']:
            path = folder / entry['path']
            hashed = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest() if path.exists() else None
            files.append({'path': str(path), 'bytes': path.stat().st_size if path.exists() else None,
                          'sha256': hashed, 'hash_matches': hashed == entry['sha256'],
                          'size_matches': path.exists() and path.stat().st_size == entry['size']})
        models[role] = {'ready': model_ready(ROOT, config, lock, role), 'files': files}
    import torch
    import importlib.metadata as metadata
    import os
    try:
        gpu = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.used', '--format=csv,noheader,nounits'],
                             capture_output=True, text=True, timeout=10)
        gpu_info = gpu.stdout.strip() if gpu.returncode == 0 else gpu.stderr.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        gpu_info = None
    legacy = ROOT/'logs/evaluations/acceptance-20261014-120550.json'
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'root': str(ROOT),
              'python_executable': sys.executable, 'python_base_prefix': sys.base_prefix,
              'config': config, 'models': models,
              'old_weights_preserved': (ROOT/'models/decision/config.json').exists(),
              'legacy_evaluation_sha256': hashlib.sha256(legacy.read_bytes()).hexdigest(),
              'legacy_evaluation_summary': {k: v for k, v in json.loads(legacy.read_text('utf-8')).items() if k != 'results'},
              'cache_environment': {k: os.environ[k] for k in ('HF_HOME','XDG_CACHE_HOME','TORCH_HOME','PIP_CACHE_DIR','TEMP','TMP')},
              'packages': {name: metadata.version(name) for name in ('anyjev','torch','transformers','numpy','huggingface-hub')},
              'cuda_available': torch.cuda.is_available(), 'gpu_snapshot': gpu_info,
              'identity': 'Independent AnyJev + Qwen, not commercial Jev',
              'all_model_hashes_match': all(f['hash_matches'] and f['size_matches'] for m in models.values() for f in m['files'])}
    target = ROOT / 'logs' / ('project-audit-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(str(target))
    print(json.dumps({k: report[k] for k in ('all_model_hashes_match','old_weights_preserved','cuda_available','gpu_snapshot')}, ensure_ascii=False))
    if not report['all_model_hashes_match']:
        raise RuntimeError('Recorded model hash mismatch; do not redownload automatically.')


if __name__ == '__main__':
    main()
