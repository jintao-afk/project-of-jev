"""Hash-verified local deliverables; artifact integrity is separate from answer quality."""
import json
import uuid

from workflow import digest, markdown_text, scoped_path


def deliver(root, report, request):
    if not (root/'workspace/runs').resolve().is_relative_to(root.resolve()):
        raise ValueError('成果目录不能通过链接跳转到项目以外。')
    run_id = report['run_id']
    folder = scoped_path(root/'workspace/runs', run_id)
    artifact_id = uuid.uuid4().hex if folder.exists() and not (report.get('mode')=='workflow' and report.get('task_complete')) else run_id
    folder = scoped_path(root/'workspace/runs', artifact_id)
    files = [{'name': name, 'url': f'/v1/artifacts/{artifact_id}/{name}'} for name in ('report.md', 'report.json')]
    report['artifacts'] = files
    report['delivery'] = {'integrity_verified': True,
        'scope': 'artifact_bytes_and_record_only; answer quality remains separately declared',
        'partial': not (report.get('execution_complete') or report.get('task_complete'))}
    # Keep the original CSV contract artifacts and receipt unchanged.
    if report.get('mode')=='workflow' and report.get('task_complete'):
        report['artifacts'] = report['result']['artifacts']
        return report
    folder.mkdir(parents=True, exist_ok=False)
    lines = ['# Jev 离线任务交付记录', '', '任务：'+markdown_text(request['goal']), '',
        '状态：'+markdown_text(report['status']),
        '说明：'+markdown_text(report.get('reason', '结果按以下范围交付。')), '',
        '当前决策实现：独立 AnyJev + Qwen，不是商用 Jev 权重。', '',
        '## 交付与质量范围', '',
        '文件完整性核对表示内容与本轮保存记录一致。它不证明需求覆盖、资料充分或自然语言结论正确。',
        '任务语义完成：'+str(report.get('task_complete', False))+'；独立语义准确率：未标注。', '']
    outputs = report.get('subtask_results', {})
    if outputs:
        from agent import result_text
        for key, value in outputs.items():
            lines += ['## '+key+' '+markdown_text(value['goal']), '',
                '实际服务：'+markdown_text(value['service']), '', markdown_text(result_text(value['result'])), '']
            for child in value['result'].get('artifacts', []):
                lines += ['子任务成果：'+markdown_text(child['name'])+'（下载路径见结构化记录）', '']
    elif report.get('result'):
        from agent import result_text
        lines += ['## 返回结果', '', markdown_text(result_text(report['result'])), '']
    pending = report.get('pending_subtasks', [])
    if pending:
        lines += ['## 尚未完成', '', *['- '+s['id']+' '+markdown_text(s['goal']) for s in pending], '']
    if report.get('resumable'):
        lines += ['## 补充资料后继续', '',
            '可在工作台补充资料后继续。新资料仅用于未完成步骤，已完成成果按原输入保留。修改前置事实请新建任务。', '']
    lines += ['## 复核事项', '', *['- '+markdown_text(s) for s in report.get('review_items', [
        '检查返回内容是否完整回应用户要求。', '核对自然语言事实、未知状态及资料是否充分。'])], '']
    data = {'report.md': '\n'.join(lines), 'report.json': json.dumps(report, ensure_ascii=False, indent=2)}
    for name, value in data.items():
        temporary = folder/(name+'.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(value, 'utf-8')
        temporary.replace(folder/name)
    if json.loads((folder/'report.json').read_text('utf-8'))!=report or (folder/'report.md').read_text('utf-8')!=data['report.md']:
        raise ValueError('交付文件重读核对失败。')
    (folder/'delivery.json').write_text(json.dumps({'run_id': artifact_id,
        'files': {name: digest(folder/name) for name in data}, 'scope': 'artifact_integrity_not_semantic_correctness'}, ensure_ascii=False), 'utf-8')
    return report
