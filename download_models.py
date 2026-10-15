"""Download official snapshots into this project; record immutable revisions."""
import argparse
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ['HF_HOME'] = str(ROOT / '.cache' / 'huggingface')
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'


def modelscope_download(config):
    folder = ROOT / 'models'
    folder.mkdir(exist_ok=True)
    manifest_path = folder / 'model-lock.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    def write():
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    def digest(path):
        sha = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                sha.update(chunk)
        return sha.hexdigest()
    for role, repo in [('decision', config['decision_model']), ('retrieval', config['retrieval_model'])]:
        old = manifest.get(role, {})
        if old.get('source') == 'modelscope' and old.get('repo_id') == repo and old.get('files'):
            files = old['files']
        else:
            url = f'https://modelscope.cn/api/v1/models/{repo}/repo/files?Revision=master&Recursive=true'
            with urllib.request.urlopen(url, timeout=30) as response:
                metadata = json.load(response)
            if metadata.get('Code') != 200:
                raise RuntimeError('魔搭仓库元数据不可用：' + repo)
            files = []
            for item in metadata['Data']['Files']:
                name = item['Path']
                if item['Type'] == 'blob' and '/' not in name and (
                    name.endswith(('.json', '.txt', '.safetensors', '.model')) or name in ('README.md', 'LICENSE')):
                    files.append({'path': name, 'revision': item['Revision'],
                                  'sha256': item['Sha256'], 'size': item['Size']})
            if not any(f['path'].endswith('.safetensors') for f in files):
                raise RuntimeError('没有可用的 safetensors 权重，不自动下载执行其他格式。')
        manifest[role] = {'repo_id': repo, 'source': 'modelscope', 'status': 'downloading',
                          'downloaded_at': datetime.now(timezone.utc).isoformat(), 'files': files,
                          'version_policy': '每个文件固定 revision 与 SHA256；不是 Hugging Face commit'}
        write()
        target = folder / role
        target.mkdir(exist_ok=True)
        print(f'魔搭准备 {role}: {repo}；版本和校验值已记录', flush=True)
        for item in sorted(files, key=lambda f: f['size']):
            path = target / item['path']
            if path.exists() and path.stat().st_size == item['size'] and digest(path) == item['sha256']:
                print(item['path'] + ' 已准备，跳过', flush=True)
                continue
            partial = path.with_name(path.name + '.partial')
            query = urllib.parse.urlencode({'Revision': item['revision'], 'FilePath': item['path']})
            url = f'https://modelscope.cn/api/v1/models/{repo}/repo?{query}'
            for attempt in range(3):
                offset = partial.stat().st_size if partial.exists() else 0
                try:
                    request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
                    with urllib.request.urlopen(request, timeout=45) as response:
                        append = offset > 0 and response.status == 206
                        total = offset if append else 0
                        next_progress = total + 128 * 1024 * 1024
                        with partial.open('ab' if append else 'wb') as stream:
                            while chunk := response.read(1024 * 1024):
                                stream.write(chunk)
                                total += len(chunk)
                                if total >= next_progress:
                                    print(f"{item['path']} {total/2**20:.0f}/{item['size']/2**20:.0f} MB", flush=True)
                                    next_progress = total + 128 * 1024 * 1024
                    if partial.stat().st_size != item['size'] or digest(partial) != item['sha256']:
                        raise RuntimeError('模型文件大小或 SHA256 不匹配：' + item['path'])
                    partial.replace(path)
                    print(item['path'] + ' 文件完整性检查完成', flush=True)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(1)
            write()
        manifest[role]['status'] = 'downloaded'
        write()
        print(f'{role} 模型文件已准备；尚未进行推理验证。', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', choices=['huggingface', 'modelscope'], default='huggingface')
    args = parser.parse_args()
    config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    if args.source == 'modelscope':
        modelscope_download(config)
        return
    from huggingface_hub import HfApi, snapshot_download
    folder = ROOT / 'models'
    folder.mkdir(exist_ok=True)
    manifest_path = folder / 'model-lock.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    api = HfApi()
    for role, repo in [('decision', config['decision_model']), ('retrieval', config['retrieval_model'])]:
        old = manifest.get(role, {})
        revision = old.get('revision') if old.get('repo_id') == repo else None
        info = api.model_info(repo_id=repo, revision=revision)
        revision = info.sha
        files = [item.rfilename for item in info.siblings]
        weights = ['*.safetensors'] if any(f.endswith('.safetensors') and '/' not in f for f in files) else ['pytorch_model*.bin']
        manifest[role] = {'repo_id': repo, 'source': 'huggingface', 'revision': revision, 'status': 'downloading',
                          'downloaded_at': datetime.now(timezone.utc).isoformat()}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'准备 {role}: {repo} @ {revision}', flush=True)
        snapshot_download(repo_id=repo, revision=revision, local_dir=str(folder / role),
                          allow_patterns=weights + ['*.json', 'tokenizer*', 'vocab.txt', 'merges.txt', '*.model', 'README.md'],
                          ignore_patterns=['onnx/*', 'onnx/**', 'openvino/*', 'openvino/**'], max_workers=2)
        manifest[role]['status'] = 'downloaded'
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'{role} 模型文件已下载；尚未进行推理验证。', flush=True)


if __name__ == '__main__':
    main()
