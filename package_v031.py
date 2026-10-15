"""Create a D-drive incremental delivery package, without models or environments."""
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from evaluation_runner import ROOT, digest


if __name__ == '__main__':
    summary = json.loads((ROOT / 'reports/progress-20261015-v031.json').read_text('utf-8'))
    frozen = json.loads((ROOT / 'evaluation_data/release-v031.json').read_text('utf-8'))
    if any(digest(ROOT / name) != sha for name, sha in frozen['implementation_sha256'].items()):
        raise RuntimeError('Frozen source was changed.')
    files = set(frozen['implementation_sha256']) | {
        'README.md', 'README_OFFLINE.md', '推进记录.md', 'tests/ui_replay.cjs',
        'tests/verify_service_v031.ps1', 'package_v031.py', 'write_progress_v031.py',
        'review_iteration.py', 'review_holdout_v031.py',
        'reports/progress-20261015-v031.md', 'reports/progress-20261015-v031.json',
        'reports/service-check-v031-20261015-122357.json',
        'reports/ui-run-v030.json',
        'logs/evaluations/dev-anyjev-frozen-dev-20261014-130616-954080.json',
        'logs/evaluations/v031-contract-20261015-121428-916789.json',
        'logs/validation-v031-20261015.log',
        'logs/ui-validation-2026-10-15T04-19-08-703Z.json',
        'evaluation_data/dev-v031.json', 'evaluation_data/holdout-v031.json',
        'evaluation_data/release-v031.json', 'evaluation_data/PROTOCOL.md',
        'evaluation_data/PROTOCOL-v031.md',
    }
    for group in ('development', 'holdout'):
        for item in summary[group].values():
            path = ROOT / item['record']
            files.update((item['record'], str(path.with_name(path.stem + '-reviewed.json').relative_to(ROOT)).replace('\\', '/'),
                          'evaluation_data/annotations/' + path.stem + '.json'))
    files = {name.replace('\\', '/') for name in files}
    missing = [name for name in files if not (ROOT / name).is_file()]
    if missing:
        raise FileNotFoundError(str(missing))
    target = ROOT / 'reports/jev-v0.3.1-update-20261015.zip'
    hashes = {name: digest(ROOT / name) for name in sorted(files)}
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('DELIVERY.md', '# Jev offline v0.3.1 update\n\n'
                         '这是原D盘项目的代码与评价更新包，不是含权重的独立安装包。\n'
                         '当前项目已更新并运行，无需再次解压安装。已有模型、.venv、缓存均不重复打包。\n'
                         '在原项目中使用start.ps1或打开工作台.cmd，保持离线。\n'
                         '报告：reports/progress-20261015-v031.md。\n'
                         '旧版基线与全部新评价原始记录、依据标注分别保留。\n'
                         '实现身份：independent AnyJev + Qwen，不是商用Jev权重。\n')
        archive.writestr('FILE_HASHES.json', json.dumps(hashes, ensure_ascii=False, indent=2))
        for name in sorted(files):
            archive.write(ROOT / name, name)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('ZIP CRC verification failed.')
        for name, sha in hashes.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != sha:
                raise RuntimeError('Packaged bytes differ: ' + name)
    manifest = {'version': '0.3.1', 'created_at': datetime.now(timezone.utc).isoformat(),
                'package': str(target), 'bytes': target.stat().st_size, 'sha256': digest(target),
                'files': len(hashes), 'verified_frozen_source': True, 'verified_zip_bytes': True,
                'includes_models_or_environment': False}
    (ROOT / 'reports/delivery-manifest-v031.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(manifest, ensure_ascii=False))
