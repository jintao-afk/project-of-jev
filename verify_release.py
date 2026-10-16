"""R1 functional acceptance with real offline inference, not an accuracy benchmark."""
import argparse
import csv
import hashlib
import json
import re
import shutil
import urllib.error
import urllib.request
from datetime import datetime, timezone
from fractions import Fraction

from core import ROOT

BASE = 'http://127.0.0.1:8765'


def http(path, body=None, host=None):
    headers = {'Content-Type': 'application/json; charset=utf-8'}
    if host:
        headers['Host'] = host
    request = urllib.request.Request(BASE+path, data=json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=310) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def get_json(path, body=None):
    status, raw = http(path, body)
    if status!=200:
        raise AssertionError(f'HTTP {status}: '+raw.decode('utf-8')[:400])
    return json.loads(raw)


def artifacts(report):
    downloaded = {}
    for item in report['artifacts']:
        assert re.fullmatch(r'/v1/artifacts/[a-f0-9]{32}/report\.(md|json)', item['url'])
        status, raw = http(item['url'])
        assert status==200
        downloaded[item['name']] = raw
    assert json.loads(downloaded['report.json'])==report
    return {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in downloaded.items()}


def local_references(folder, child):
    """Fraction reference computed independently of production Decimal code."""
    checks = {}
    for name in ('baseline.csv', 'current.csv'):
        with (folder/name).open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream))
        valid, missing, invalid = [], [], []
        for number, row in enumerate(rows, 2):
            if not row['latency_ms'].strip():
                missing.append(number)
                continue
            try:
                valid.append((number, Fraction(row['latency_ms'])))
            except (ValueError, ZeroDivisionError):
                invalid.append(number)
        actual = child['statistics'][name]
        threshold = child['threshold_checks'][name]
        checks[name] = (actual['rows']==len(rows) and actual['numeric_rows']==len(valid)
            and actual['missing_rows']==missing and actual['invalid_rows']==invalid
            and Fraction(actual['mean'])==sum(v for _, v in valid)/len(valid)
            and threshold['count']==sum(v>200 for _, v in valid)
            and [m['source_row'] for m in threshold['matches']]==[n for n, v in valid if v>200])
    checks['mean_delta'] = child['comparison']['mean_delta']=='30.000000'
    return checks


def health():
    status = get_json('/v1/status')
    assert status['version']=='0.6.0' and status['offline_mode']
    capabilities = get_json('/v1/capabilities')
    assert 'dataset_report' in capabilities['agent']['services']
    assert http('/')[0]==200
    return {'version': status['version'], 'offline': True, 'homepage_http': 200}


def run_case(name, task, check, records):
    report = get_json('/v1/run', task)
    checks = {'no_remote': report['remote_attempts']==0, **check(report)}
    download = artifacts(report)
    record = {'name': name, 'request': task, 'report': report, 'checks': checks, 'downloads': download}
    records.append(record)
    print(json.dumps({'case': name, 'status': report['status'], 'run_id': report['run_id'], 'checks': checks}, ensure_ascii=False), flush=True)
    assert all(checks.values()), name+' failed declared functional checks'
    return report


