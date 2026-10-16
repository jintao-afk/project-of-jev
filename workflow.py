"""Bounded offline dataset tasks: model selects actions; program owns execution."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import statistics
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path


class WorkflowError(ValueError):
    pass


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scoped_path(base, relative):
    if not isinstance(relative, str) or not relative or len(relative) > 240:
        raise WorkflowError('需要有效的工作区相对路径。')
    raw = Path(relative)
    if raw.is_absolute() or raw.drive or '..' in raw.parts or ':' in relative or '\x00' in relative:
        raise WorkflowError('只允许工作区内的相对路径，不能跨目录或访问磁盘绝对路径。')
    base = base.resolve()
    target = (base / raw).resolve()
    if not target.is_relative_to(base):
        raise WorkflowError('路径超出允许的工作区。')
    return target


def read_csv(path, value_column, status_column):
    if path.stat().st_size > 1_000_000:
        raise WorkflowError('单个CSV上限为1MB。')
    before = digest(path)
    with path.open('rb') as stream:
        raw = stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise WorkflowError('读取过程中CSV超出1MB限制。')
    text = raw.decode('utf-8-sig')
    rows = list(csv.reader(io.StringIO(text), strict=True))
    if not rows or not rows[0] or len(set(rows[0])) != len(rows[0]) or any(not h.strip() for h in rows[0]):
        raise WorkflowError('CSV缺少表头，或表头存在空字段/重复字段。')
    headers = rows[0]
    if len(headers) > 32 or len(rows) > 5001:
        raise WorkflowError('CSV上限为32列、5000行数据。')
    for name in (value_column, status_column):
        if name and name not in headers:
            raise WorkflowError('CSV缺少声明的字段：' + name)
    data = []
    for number, row in enumerate(rows[1:], 2):
        if not row:
            continue
        if len(row) != len(headers) or any(len(cell) > 2000 for cell in row):
            raise WorkflowError(f'CSV第{number}行的列数或字段长度不合格。')
        data.append({'source_row': number, 'cells': dict(zip(headers, row))})
    if digest(path) != before:
        raise WorkflowError('读取过程中源文件发生变化，请重新运行。')
    return {'name': path.name, 'sha256': before, 'headers': headers, 'rows': data}


def numeric_values(table, column):
    values, missing, invalid = [], [], []
    for row in table['rows']:
        raw = row['cells'][column].strip()
        if not raw:
            missing.append(row['source_row'])
            continue
        try:
            if len(raw) > 64:
                raise InvalidOperation
            value = Decimal(raw)
            if not value.is_finite() or value.copy_abs() > Decimal('1e12'):
                raise InvalidOperation
            values.append((row['source_row'], value))
        except InvalidOperation:
            invalid.append(row['source_row'])
    return values, missing, invalid


def decimal_text(value):
    with localcontext() as ctx:
        ctx.prec = 40
        return format(value.quantize(Decimal('0.000001')), 'f')


def markdown_text(value):
    text = str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_[\]{}()!|#])', r'\\\1', text).replace('\r', ' ').replace('\n', ' ')


def table_statistics(table, column, status_column):
    values, missing, invalid = numeric_values(table, column)
    numbers = [v for _, v in values]
    with localcontext() as ctx:
        ctx.prec = 40
        summary = {'rows': len(table['rows']), 'numeric_rows': len(numbers),
                   'missing_rows': missing, 'invalid_rows': invalid,
                   'minimum': decimal_text(min(numbers)) if numbers else None,
                   'maximum': decimal_text(max(numbers)) if numbers else None,
                   'mean': decimal_text(sum(numbers) / len(numbers)) if numbers else None,
                   'median': decimal_text(statistics.median(numbers)) if numbers else None,
                   'status_counts': dict(sorted(Counter(row['cells'][status_column] for row in table['rows']).items())) if status_column else {},
                   'numeric_scope': 'only finite numeric cells; missing/invalid cells separately disclosed',
                   'status_meaning': 'literal field counts, not semantic correctness or task success'}
    return summary


def threshold_check(table, column, threshold):
    values, missing, invalid = numeric_values(table, column)
    matches = [{'source_row': row, 'value': str(value)} for row, value in values if value > threshold]
    return {'operator': '>', 'threshold': str(threshold), 'count': len(matches),
            'matches': matches, 'missing_rows': missing, 'invalid_rows': invalid}


def validate_request(request):
    if not isinstance(request.get('goal'), str) or not request['goal'].strip() or len(request['goal']) > 2000:
        raise WorkflowError('请提供不超过2000字符的任务描述。')
    if request.get('backend', 'anyjev') not in ('anyjev', 'rules'):
        raise WorkflowError('文件任务只支持离线AnyJev或规则对照。')
    spec = request.get('workflow', {})
    if not isinstance(spec, dict) or set(spec) - {'input_dir', 'files', 'value_column', 'status_column', 'threshold', 'include_suggestions'}:
        raise WorkflowError('文件任务参数不合格或包含未知字段。')
    column = spec.get('value_column', 'total_ms')
    status = spec.get('status_column', 'status')
    if not isinstance(column, str) or not column.strip() or len(column) > 64 or not isinstance(status, str) or len(status) > 64:
        raise WorkflowError('需要有效的数值字段名；状态字段可以留空。')
    files = spec.get('files')
    if files is not None and (not isinstance(files, list) or not 1 <= len(files) <= 2 or any(not isinstance(f, str) or Path(f).name != f or not f.lower().endswith('.csv') or ':' in f or '/' in f or '\\' in f for f in files) or len(set(files)) != len(files)):
        raise WorkflowError('files只能是至多两个不同的CSV文件名。')
    suggestions = spec.get('include_suggestions', False)
    if type(suggestions) is not bool:
        raise WorkflowError('include_suggestions必须是布尔值。')
    threshold = spec.get('threshold')
    if threshold is not None:
        try:
            if type(threshold) not in (str, int, float) or len(str(threshold)) > 64:
                raise InvalidOperation
            threshold = Decimal(str(threshold))
            if not threshold.is_finite() or threshold.copy_abs() > Decimal('1e12'):
                raise InvalidOperation
        except InvalidOperation:
            raise WorkflowError('阈值必须是范围内的有限数值。') from None
    return {'input_dir': spec.get('input_dir', 'demo'), 'files': files, 'value_column': column,
            'status_column': status, 'threshold': str(threshold) if threshold is not None else None,
            'include_suggestions': suggestions}


class WorkflowRunner:
    def __init__(self, root, config, local, ready):
        self.root, self.config, self.local, self.ready = Path(root), config, local, ready

    def run(self, request):
        from core import available_ram_mb
        spec = validate_request(request)
        inbox = self.root / 'workspace/inbox'
        for folder in (inbox, self.root / 'workspace/runs'):
            if not folder.resolve().is_relative_to(self.root.resolve()):
                raise WorkflowError('工作区不能通过链接跳转到项目目录以外。')
        input_dir = scoped_path(inbox, spec['input_dir'])
        backend = request.get('backend', self.config['decision_backend'])
        run_id = uuid.uuid4().hex
        started = time.monotonic()
        created_at = datetime.now(timezone.utc).isoformat()
        deadline = started + min(300, self.config.get('max_seconds', 300))
        events, completed, failed, labels = [], set(), {}, {}
        inventory, tables, stats, thresholds, notes = [], {}, {}, {}, {}
        comparison = suggestions = artifact = verified = None
        reviews = repairs = 0
        outcome = {'status': 'stopped', 'task_complete': False, 'reason': '达到任务步骤上限。'}

        def log(event, **data):
            events.append({'event': event, 'elapsed_ms': round((time.monotonic()-started)*1000, 2), **data})

        def timeout():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('达到文件任务总时限。')
            return min(remaining, self.config['call_timeout_seconds'])

        def requirements():
            pending = []
            if 'inspect' not in completed:
                return ['检查输入目录']
            if not inventory:
                return ['需要1至2份CSV资料']
            for name in inventory:
                if name not in stats or stats[name]['numeric_rows'] == 0:
                    pending.append(name + '的有效数值统计')
                if spec['threshold'] is not None and name not in thresholds:
                    pending.append(name + '的阈值检查')
            if len(inventory) == 2 and comparison is None:
                pending.append('两份数据的统计对比')
            if spec['include_suggestions'] and suggestions is None:
                pending.append('模型待核查建议')
            return pending

        def report_data():
            return {'run_id': run_id, 'goal': request['goal'], 'contract': spec,
                    'created_at_utc': created_at, 'decision_backend': backend,
                    'model_identity': 'independent AnyJev + Qwen; not commercial Jev',
                    'source_files': {name: {'sha256': tables[name]['sha256'], 'rows': len(tables[name]['rows'])} for name in inventory},
                    'statistics': stats, 'threshold_checks': thresholds, 'comparison': comparison,
                    'notes': {name: {'sha256': item['sha256'], 'text': item['text']} for name, item in notes.items()},
                    'model_suggestions': suggestions, 'semantic_verified': False,
                    'scope': '结构化CSV分析条件；不自动验证自然语言额外要求或模型建议，不将状态计数视为答案正确率。'}

        def markdown(data):
            lines = ['# 本地数据分析报告', '', '任务：' + markdown_text(request['goal']), '',
                     '依据：声明字段与源文件；数值保留六位小数。状态计数不代表答案正确。', '']
            for name, summary in data['statistics'].items():
                lines += ['## ' + markdown_text(name), '', '源文件SHA256：`' + tables[name]['sha256'] + '`',
                          '数值字段：' + markdown_text(spec['value_column']), '', '| 指标 | 数值 |', '|---|---:|']
                for title, value in (('全部记录', summary['rows']), ('有效数值记录', summary['numeric_rows']),
                    ('缺失数值', len(summary['missing_rows'])), ('非法数值', len(summary['invalid_rows'])),
                    ('最小值', summary['minimum']), ('最大值', summary['maximum']), ('均值', summary['mean']), ('中位数', summary['median'])):
                    lines.append('| ' + title + ' | ' + str(value) + ' |')
                lines += ['', '缺失行：' + str(summary['missing_rows']), '非法值行：' + str(summary['invalid_rows']),
                          '', '### 状态字段原始计数', '', '| 状态 | 条数 |', '|---|---:|']
                for state, count in summary['status_counts'].items():
                    lines.append('| ' + markdown_text(state or '(空)') + ' | ' + str(count) + ' |')
                lines.append('')
            for title, key in (('阈值检查（严格大于）', 'threshold_checks'), ('数据对比（第二份减第一份）', 'comparison')):
                if data[key]:
                    encoded = json.dumps(data[key], ensure_ascii=False, indent=2).replace('<', '\\u003c').replace('>', '\\u003e')
                    lines += ['## ' + title, '', '```json', encoded, '```', '']
            if suggestions:
                lines += ['## 模型提出的待核查事项', '', '以下为未验证建议，不能当作已确认原因。', '',
                          *['- ' + markdown_text(check) for check in suggestions['checks']], '']
            lines += ['## 验收范围', '', data['scope'], '']
            return '\n'.join(lines)

        def write_report():
            folder = scoped_path(self.root / 'workspace/runs', run_id)
            folder.mkdir(parents=True, exist_ok=artifact is not None)
            data = report_data()
            for name, text in (('report.json', json.dumps(data, ensure_ascii=False, indent=2)), ('report.md', markdown(data))):
                target = folder / name
                # Only this run's registered artifacts may be replaced on bounded repair.
                if target.is_symlink() or target.resolve().parent != folder.resolve():
                    raise WorkflowError('成果路径不是本轮登记文件。')
                temporary = folder / (name + '.' + uuid.uuid4().hex + '.tmp')
                temporary.write_text(text, 'utf-8')
                temporary.replace(target)
            return {'directory': str(folder), 'run_id': run_id,
                    'json_sha256': digest(folder / 'report.json'), 'markdown_sha256': digest(folder / 'report.md'),
                    'files': [{'name': n, 'url': f'/v1/artifacts/{run_id}/{n}'} for n in ('report.md', 'report.json')]}

        def verify_report():
            folder = Path(artifact['directory'])
            for name in inventory:
                path = scoped_path(input_dir, name)
                if digest(path) != tables[name]['sha256']:
                    return {'passed': False, 'failure_type': 'source_changed', 'reason': '源文件在执行后发生变化：' + name}
                fresh = read_csv(path, spec['value_column'], spec['status_column'])
                if table_statistics(fresh, spec['value_column'], spec['status_column']) != stats[name]:
                    return {'passed': False, 'failure_type': 'statistics_mismatch', 'reason': '重新计算与统计记录不同。'}
            for name, note in notes.items():
                if digest(scoped_path(input_dir, name)) != note['sha256']:
                    return {'passed': False, 'failure_type': 'source_changed', 'reason': '参考文字在执行后发生变化。'}
            try:
                actual = json.loads((folder / 'report.json').read_text('utf-8'))
                correct = actual == report_data() and (folder / 'report.md').read_text('utf-8') == markdown(report_data())
            except (OSError, ValueError):
                correct = False
            return {'passed': correct, 'failure_type': None if correct else 'artifact_mismatch',
                    'reason': '源文件哈希、重算统计、完整JSON与Markdown内容核对' if correct else '成果文件缺失或内容不符。',
                    'scope': 'deterministic_dataset_contract', 'semantic_verified': False}

        log('run_started', backend=backend, mode='workflow', task=request, configuration=self.config,
            model_identity='independent AnyJev + Qwen; not commercial Jev', available_ram_mb=available_ram_mb())
        log('task_contract', contract={'operation': 'dataset_report', **spec},
            note='结构化任务声明和可执行依赖由程序约束，非模型自发任务分解。')
        try:
            if not input_dir.is_dir():
                raise WorkflowError('输入目录不存在，请将CSV放入workspace/inbox下的指定目录。')
            for step in range(1, min(24, self.config.get('workflow_max_steps', 16)) + 1):
                timeout()
                candidates = []
                def offer(key, description, location='local'):
                    if key not in completed and key not in failed:
                        labels[key] = description
                        candidates.append({'id': key, 'description': description, 'location': location})
                if 'inspect' not in completed:
                    offer('inspect', '检查已授权输入目录中的CSV和参考文字')
                elif artifact is not None:
                    if verified and verified['passed']:
                        offer('finish', '成果文件已通过声明的程序验收，交付并结束')
                    elif verified and verified['failure_type'] == 'artifact_mismatch' and repairs < 1:
                        offer('repair_report', '成果文件核对失败，按已核对数据重写一次')
                    elif verified is None:
                        offer('verify', '重新读取源文件及成果文件，检查统计和完整内容')
                else:
                    for index, name in enumerate(inventory):
                        if name not in tables:
                            offer(f'load_{index}', '读取CSV：' + name)
                        elif name not in stats:
                            offer(f'stats_{index}', '用程序计算统计并披露缺失和非法值：' + name)
                        elif stats[name]['numeric_rows'] and spec['threshold'] is not None and name not in thresholds:
                            offer(f'threshold_{index}', '用程序检查严格超过声明阈值的记录：' + name)
                    if inventory and len(stats) == len(inventory) and all(s['numeric_rows'] for s in stats.values()):
                        if len(inventory) == 2 and comparison is None:
                            offer('compare', '用程序对比两份数据的行数、均值及状态计数')
                        for name in sorted(p.name for p in input_dir.iterdir() if p.suffix.lower() in ('.txt', '.md') and p.is_file())[:2]:
                            if name not in notes:
                                offer('note_' + hashlib.sha256(name.encode()).hexdigest()[:8], '读取可选参考文字：' + name)
                        if spec['include_suggestions'] and suggestions is None:
                            offer('suggest', '用本地语言模型提出待核查问题，不宣称原因已确定')
                    if inventory and not requirements():
                        offer('write', '根据已完成的统计和要求生成JSON与Markdown报告')
                offer('stop', '停止并说明未完成条件；不伪造结果')
                if len(candidates) == 1 and candidates[0]['id'] == 'stop':
                    outcome['reason'] = '没有可继续执行的动作。' + ('；'.join(requirements()) or (verified or {}).get('reason', ''))
                    log('controller_stop', step=step, reason=outcome['reason'], failures=failed)
                    break
                log('candidates_filtered', step=step, available=[c['id'] for c in candidates],
                    excluded=failed.copy(), pending=requirements(),
                    actionable_count=sum(c['id'] != 'stop' for c in candidates))
                compact_stats = {name: {**{k: s[k] for k in ('rows', 'numeric_rows', 'minimum', 'maximum', 'mean', 'median')},
                    'missing_count': len(s['missing_rows']), 'invalid_count': len(s['invalid_rows']),
                    'status_counts_top10': dict(sorted(s['status_counts'].items(), key=lambda x: -x[1])[:10]),
                    'status_category_count': len(s['status_counts'])} for name, s in stats.items()}
                state = {'goal': request['goal'], 'contract': spec, 'completed': sorted(completed),
                         'pending': requirements(), 'statistics': compact_stats, 'verification': verified,
                         'previous_failures': failed, 'remaining_steps': self.config.get('workflow_max_steps', 16)-step+1}
                ids = [c['id'] for c in candidates]
                began = time.monotonic()
                if backend == 'rules':
                    # Declared fixed baseline: preserve enumeration order, skip optional notes.
                    chosen = next((c['id'] for c in candidates if not c['id'].startswith('note_') and c['id'] != 'stop'), 'stop')
                    decision = {'choice': chosen, 'probabilities': None, 'confidence': None, 'backend': 'rules'}
                else:
                    if not self.ready('decision'):
                        raise WorkflowError('本地决策模型文件不可用；不偷偷改用规则。')
                    ram = available_ram_mb()
                    if ram is not None and ram < 768:
                        raise WorkflowError('可用系统内存不足以尝试本地决策；不代表显存保证。')
                    log('decision_started', step=step, available_ram_mb=ram)
                    decision = self.local.request('decide_workflow', {'state': state, 'candidates': candidates}, timeout())
                    probabilities = decision.get('probabilities', {})
                    if set(probabilities) != set(ids) or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in probabilities.values()) or not math.isclose(sum(probabilities.values()), 1, abs_tol=.001):
                        raise WorkflowError('工作流决策概率或候选集合不合格。')
                    chosen = max(probabilities, key=probabilities.get)
                    decision['choice'] = chosen
                    decision['confidence'] = (max(probabilities.values())-1/len(ids))/(1-1/len(ids))
                log('decision', step=step, duration_ms=round((time.monotonic()-began)*1000, 2), **decision)
                initial = chosen
                reviewed_this_step = False
                if backend == 'anyjev' and chosen == 'stop' and reviews < 1:
                    reviews += 1
                    reviewed_this_step = True
                    log('route_review_started', step=step, reason='停止选择与仍有可执行步骤冲突；允许一次复核，不强制继续。')
                    try:
                        review = self.local.request('review_workflow', {'state': state, 'candidates': candidates}, timeout())
                        if review.get('choice') not in ids:
                            raise WorkflowError('复核返回了不可执行动作。')
                        chosen = review['choice']
                        log('route_review_finished', step=step, **review)
                    except Exception as exc:
                        log('route_review_failed', step=step, error=str(exc)[:300])
                log('route_finalized', step=step, initial_choice=initial, choice=chosen,
                    reviewed=reviewed_this_step, review_changed_choice=initial != chosen,
                    note='首次选择、复核和实际执行分别记录。')
                if chosen == 'stop':
                    outcome['reason'] = '决策模块选择停止；未完成：' + '；'.join(requirements() or ['成果写出、验证或交付'])
                    log('controller_stop', step=step, reason=outcome['reason'])
                    break
                began = time.monotonic()
                log('invocation_started', step=step, action=chosen, parameters={'binding': labels[chosen]})
                try:
                    delivery = None
                    if chosen == 'inspect':
                        entries = []
                        for item in input_dir.iterdir():
                            entries.append(item)
                            if len(entries) > 32:
                                raise WorkflowError('输入目录最多32个直接条目，请选择更小的资料目录。')
                        files = sorted(p.name for p in entries if p.is_file() and p.suffix.lower() == '.csv')
                        if spec['files'] is not None:
                            if any(name not in files for name in spec['files']):
                                raise WorkflowError('指定CSV不存在。')
                            files = spec['files']
                        if not 1 <= len(files) <= 2:
                            raise WorkflowError('请选择1至2份CSV；目录有更多文件时请通过files明确指定。')
                        for name in files:
                            scoped_path(input_dir, name)
                        inventory = files
                        result = {'files': inventory}
                    elif chosen.startswith(('load_', 'stats_', 'threshold_')):
                        index = int(chosen.rsplit('_', 1)[1]); name = inventory[index]
                        if chosen.startswith('load_'):
                            tables[name] = read_csv(scoped_path(input_dir, name), spec['value_column'], spec['status_column'])
                            result = {k: v for k, v in tables[name].items() if k != 'rows'}
                            result['row_count'] = len(tables[name]['rows'])
                        elif chosen.startswith('stats_'):
                            stats[name] = table_statistics(tables[name], spec['value_column'], spec['status_column'])
                            result = stats[name]
                            if not result['numeric_rows']:
                                raise WorkflowError('声明字段没有可统计的有效数值。')
                        else:
                            thresholds[name] = threshold_check(tables[name], spec['value_column'], Decimal(spec['threshold']))
                            result = thresholds[name]
                    elif chosen == 'compare':
                        first, second = inventory
                        with localcontext() as ctx:
                            ctx.prec = 40
                            first_values = [v for _, v in numeric_values(tables[first], spec['value_column'])[0]]
                            second_values = [v for _, v in numeric_values(tables[second], spec['value_column'])[0]]
                            mean_delta = decimal_text(sum(second_values)/len(second_values)-sum(first_values)/len(first_values))
                        comparison = {'first': first, 'second': second,
                                      'rows_delta': stats[second]['rows']-stats[first]['rows'],
                                      'mean_delta': mean_delta,
                                      'status_counts': {name: stats[name]['status_counts'] for name in inventory},
                                      'scope': '第二份减第一份的描述性差异；样本或负载可能不同，不证明因果、性能优势或答案质量。'}
                        result = comparison
                    elif chosen.startswith('note_'):
                        name = labels[chosen].split('：', 1)[1]
                        path = scoped_path(input_dir, name)
                        if path.stat().st_size > 16000:
                            raise WorkflowError('参考文字上限16KB。')
                        notes[name] = {'sha256': digest(path), 'text': path.read_text('utf-8-sig')}
                        result = notes[name]
                    elif chosen == 'suggest':
                        suggestions = self.local.request('workflow_suggest', {'statistics': stats,
                            'notes_as_untrusted_data': notes, 'goal': request['goal']}, timeout())
                        result = suggestions
                    elif chosen in ('write', 'repair_report'):
                        if chosen == 'repair_report':
                            repairs += 1
                        artifact = write_report(); verified = None
                        result = artifact
                    elif chosen == 'verify':
                        verified = verify_report()
                        result = verified
                    elif chosen == 'finish':
                        # Recheck at delivery, not merely when the verify action ran.
                        verified = verify_report()
                        if not verified['passed']:
                            raise WorkflowError('交付前复核失败：' + verified['reason'])
                        delivery = {'status': 'needs_review' if suggestions else 'completed',
                                   'task_complete': True, 'action': 'dataset_report',
                                   'completion_scope': 'deterministic_dataset_contract',
                                   'result': {'text': '已生成并核对数据分析报告。' + ('模型建议仍需人工核查。' if suggestions else ''),
                                              'artifacts': artifact['files'], 'statistics': stats,
                                              'comparison': comparison, 'threshold_checks': thresholds, 'semantic_verified': False},
                                   'validation': verified}
                        result = {'delivered': True, 'scope': 'deterministic_dataset_contract'}
                    else:
                        raise WorkflowError('未登记动作。')
                    timeout()
                    if chosen == 'finish':
                        receipt = {'run_id': run_id, 'completion_scope': 'deterministic_dataset_contract',
                                   'files': {'report.json': artifact['json_sha256'], 'report.md': artifact['markdown_sha256']}}
                        (Path(artifact['directory']) / 'delivery.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), 'utf-8')
                    log('invocation_finished', step=step, action=chosen, call_success=True, result=result,
                        duration_ms=round((time.monotonic()-began)*1000, 2))
                    completed.add(chosen)
                    if chosen == 'repair_report':
                        completed.discard('verify')
                    if chosen == 'finish':
                        outcome = delivery
                        break
                except Exception as exc:
                    failed[chosen] = str(exc)[:400]
                    log('invocation_failed', step=step, action=chosen, call_success=False,
                        error=str(exc)[:400], duration_ms=round((time.monotonic()-began)*1000, 2))
        except Exception as exc:
            outcome = {'status': 'stopped', 'task_complete': False, 'reason': str(exc)[:500]}
            log('run_interrupted', error=str(exc)[:500])
        report = {'run_id': run_id, 'mode': 'workflow', 'backend': backend, **outcome,
                  'task_contract': {'operation': 'dataset_report', **spec}, 'pending_requirements': requirements(),
                  'capability_labels': labels, 'events': events,
                  'invocation_attempts': sum(e['event']=='invocation_started' for e in events),
                  'successful_calls': sum(e['event']=='invocation_finished' for e in events),
                  'route_reviews': reviews, 'artifact_repairs': repairs, 'remote_attempts': 0,
                  'semantic_accuracy': None, 'threshold_calibrated': False,
                  'total_ms': round((time.monotonic()-started)*1000, 2)}
        folder = self.root / 'logs'; folder.mkdir(exist_ok=True)
        path = folder / (run_id + '.json')
        path.write_text(json.dumps({'created_at': datetime.now(timezone.utc).isoformat(), **report}, ensure_ascii=False, indent=2), 'utf-8')
        report['log_file'] = str(path)
        return report
