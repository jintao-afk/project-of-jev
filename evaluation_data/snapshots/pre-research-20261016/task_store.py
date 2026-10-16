"""Local durable task checkpoints; immutable revisions and a verified latest pointer."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from workflow import scoped_path

MAX_RECORD_BYTES = 16 * 1024 * 1024
DELIVERY_METADATA_RESERVE = 8192
STEP_ID = re.compile(r's[1-6]')
SOURCE = re.compile(r'\$(input|s[1-6])')


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('任务编号无效。')
    return value


def _require(condition):
    if not condition:
        raise ValueError('任务不存在或记录损坏。')


def _validate_record(data, task_id, run_id):
    from core import validate_task
    _require(isinstance(data, dict) and set(data)=={'request', 'report', 'created_at'})
    request, report = data['request'], data['report']
    _require(isinstance(request, dict) and isinstance(report, dict))
    validate_task(request)
    _require(not any(str(key).startswith('_') for key in request))
    _require(isinstance(data['created_at'], str) and bool(data['created_at']))
    _require(identifier(report['task_id'])==task_id and identifier(report['run_id'])==run_id)
    _require(type(report['revision']) is int and 1 <= report['revision'] <= 4)
    _require(type(report['resumable']) is bool and type(report['execution_complete']) is bool)
    _require(type(report['task_complete']) is bool)
    _require(report['status'] in ('waiting_input', 'needs_review', 'completed', 'stopped'))
    _require(report['mode'] in ('agent', 'single', 'workflow') and report['mode']==request.get('mode', 'single'))
    _require(report['goal']==request['goal'])
    previous = report['previous_runs']
    _require(isinstance(previous, list) and len(previous)==report['revision']-1)
    _require(all(identifier(value)!=run_id for value in previous) and len(set(previous))==len(previous))
    _require((previous[0] if previous else run_id)==task_id)
    if report['mode']!='agent':
        _require(not report['resumable'])
        return
    plans, pending, outputs, bindings = (report[key] for key in ('plans', 'pending_subtasks', 'subtask_results', 'input_bindings'))
    _require(isinstance(plans, list) and len(plans)<=2 and isinstance(pending, list) and len(pending)<=6)
    _require(isinstance(outputs, dict) and len(outputs)<=6 and isinstance(bindings, dict) and len(bindings)<=6)
    _require(type(report['replans']) is int and 0 <= report['replans'] <= 1)
    allocated = {}
    for plan in plans:
        _require(isinstance(plan, dict) and isinstance(plan['steps'], list) and 1 <= len(plan['steps'])<=4)
        _require(type(plan['revision']) is int and plan['revision']==len({s.get('_plan') for s in allocated.values()})+1)
        for step in plan['steps']:
            _require(isinstance(step, dict) and set(step)=={'id', 'goal', 'input', 'parameters'})
            key, source, parameters = step['id'], step['input'], step['parameters']
            _require(isinstance(key, str) and STEP_ID.fullmatch(key) and key not in allocated)
            _require(isinstance(step['goal'], str) and 0<len(step['goal'].strip())<=500)
            _require(isinstance(source, str) and SOURCE.fullmatch(source))
            _require(source=='$input' or source[1:] in allocated)
            _require(isinstance(parameters, dict) and not set(parameters)-{'expression', 'query', 'top_k'})
            if 'top_k' in parameters:
                _require(type(parameters['top_k']) is int and 1<=parameters['top_k']<=8)
            for field in ('expression', 'query'):
                if field in parameters:
                    value = parameters[field]
                    _require(isinstance(value, str) and 0<len(value.strip())<=(200 if field=='expression' else 1000))
                    if value.startswith('$'):
                        reference = re.fullmatch(r'\$(input|s[1-6])(?:\.(value|characters|nonempty_lines|whitespace_words))?', value)
                        _require(reference and (reference[1]=='input' and not reference[2] or reference[1] in allocated))
            allocated[key] = {**step, '_plan': plan['revision']}
    _require(len(allocated)<=6)
    seen = set()
    for key, value in outputs.items():
        _require(key in allocated and isinstance(value, dict))
        _require(value['goal']==allocated[key]['goal'] and isinstance(value['service'], str))
        _require(isinstance(value['result'], dict) and isinstance(value['validation'], dict))
        provenance = value['input_provenance']
        _require(isinstance(provenance, dict) and isinstance(provenance['source'], str) and SOURCE.fullmatch(provenance['source']))
        _require(provenance['source']=='$input' or provenance['source'][1:] in seen)
        _require(isinstance(provenance['sha256'], str) and re.fullmatch(r'[a-f0-9]{64}', provenance['sha256']))
        identifier(provenance['run_id'])
        _require(type(provenance['retained_on_continue']) is bool)
        seen.add(key)
    pending_ids = set()
    for step in pending:
        _require(isinstance(step, dict) and isinstance(step.get('id'), str))
        key = step['id']
        _require(key in allocated and key not in outputs and key not in pending_ids)
        _require(step=={field: value for field, value in allocated[key].items() if field!='_plan'})
        pending_ids.add(key)
    for key, source in bindings.items():
        _require(key in allocated and isinstance(source, str) and SOURCE.fullmatch(source))
        _require(source=='$input' or source[1:] in outputs)
    _require(set(outputs)<=set(bindings))
    _require(not report['resumable'] or (report['revision']<4 and not report['execution_complete']
        and (pending or report['status']=='waiting_input')))


class TaskStore:
    def __init__(self, root):
        self.root = root.resolve()
        self.base = self.root/'workspace/tasks'
        if not self.base.resolve().is_relative_to(self.root):
            raise ValueError('任务目录超出项目范围。')

    def folder(self, task_id):
        return scoped_path(self.base, identifier(task_id))

    def load(self, task_id):
        folder = self.folder(task_id)
        try:
            with (folder/'latest.json').open('rb') as stream:
                pointer_raw = stream.read(32769)
            _require(len(pointer_raw)<=32768)
            pointer = json.loads(pointer_raw)
            _require(isinstance(pointer, dict) and isinstance(pointer.get('sha256'), str)
                and re.fullmatch(r'[a-f0-9]{64}', pointer['sha256']))
            path = scoped_path(folder, identifier(pointer['run_id'])+'.json')
            with path.open('rb') as stream:
                raw = stream.read(MAX_RECORD_BYTES+1)
            if len(raw)>MAX_RECORD_BYTES or hashlib.sha256(raw).hexdigest()!=pointer['sha256']:
                raise ValueError('任务记录已变化，拒绝继续执行。')
            data = json.loads(raw)
            _validate_record(data, task_id, pointer['run_id'])
            for field in ('task_id', 'revision', 'goal', 'status', 'resumable'):
                _require(type(pointer[field]) is type(data['report'][field]) and pointer[field]==data['report'][field])
            _require(pointer['created_at']==data['created_at'] and isinstance(pointer['updated_at'], str))
            return data
        except (OSError, KeyError, TypeError, ValueError, UnicodeError, RecursionError, AttributeError) as exc:
            raise ValueError('任务不存在或记录损坏。') from exc

    def ensure_record_size(self, request, report, created_at):
        """Check before creating deliverables, retaining 8 KiB for delivery metadata."""
        try:
            raw = json.dumps({'request': request, 'report': report, 'created_at': created_at},
                ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError('任务记录无法安全保存。') from exc
        if len(raw)+DELIVERY_METADATA_RESERVE>MAX_RECORD_BYTES:
            raise ValueError('任务记录超出16MiB本地保存上限（含8KiB交付元数据预留）。')
        try:
            _validate_record({'request': request, 'report': report, 'created_at': created_at},
                report['task_id'], report['run_id'])
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError('任务记录结构不合格，拒绝保存。') from exc
        return raw

    def save(self, request, report, created_at):
        raw = self.ensure_record_size(request, report, created_at)
        try:
            _validate_record({'request': request, 'report': report, 'created_at': created_at},
                report['task_id'], report['run_id'])
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError('任务记录结构不合格，拒绝保存。') from exc
        folder = self.folder(report['task_id'])
        folder.mkdir(parents=True, exist_ok=True)
        path = scoped_path(folder, identifier(report['run_id'])+'.json')
        with path.open('xb') as stream:
            stream.write(raw)
        pointer = {'run_id': report['run_id'], 'sha256': hashlib.sha256(raw).hexdigest(),
            'task_id': report['task_id'], 'revision': report['revision'], 'goal': request['goal'],
            'status': report['status'], 'created_at': created_at, 'updated_at': datetime.now(timezone.utc).isoformat(),
            'resumable': report.get('resumable', False)}
        temporary = folder/('latest.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(pointer, ensure_ascii=False, indent=2), 'utf-8')
        temporary.replace(folder/'latest.json')

    def list(self, limit=12):
        if not self.base.exists():
            return []
        paths = []
        for path in self.base.glob('*/latest.json'):
            try:
                paths.append((path.stat().st_mtime, path))
            except OSError:
                continue
        paths = [path for _, path in sorted(paths, key=lambda item:item[0], reverse=True)]
        items = []
        for path in paths[:min(limit, 20)]:
            try:
                task_id = identifier(path.parent.name)
                record = self.load(task_id)
                report = record['report']
                items.append({'task_id': task_id, 'run_id': report['run_id'], 'revision': report['revision'],
                    'goal': record['request']['goal'], 'status': report['status'],
                    'resumable': report.get('resumable', False), 'created_at': record['created_at']})
            except (ValueError, OSError):
                continue
        return items