def prepare():
    health_info = health()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    fixture = ROOT/'workspace/inbox'/('r1-check-'+stamp)
    fixture.mkdir(parents=True, exist_ok=False)
    for name in ('baseline.csv', 'current.csv'):
        shutil.copyfile(ROOT/'examples/r1-demo'/name, fixture/name)
    records = []
    result = {'phase': 'prepare', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'purpose': 'functional development acceptance, no effectiveness comparison or independent accuracy claim',
        'semantic_accuracy': None, 'health': health_info, 'records': records}
    target = ROOT/'logs'/('r1-prepare-'+stamp+'.json')
    try:
        run_case('explicit-arithmetic', {'mode': 'agent', 'goal': '1. 计算 (31-7)/3\n2. 计算 (2.5+1.5)*4', 'input': ''},
            lambda r: {'executed': r['execution_complete'], 'values_8_16': [v['result'].get('value') for v in r['subtask_results'].values()]==[8,16]}, records)
        source = '巡检记录共有8项。2项缺少照片，尚未补齐。原因尚未确认。'
        summary = run_case('summary-to-count', {'mode': 'agent', 'goal': '1. 总结原文\n2. 统计上一步总结结果的字符数', 'input': source},
            lambda r: {'executed': r['execution_complete'],
                'summary_to_count': len(r['subtask_results'])==2 and r['subtask_results']['s2']['result'].get('characters')==len(r['subtask_results']['s1']['result'].get('text', '')),
                'source_quote_correspondence_only': bool(r['subtask_results'].get('s1', {}).get('result', {}).get('evidence')) and all(e['quote'] in source for e in r['subtask_results']['s1']['result']['evidence'])}, records)
        task = json.loads((ROOT/'examples/r1_dataset.json').read_text('utf-8'))
        task['dataset']['input_dir'] = fixture.name
        dataset = run_case('csv-to-summary-to-count', task,
            lambda r: {'executed': r['execution_complete'],
                'csv_registered_service': r['subtask_results'].get('s1', {}).get('service')=='dataset_report',
                'input_chain': r.get('input_bindings', {}).get('s2')=='$s1' and r.get('input_bindings', {}).get('s3')=='$s2',
                'count_actual_summary': len(r['subtask_results'])==3 and r['subtask_results']['s3']['result'].get('characters')==len(r['subtask_results']['s2']['result'].get('text', '')),
                **local_references(fixture, r['subtask_results']['s1']['result'])}, records)
        child = dataset['subtask_results']['s1']['result']
        child_files = {}
        for item in child['artifacts']:
            status, raw = http(item['url'])
            assert status==200
            child_files[item['name']] = hashlib.sha256(raw).hexdigest()
            if item['name']=='report.json':
                assert json.loads(raw)['statistics']==child['statistics']
        result['csv_download_hashes'] = child_files
        run_case('unsupported-device', {'mode': 'agent', 'goal': '连接我家的摄像头，查看此刻客厅是否有人，并关闭客厅灯。', 'input': ''},
            lambda r: {'stopped_without_actuation': r['status']=='stopped' and not r['subtask_results'] and r['invocation_attempts']==0}, records)
        run_case('legacy-single-calculation', {'goal': '计算 (23+17)/5', 'backend': 'anyjev', 'validation': {'expected_value': 8}},
            lambda r: {'declared_value': r.get('task_complete') and r.get('result', {}).get('value')==8}, records)
        pending = run_case('pause-for-material', json.loads((ROOT/'examples/r1_continue.json').read_text('utf-8')),
            lambda r: {'waiting': r['status']=='waiting_input' and r['resumable'],
                'first_result_preserved': r['subtask_results'].get('s1', {}).get('result', {}).get('value')==8,
                'pending_s2': [s['id'] for s in r['pending_subtasks']]==['s2']}, records)
        url = pending['artifacts'][0]['url']
        run_id = url.split('/')[3]
        assert re.fullmatch(r'[a-f0-9]{32}', run_id)
        path = ROOT/'workspace/runs'/run_id/'report.md'
        assert path.resolve().is_relative_to((ROOT/'workspace/runs').resolve())
        original = path.read_bytes()
        try:
            path.write_bytes(b'intentionally-changed-by-r1-test')
            result['changed_download_http'] = http(url)[0]
            assert result['changed_download_http']==409
        finally:
            path.write_bytes(original)
        result['path_escape_http'] = http('/v1/run', {'mode': 'agent', 'goal': '1. 分析CSV附件',
            'dataset': {'input_dir': '../outside', 'value_column': 'value', 'status_column': ''}})[0]
        result['private_state_injection_http'] = http('/v1/run', {'mode': 'agent', 'goal': 'test', '_resume': {}})[0]
        result['foreign_host_http'] = http('/v1/status', host='untrusted.invalid')[0]
        assert result['path_escape_http']==400 and result['private_state_injection_http']==400 and result['foreign_host_http']==403
        history = get_json('/v1/tasks')['tasks']
        assert pending['task_id'] in {t['task_id'] for t in history}
        result['pending_task_id'] = pending['task_id']
        result['pending_record_sha256'] = hashlib.sha256((ROOT/'workspace/tasks'/pending['task_id']/(pending['run_id']+'.json')).read_bytes()).hexdigest()
        result['prepared'] = True
    finally:
        with target.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    pointer = ROOT/'logs/r1-verification.local.json'
    pointer.write_text(json.dumps({'prepare_file': str(target.relative_to(ROOT))}), 'utf-8')
    print('PREPARED '+str(target), flush=True)


