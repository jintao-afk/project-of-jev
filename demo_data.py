"""Seed bundled synthetic demo inputs only into a new, non-existing directory."""
import shutil
from workflow import scoped_path


def seed(root):
    source = root/'examples/r1-demo'
    target = scoped_path(root/'workspace/inbox', 'r1-demo')
    if not source.is_dir() or target.exists():
        return
    target.mkdir(parents=True, exist_ok=False)
    for name in ('baseline.csv', 'current.csv'):
        shutil.copyfile(source/name, target/name)
