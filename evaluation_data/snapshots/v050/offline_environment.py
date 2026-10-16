"""All runtime writable caches and temporary files stay inside the D-drive project."""
import os
from pathlib import Path


def configure(root: Path):
    paths = {'HF_HOME': '.cache/huggingface', 'XDG_CACHE_HOME': '.cache',
             'TORCH_HOME': '.cache/torch', 'PIP_CACHE_DIR': '.cache/pip',
             'TEMP': '.cache/tmp', 'TMP': '.cache/tmp'}
    for key, relative in paths.items():
        target = root / relative
        target.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(target)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      HF_HUB_DISABLE_PROGRESS_BARS='1', PYTHONDONTWRITEBYTECODE='1')