def continue_phase(previous_pid, current_pid):
    health_info = health()
    pointer = json.loads((ROOT/'logs/r1-verification.local.json').read_text('utf-8'))
    path = ROOT/pointer['prepare_file']
    assert path.resolve().is_relative_to((ROOT/'logs').resolve())
    prepared = json.loads(path.read_text('utf-8'))
    assert prepared['prepared']
    task_id = prepared['pending_task_id']
    old = get_json('/v1/tasks/'+task_id)
    assert old['status']=='waiting_input' and old['resumable']
    assert previous_pid and current_pid and previous_pid!=current_pid, 'Use verify_release.ps1 to verify a real registered service restart'
    supplement = {'input': 'The inspection is scheduled for Friday at 10:00. The room has not been decided.'}
    final = get_json('/v1/tasks/'+task_id+'/continue', supplement)
    calls = [e['action'] for e in final['events'] if e['event']=='invocation_started']
    checks = {'same_task_new_revision': final['task_id']==task_id and final['revision']==2,
        'execution_complete': final['execution_complete'], 'no_calculator_replay': calls==['local_text'],
        'old_value_unchanged': final['subtask_results']['s1']['result']==old['subtask_results']['s1']['result'],
        'old_provenance_preserved': final['subtask_results']['s1']['input_provenance']['run_id']==old['run_id'],
        'no_remote': final['remote_attempts']==0, 'unverified_semantics': final['task_complete'] is False}
    assert all(checks.values()), checks
    assert hashlib.sha256((ROOT/'workspace/tasks'/task_id/(old['run_id']+'.json')).read_bytes()).hexdigest()==prepared['pending_record_sha256']
    downloads = artifacts(final)
    assert http('/v1/tasks/'+task_id+'/continue', supplement)[0]==400
    prepared.update(phase='complete', completed_at_utc=datetime.now(timezone.utc).isoformat(),
        continuation={'request': supplement, 'report': final, 'checks': checks, 'downloads': downloads,
            'previous_server_pid': previous_pid, 'current_server_pid': current_pid}, final_health=health_info,
        browser_visual_verification='not_performed')
    target = ROOT/'logs'/('r1-acceptance-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.json')
    with target.open('x', encoding='utf-8') as stream:
        json.dump(prepared, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'continuation_checks': checks, 'translated_result': final['subtask_results']['s2']['result']['text'], 'record': str(target)}, ensure_ascii=False), flush=True)
    (ROOT/'logs/r1-verification.local.json').write_text(json.dumps({'prepare_file': str(path.relative_to(ROOT)), 'complete_file': str(target.relative_to(ROOT))}), 'utf-8')


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('prepare', 'continue'), required=True)
    parser.add_argument('--previous-server-pid', type=int)
    parser.add_argument('--current-server-pid', type=int)
    args = parser.parse_args()
    if args.phase=='prepare':
        prepare()
    else:
        continue_phase(args.previous_server_pid, args.current_server_pid)
