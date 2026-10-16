"""Resolve configured model locations inside the project."""
from pathlib import Path

def model_dir(root: Path, config: dict, role: str) -> Path:
    value = config.get(role + '_model_dir', 'models/' + role)
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError('模型目录必须是项目内的相对路径。')
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('模型路径超出项目目录。')
    return target

def model_ready(root: Path, config: dict, manifest: dict, role: str) -> bool:
    record = manifest.get(role, {})
    folder = model_dir(root, config, role)
    return (record.get('status') == 'downloaded'
            and record.get('repo_id') == config[role + '_model']
            and (folder / 'config.json').exists()
            and any(folder.glob('*.safetensors')))
