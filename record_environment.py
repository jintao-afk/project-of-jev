"""Read installed package metadata only; do not run model or implementation tests."""
import importlib.metadata as metadata
import json
import platform
from pathlib import Path

root = Path(__file__).resolve().parent
packages = {}
missing = []
for name in ['anyjev', 'numpy', 'torch', 'transformers', 'huggingface-hub']:
    try:
        packages[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        packages[name] = None
        missing.append(name)
(root / 'environment-lock.local.json').write_text(json.dumps({
    'python': platform.python_version(), 'system': platform.system(), 'packages': packages,
    'note': '仅记录安装版本；尚未验证 CUDA、模型推理或完整流程。'
}, ensure_ascii=False, indent=2), encoding='utf-8')
if missing:
    raise SystemExit('尚缺依赖：' + ', '.join(missing))
print('环境版本已记录；未运行模型验证。')
