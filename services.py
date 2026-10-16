"""One local invocation adapter shared by single tasks and the general controller."""

import hashlib
import json
from pathlib import Path

DETAIL_ITEMS = 50
STATUS_ITEMS = 20
STATUS_BYTES = 4000
TRACE_ITEMS = 200


def _status_preview(counts):
    if len(counts) <= STATUS_ITEMS and len(json.dumps(counts, ensure_ascii=False).encode('utf-8')) <= STATUS_BYTES:
        return dict(counts), 0
    preview = {}
    for key, value in counts.items():
        candidate = {**preview, key: value}
        if len(candidate) > STATUS_ITEMS or len(json.dumps(candidate, ensure_ascii=False).encode('utf-8')) > STATUS_BYTES:
            break
        preview = candidate
    return preview, len(counts)-len(preview)


def _row_preview(data, fields):
    result = dict(data)
    for field in fields:
        values = data.get(field, [])
        if len(values) > DETAIL_ITEMS:
            result[field] = values[:DETAIL_ITEMS]
            result[field+'_total'] = len(values)
            result[field+'_omitted'] = len(values)-DETAIL_ITEMS
    return result


def _dataset_details(result):
    """Bound the controller view; original verified artifacts retain every item."""
    statistics = {}
    for name, data in result['statistics'].items():
        preview = _row_preview(data, ('missing_rows', 'invalid_rows'))
        preview['status_counts'], omitted = _status_preview(data['status_counts'])
        if omitted:
            preview['status_counts_total'] = len(data['status_counts'])
            preview['status_counts_omitted'] = omitted
        statistics[name] = preview
    comparison = result.get('comparison')
    if comparison:
        comparison = dict(comparison)
        counts, omitted_counts = {}, {}
        for name, values in comparison.get('status_counts', {}).items():
            counts[name], omitted = _status_preview(values)
            if omitted:
                omitted_counts[name] = omitted
        comparison['status_counts'] = counts
        if omitted_counts:
            comparison['status_counts_omitted'] = omitted_counts
    thresholds = {name: _row_preview(data, ('matches', 'missing_rows', 'invalid_rows'))
        for name, data in (result.get('threshold_checks') or {}).items()}
    return statistics, comparison, thresholds


def _workflow_summary(root, child):
    log_path = Path(child['log_file']).resolve()
    if not log_path.is_relative_to((root/'logs').resolve()):
        raise ValueError('子流程日志超出项目日志目录。')
    log_reference = {'path': str(log_path), 'sha256': hashlib.sha256(log_path.read_bytes()).hexdigest()}
    trace = []
    fields = ('event', 'step', 'elapsed_ms', 'choice', 'initial_choice', 'reviewed', 'review_changed_choice',
        'action', 'call_success', 'duration_ms', 'error', 'reason', 'backend')
    kinds = {'decision', 'route_review_started', 'route_review_finished', 'route_review_failed',
        'route_finalized', 'invocation_started', 'invocation_finished', 'invocation_failed', 'controller_stop', 'run_interrupted'}
    for event in child.get('events', []):
        if event.get('event') in kinds:
            trace.append({key: value[:500] if isinstance(value, str) else value
                for key, value in event.items() if key in fields})
    summary = {key: child[key] for key in ('run_id', 'mode', 'backend', 'status', 'task_complete',
        'completion_scope', 'invocation_attempts', 'successful_calls', 'route_reviews', 'artifact_repairs',
        'remote_attempts', 'total_ms', 'semantic_accuracy') if key in child}
    summary.update(record_scope='summary_only; full decisions, failures and numerical details remain in original log/artifacts',
        log_file=str(log_path), log_reference=log_reference,
        decision_calls=sum(e.get('event')=='decision' for e in child.get('events', [])),
        trace=trace[:TRACE_ITEMS], trace_total=len(trace), trace_omitted=max(0, len(trace)-TRACE_ITEMS),
        artifacts=child.get('result', {}).get('artifacts', []))
    if child.get('reason'):
        summary['reason'] = child['reason'][:500]
    return summary


class InputRequired(ValueError):
    def __init__(self, message, kind='text'):
        super().__init__(message)
        self.kind = kind


def invoke(engine, action, task, parameters, timeout):
    from core import safe_calculate
    if action=='calculator':
        return {'value': safe_calculate(parameters['expression']), 'expression': parameters['expression']}
    if action=='text_stats':
        source = parameters['text']
        return {'characters': len(source), 'nonempty_lines': sum(bool(s.strip()) for s in source.splitlines()),
            'whitespace_words': len(source.split())}
    if action=='dataset_report':
        from workflow import WorkflowRunner, scoped_path
        if not scoped_path(engine.root/'workspace/inbox', parameters['dataset']['input_dir']).is_dir():
            raise InputRequired('CSV资料目录不存在，请在workspace/inbox放入资料，或补充正确的附件目录与字段。', 'dataset')
        config = {**engine.config, 'max_seconds': min(timeout, engine.config['max_seconds'])}
        child = WorkflowRunner(engine.root, config, engine.local, engine.model_ready).run({
            'mode': 'workflow', 'backend': 'anyjev', 'goal': task['goal'], 'workflow': parameters['dataset']})
        summary = _workflow_summary(engine.root, child)
        if not child.get('task_complete'):
            return {'text': child.get('reason', '文件分析未完成。'), 'workflow_run': summary,
                'quality': {'status': 'rejected_draft', 'semantic_verified': False}}
        result = child['result']
        statistics, comparison, thresholds = _dataset_details(result)
        sentences = ['以下数值来自本次文件分析；状态计数不是答案正确率。']
        for name, data in result['statistics'].items():
            sentences.append(f"文件{name}共有{data['rows']}条记录，其中有效数值{data['numeric_rows']}条，缺失{len(data['missing_rows'])}条，非法值{len(data['invalid_rows'])}条，均值{data['mean']}，中位数{data['median']}。")
        if result.get('comparison'):
            delta = result['comparison']
            sentences.append(f"第二份减第一份：记录数差{delta['rows_delta']}，均值差{delta['mean_delta']}。")
        sentences.append('控制器仅保留有上限的明细预览；省略数量明确标注，全部状态和行明细以已核验CSV成果为准。')
        return {'text': '\n'.join(sentences), 'statistics': statistics,
            'comparison': comparison, 'threshold_checks': thresholds,
            'detail_scope': {'kind': 'bounded_controller_preview', 'list_limit': DETAIL_ITEMS,
                'status_entry_limit': STATUS_ITEMS, 'status_utf8_bytes_limit': STATUS_BYTES,
                'full_details': result['artifacts'], 'omissions': 'Fields ending _omitted explicitly count omitted entries; original verified artifacts are complete.'},
            'artifacts': result['artifacts'], 'workflow_run': summary,
            'quality': {'status': 'deterministic_dataset_contract', 'semantic_verified': False}}
    operations = {'local_text': 'generate', 'retrieve': 'retrieve', 'knowledge_qa': 'knowledge_answer'}
    if action not in operations:
        raise ValueError('服务未登记到本地执行适配器。')
    payload = dict(parameters)
    if action!='retrieve':
        from task_contract import build_contract
        payload.update(goal=task['goal'], task_contract=build_contract(task))
    return engine.local.request(operations[action], payload, timeout)
