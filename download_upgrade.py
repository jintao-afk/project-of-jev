"""Resume a pinned ModelScope download into D, without changing the active model lock."""
import argparse, hashlib, json, re, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(4*1024*1024), b''):digest.update(part)
    return digest.hexdigest()

def download(root):
    root=root.resolve()
    if str(root).lower()!=r'd:\1 jev\jev-edge-prototype'.lower():raise ValueError('Unexpected project location.')
    folder=root/'models/qwen3-1.7b'
    if not (root/'models').resolve().is_relative_to(root):raise ValueError('Unsafe model parent folder.')
    folder.mkdir(exist_ok=True)
    if not folder.resolve().is_relative_to(root):raise ValueError('Model folder is outside project.')
    manifest_path=folder/'download-lock.json'
    repo='Qwen/Qwen3-1.7B'
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text('utf-8'))
        if manifest['repo_id']!=repo:raise ValueError('Unexpected model identity.')
    else:
        metadata=json.loads((Path(__file__).parent/'model_metadata.json').read_text('utf-8'))
        if metadata['repo_id']!=repo:raise ValueError('Model metadata identity mismatch.')
        files=metadata['files']
        manifest={'repo_id':repo,'source':'modelscope','relative_dir':'models/qwen3-1.7b',
                  'status':'downloading','files':files,'downloaded_at':datetime.now(timezone.utc).isoformat(),
                  'version_policy':'每个文件固定 revision 与 SHA256'}
    files=manifest['files']
    if not any(f['path'].endswith('.safetensors') for f in files):raise ValueError('Missing safetensors.')
    for item in files:
        if not re.fullmatch(r'[\w.\-]+',item['path']) or item['path'] in ('.','..') or not re.fullmatch(r'[a-fA-F0-9]{64}',item['sha256']):raise ValueError('Unsafe download metadata.')
    def save():
        temp=manifest_path.with_suffix('.tmp')
        temp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8');temp.replace(manifest_path)
    save()
    print('Preparing Qwen3-1.7B in D; old model is preserved.',flush=True)
    for item in sorted(files,key=lambda f:f['size']):
        target=folder/item['path']
        if target.exists() and target.stat().st_size==item['size'] and sha256(target).lower()==item['sha256'].lower():continue
        partial=target.with_name(target.name+'.partial')
        query=urllib.parse.urlencode({'Revision':item['revision'],'FilePath':item['path']})
        for attempt in range(3):
            try:
                offset=partial.stat().st_size if partial.exists() else 0
                request=urllib.request.Request(f'https://modelscope.cn/api/v1/models/{repo}/repo?{query}',headers={'Range':f'bytes={offset}-'} if offset else {})
                with urllib.request.urlopen(request,timeout=60) as response:
                    append=offset>0 and response.status==206
                    if append and not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise RuntimeError('Invalid resumed range.')
                    total=offset if append else 0
                    next_progress=total+128*1024*1024
                    with partial.open('ab' if append else 'wb') as stream:
                        while part:=response.read(1024*1024):
                            total+=len(part)
                            if total>item['size']:raise RuntimeError('Response exceeds expected size.')
                            stream.write(part)
                            if total>=next_progress:
                                print(f"{item['path']}: {total/2**20:.0f}/{item['size']/2**20:.0f} MB",flush=True)
                                next_progress=total+128*1024*1024
                if partial.stat().st_size!=item['size'] or sha256(partial).lower()!=item['sha256'].lower():
                    partial.unlink(missing_ok=True)
                    raise RuntimeError('File checksum mismatch; discarded the invalid partial file.')
                partial.replace(target)
                print(item['path']+' verified.',flush=True)
                break
            except Exception:
                if attempt==2:raise
                time.sleep(1)
    manifest['status']='downloaded';save()
    print('Model download verified. Runtime inference is checked separately.',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    download(parser.parse_args().project)
