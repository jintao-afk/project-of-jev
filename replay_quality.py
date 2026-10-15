"""Replay stored model drafts through a deterministic guard; not a new inference."""
import hashlib
import json
from answer_quality import guard_generation
from core import ROOT


if __name__ == '__main__':
    path = ROOT/'logs/evaluations/wording-probes-20261014-130206.json'
    original = json.loads(path.read_text('utf-8'))
    rows = []
    for row in original['results']:
        if row['id'] not in ('p05','p06'):
            continue
        actual = row['report']['result']
        checked = guard_generation({'text':actual['draft']}, row['request']['goal'],
                                   row['request']['input'], 'extraction')
        rows.append({'case':row['id'],'request':row['request'],
                     'stored_model_draft':actual['draft'], 'previous_quality':actual['quality'],
                     'new_guard_result':checked, 'passed_replay':not checked['quality']['issues']})
    target = ROOT/'logs/evaluations/email-guard-replay-v030.json'
    target.write_text(json.dumps({'mode':'deterministic_guard_replay_not_new_model_inference',
                                 'source_record_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                 'guard_sha256':hashlib.sha256((ROOT/'answer_quality.py').read_bytes()).hexdigest(),
                                 'results':rows},ensure_ascii=False,indent=2),'utf-8')
    print(target)
    print('replay passes:',sum(r['passed_replay'] for r in rows), '/', len(rows))
