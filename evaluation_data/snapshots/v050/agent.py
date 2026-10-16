"""Bounded general task orchestration; Qwen proposes, AnyJev selects, code executes."""
from __future__ import annotations

import json
from copy import deepcopy
import re
import time
import uuid
from datetime import datetime, timezone

from answer_quality import task_kind
from task_contract import build_contract

REF = re.compile(r'^\$(input|s[1-6])(?:\.(value|characters|nonempty_lines|whitespace_words))?$')


def parse_plan(raw, completed):
    raw = raw.strip()
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {'steps'} or not isinstance(data['steps'], list) or not 1 <= len(data['steps']) <= 4:
        raise ValueError('计划须为包含1至4个steps的JSON对象。')
    seen, steps = set(completed), []
    for item in data['steps']:
        if not isinstance(item, dict) or set(item) != {'id', 'goal', 'input', 'parameters'}:
            raise ValueError('每步仅允许id、goal、input、parameters。')
        key, goal, source, params = (item[k] for k in ('id', 'goal', 'input', 'parameters'))
        if not isinstance(key, str) or not re.fullmatch(r's[1-6]', key) or key in seen:
            raise ValueError('步骤ID须为不重复的s1至s6，不能覆盖已执行结果。')
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 500:
            raise ValueError('子任务要求须为1至500字符。')
        # Material is bound to the user's exact input or a previous result, never
        # to a model-invented literal paragraph in the plan.
        if not isinstance(source, str) or not REF.fullmatch(source) or '.' in source:
            raise ValueError('input仅允许$input或先前步骤引用，例如$s1。')
        if not isinstance(params, dict) or set(params) - {'expression', 'query', 'top_k'}:
            raise ValueError('计划参数仅允许expression、query、top_k。')
        if 'top_k' in params and (type(params['top_k']) is not int or not 1 <= params['top_k'] <= 8):
            raise ValueError('top_k须为1至8的整数。')
        for name in ('expression', 'query'):
            if name in params and (not isinstance(params[name], str) or not params[name].strip() or len(params[name]) > (200 if name == 'expression' else 1000)):
                raise ValueError('计划参数类型或长度不合格。')
        for value in [source, *[v for v in params.values() if isinstance(v, str) and v.startswith('$')]]:
            match = REF.fullmatch(value)
            if not match or (match[1] != 'input' and match[1] not in seen) or (match[1] == 'input' and match[2]):
                raise ValueError('引用不存在、向前引用或引用字段不受支持。')
        seen.add(key)
        steps.append(item)
    return steps


def result_text(result):
    if isinstance(result.get('text'), str):
        return result['text']
    if 'value' in result:
        return str(result['value'])
    if 'matches' in result:
        return '\n'.join('[' + str(m.get('id', '?')) + '] ' + m['text'] for m in result['matches'])
    return json.dumps(result, ensure_ascii=False)


def bind(value, original, outputs):
    if not isinstance(value, str) or not value.startswith('$'):
        return value
    match = REF.fullmatch(value)
    if not match:
        raise ValueError('不支持的结果引用。')
    if match[1] == 'input':
        return original
    result = outputs[match[1]]['result']
    if match[2]:
        number = result.get(match[2])
        if type(number) not in (float, int):
            raise ValueError('引用的结果不是可用数值。')
        return str(number)
    return result_text(result)


def usable(result):
    if result.get('truncated'):
        return False, '输出截断，不能作为完整子任务结果。'
    if result.get('quality', {}).get('status') in ('rejected_draft', 'abstained'):
        return False, '质量保护拒交或资料缺少直接依据。'
    if result.get('answer_mode') in ('missing_material', 'insufficient_evidence', 'evidence_selection_rejected'):
        return False, '缺少原文或可靠资料，不能据此继续生成结论。'
    if 'matches' in result and not result['matches']:
        return False, '检索未返回资料。'
    if not result or not result_text(result).strip():
        return False, '未返回可用输出。'
    return True, '调用返回且未触发有限保护；子任务是否满足语义要求仍待核查。'


class AgentRunner:
    def __init__(self, engine):
        self.engine = engine
        self.root, self.config, self.local = engine.root, engine.config, engine.local

    def run(self, request):
        from core import REGISTRY, validate_task, normalize_probabilities, available_ram_mb, safe_calculate, requires_reference, supplied_text_transformation
        task = validate_task(request)
        if task.get('backend', 'anyjev') != 'anyjev':
            raise ValueError('通用任务当前仅使用本地AnyJev决策；旧模式仍可使用原有后端。')
        if task.get('parameters') or task.get('validation'):
            raise ValueError('通用任务由模型准备受限参数；请将要求写入goal、原文放入input，高级JSON留空。')
        started, run_id = time.monotonic(), uuid.uuid4().hex
        deadline = started + min(300, self.config['max_seconds'])
        events, outputs, plans, labels = [], {}, [], {'replan': '根据反馈重新规划', 'finish': '整理并返回成果', 'stop': '说明限制并停止'}
        queue, failed = [], set()
        bindings, allocated = {}, set()
        replans = reviews = decisions = 0
        outcome = {'status': 'stopped', 'reason': '达到通用任务步骤上限。', 'execution_complete': False}

        def log(event, **data):
            events.append({'event': event, 'elapsed_ms': round((time.monotonic()-started)*1000, 2), **data})

        def timeout():
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('通用任务达到总时限。')
            return min(remaining, self.config['call_timeout_seconds'])

        def generate_plan(feedback=None):
            # Numbered requirements are the user's explicit task decomposition,
            # never credited to the model. This is the stable first-version path.
            numbered = re.findall(r'^\s*\d+[.、)）]\s*(\S.*)\s*$', task['goal'], re.M)
            if numbered and not plans:
                if len(numbered) > 4 or any(len(s)>500 for s in numbered):
                    raise ValueError('初版一次最多4项编号任务，每项不超过500字符。')
                if len(numbered) != len([line for line in task['goal'].splitlines() if line.strip()]):
                    raise ValueError('请让所有任务要求逐项编号，不能混入未编号的要求。')
                from request_normalization import normalize_request
                proposed = []
                for i, objective in enumerate(numbered, 1):
                    normalized, derived = normalize_request({'goal': objective, 'input': '', 'parameters': {}})
                    proposed.append({'id': f's{i}', 'goal': objective, 'input': '$input', 'parameters': normalized['parameters']})
                    if derived:
                        log('parameters_derived', subtask_id=f's{i}', parameters=derived,
                            note='程序仅提取用户明确写出的受限算式，服务仍由AnyJev选择。')
                allocated.update(s['id'] for s in proposed)
                plans.append({'revision': 1, 'source': 'user_numbered_requirements', 'objectives': numbered, 'steps': deepcopy(proposed)})
                log('plan_accepted', revision=1, plan=deepcopy(proposed), source='user_numbered_requirements',
                    note='编号子任务由用户明确给出；程序解析编号，AnyJev决定输入来源与实际调用。不是模型自动拆解。')
                return proposed
            outline = self.local.request('outline_agent', {
                'goal': task['goal'], 'input_present': bool(task.get('input', '').strip()),
                'completed': {k: v['goal'] for k, v in outputs.items()}, 'feedback': feedback}, timeout())
            log('requirements_generated', **outline)
            requirements = json.loads(outline['text'])
            if outline.get('truncated') or not isinstance(requirements, dict) or set(requirements) != {'objectives'}:
                raise ValueError('需求拆分格式不合格。')
            objectives = requirements['objectives']
            if not isinstance(objectives, list) or not 1 <= len(objectives) <= 4 or any(not isinstance(s, str) or not s.strip() or len(s) > 500 for s in objectives):
                raise ValueError('需求拆分须包含1至4项具体要求。')
            if len(set(objectives)) != len(objectives):
                raise ValueError('模型重复了相同子任务，未交付；请使用编号任务清单明确每项要求。')
            if len(allocated)+len(objectives) > 6:
                raise ValueError('整轮任务最多6个子任务。')
            proposed = []
            free_ids = [f's{i}' for i in range(1, 7) if f's{i}' not in allocated]
            for objective, key in zip(objectives, free_ids):
                parameter_feedback = feedback
                for attempt in range(2):
                    log('plan_started', subtask_id=key, attempt=attempt+1, replan=bool(plans))
                    t = time.monotonic()
                    generated = self.local.request('plan_agent', {
                        'overall_goal': task['goal'], 'objective': objective,
                        'input_as_data': task.get('input', ''),
                        'previous_steps': {**{k: v['goal'] for k, v in outputs.items()}, **{s['id']: s['goal'] for s in proposed}},
                        'allowed_inputs': ['$input', *['$'+k for k in outputs], *['$'+s['id'] for s in proposed]],
                        'feedback': parameter_feedback}, timeout())
                    log('plan_generated', subtask_id=key, duration_ms=round((time.monotonic()-t)*1000, 2), **generated)
                    try:
                        raw = generated['text'].strip()
                        if raw.startswith('```'):
                            raw = raw.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
                        parameters = json.loads(raw)
                        if generated.get('truncated') or not isinstance(parameters, dict) or set(parameters) != {'input', 'parameters'}:
                            raise ValueError('参数计划须包含input和parameters，不能修改子任务目标。')
                        item = {'id': key, 'goal': objective, **parameters}
                        parse_plan(json.dumps({'steps': [item]}), {**outputs, **{s['id']: s for s in proposed}})
                        proposed.append(item)
                        break
                    except (ValueError, TypeError, KeyError) as exc:
                        parameter_feedback = {'plan_error': str(exc), 'previous_parameters_as_data': generated.get('text', '')[:1500]}
                        log('plan_rejected', subtask_id=key, error=str(exc), attempt=attempt+1)
                else:
                    raise ValueError('两次参数计划均不符合执行约束，已停止。')
            plans.append({'revision': len(plans)+1, 'objectives': objectives, 'steps': deepcopy(proposed)})
            allocated.update(s['id'] for s in proposed)
            log('plan_accepted', revision=len(plans), plan=deepcopy(proposed),
                note='Qwen拆分需求并准备引用和参数；程序只检查结构与边界，不证明需求覆盖或语义正确。')
            return proposed

        log('run_started', mode='agent', backend='anyjev', task=task, configuration=self.config,
            model_identity='independent AnyJev + Qwen; not commercial Jev', available_ram_mb=available_ram_mb())
        try:
            if not self.engine.model_ready('decision'):
                raise ValueError('本地决策模型未准备。')
            gate_candidates = [
                {'id': 'plan', 'description': '现有离线计算、统计、文本处理或本地资料服务能够尝试此任务；先拆分需求再规划'},
                {'id': 'clarify', 'description': '用户要求翻译、总结、改写或分析特定原文，但没有提供所需原文，先停止并要求补充资料'},
                {'id': 'stop', 'description': '用户要求实际连接或操作未接入设备、观察现场、访问实时网络或其他未登记功能，停止并说明能力限制'}]
            if task.get('input', '').strip():
                gate_candidates = [c for c in gate_candidates if c['id'] != 'clarify']
            entry_requirements = re.findall(r'^\s*\d+[.、)）]\s*(\S.*)\s*$', task['goal'], re.M)
            gate_state = {'stage': 'whole_task_capability_check',
                'scope': 'first_numbered_requirement' if entry_requirements else 'whole_goal',
                'overall_goal': entry_requirements[0] if entry_requirements else task['goal'],
                'input_present': bool(task.get('input', '').strip()), 'input_characters': len(task.get('input', ''))}
            gate = self.local.request('decide_agent', {'state': gate_state, 'candidates': gate_candidates}, timeout())
            probabilities, confidence = normalize_probabilities(gate['probabilities'], [c['id'] for c in gate_candidates])
            choice = max(probabilities, key=probabilities.get)
            decisions += 1
            labels.update(plan='拆分需求并规划', clarify='补充必要资料')
            log('decision', step=0, choice=choice, **{**gate, 'probabilities': probabilities, 'confidence': confidence})
            gate_initial = choice
            if choice == 'stop' and task.get('input', '').strip():
                reviews += 1
                log('route_review_started', step=0, original_choice=choice, reason='已收到用户资料，复核整项任务是否确实超出能力。')
                try:
                    review = self.local.request('review_agent', {'state': gate_state, 'candidates': gate_candidates}, timeout())
                    if review.get('choice') not in {c['id'] for c in gate_candidates}:
                        raise ValueError('整项任务复核不在可用候选内。')
                    choice = review['choice']
                    log('route_review_finished', step=0, **review)
                except Exception as exc:
                    log('route_review_failed', step=0, error=str(exc)[:500])
            log('route_finalized', step=0, initial_choice=gate_initial, choice=choice, reviewed=choice != gate_initial)
            if choice != 'plan':
                raise ValueError('未收到必要原文，请补充后再运行。' if choice == 'clarify' else '决策模块判断当前离线能力不足，已停止；未执行设备或联网操作。')
            queue = generate_plan()
            for step in range(1, min(20, self.config.get('agent_max_steps', 12))+1):
                timeout()
                current = queue[0] if queue else None
                params, text, excluded, candidates = {}, '', {}, []
                if current:
                    if current['id'] not in bindings:
                        source_candidates = [{'id': '$input', 'description': '使用用户提供的原始资料'}]
                        source_candidates += [{'id': '$'+k, 'description': '使用已完成子任务'+k+'的输出：'+v['goal']} for k, v in outputs.items()]
                        if len(source_candidates) == 1:
                            source_choice = '$input'
                            log('input_bound', subtask_id=current['id'], source=source_choice, method='only_available_source')
                        else:
                            source_decision = self.local.request('decide_agent', {'state': {'stage': 'input_binding',
                                'current_subtask': current, 'available_results': {k: {'goal': v['goal'], 'preview': result_text(v['result'])[:400]} for k, v in outputs.items()},
                                'user_input_present': bool(task.get('input', '').strip())}, 'candidates': source_candidates}, timeout())
                            source_probabilities, source_confidence = normalize_probabilities(source_decision['probabilities'], [c['id'] for c in source_candidates])
                            source_choice = max(source_probabilities, key=source_probabilities.get)
                            decisions += 1
                            log('input_source_decision', subtask_id=current['id'], choice=source_choice,
                                **{**source_decision, 'probabilities': source_probabilities, 'confidence': source_confidence})
                            log('input_bound', subtask_id=current['id'], source=source_choice, method='anyjev_choice')
                        bindings[current['id']] = source_choice
                    current = {**current, 'input': bindings[current['id']]}
                    text = bind(current['input'], task.get('input', ''), outputs)
                    params = {k: bind(v, task.get('input', ''), outputs) for k, v in current['parameters'].items()}
                    subtask = {'goal': current['goal'], 'input': text, 'parameters': params}
                    contract = build_contract(subtask)
                    ram = available_ram_mb()
                    for item in REGISTRY:
                        if item.id in ('stop', 'remote_llm'):
                            continue
                        reason = None
                        if contract['blocked_reason'] == 'missing_material':
                            reason = '本子任务缺少所需原文，不能用检索、计数或无资料生成替代。'
                        elif item.id in failed:
                            reason = '本子任务已尝试此服务，不原样重复。'
                        elif item.id in ('local_text', 'knowledge_qa', 'retrieve') and ram is not None and ram < 1200:
                            reason = '可用内存低于保守下限。'
                        elif item.id in ('retrieve', 'knowledge_qa') and not self.engine.model_ready('retrieval'):
                            reason = '本地检索模型未准备。'
                        elif item.id == 'local_text' and requires_reference(subtask, self.config.get('reference_topics', [])):
                            reason = '已登记主题需要资料支持。'
                        elif item.id == 'local_text' and not text.strip() and task_kind(current['goal']) in ('translation', 'summary', 'rewrite', 'extraction', 'source_qa'):
                            reason = '缺少原文，不能生成替代资料。'
                        else:
                            try:
                                probe = dict(subtask, parameters={**params, 'query': params.get('query', current['goal'])})
                                self.engine.prepare(item.id, probe)
                            except (ValueError, SyntaxError, ArithmeticError) as exc:
                                reason = str(exc)
                        if reason:
                            excluded[item.id] = reason
                        else:
                            candidates.append({'id': item.id, 'description': item.description})
                    if replans < 1 and len(outputs) < 6:
                        candidates.append({'id': 'replan', 'description': '当前计划不适用或调用失败，利用真实反馈重新拆分剩余任务（仅一次）'})
                else:
                    candidates.append({'id': 'finish', 'description': '所有计划子任务已有返回结果；逐项整理原始成果，交付为待核查并结束'})
                candidates.append({'id': 'stop', 'description': '任务缺少必要资料、超出离线能力或已无合理执行方法；说明限制并停止'})
                log('candidates_filtered', step=step, subtask=current, available=[c['id'] for c in candidates], excluded=excluded)
                state = {'overall_goal': task['goal'], 'current_subtask': current, 'input_as_data': text[:2000],
                    'pending_subtasks': [{'id': s['id'], 'goal': s['goal']} for s in queue],
                    'completed': {k: {'service': v['service'], 'goal': v['goal'], 'output': result_text(v['result'])[:700]} for k, v in outputs.items()},
                    'recent_feedback': [e for e in events if e['event'] in ('invocation_failed', 'result_blocked')][-2:],
                    'remaining_seconds': round(deadline-time.monotonic(), 2), 'remaining_replans': 1-replans}
                t = time.monotonic()
                decision = self.local.request('decide_agent', {'state': state, 'candidates': candidates}, timeout())
                probabilities, confidence = normalize_probabilities(decision['probabilities'], [c['id'] for c in candidates])
                choice = max(probabilities, key=probabilities.get)
                decisions += 1
                log('decision', step=step, subtask_id=current['id'] if current else None, choice=choice,
                    duration_ms=round((time.monotonic()-t)*1000, 2), **{**decision, 'probabilities': probabilities, 'confidence': confidence})
                initial_choice = choice
                if choice == 'stop' and reviews < 1 and any(c['id'] not in ('stop', 'replan') for c in candidates):
                    reviews += 1
                    log('route_review_started', step=step, original_choice=choice, reason='停止前复核当前能力与执行反馈。')
                    try:
                        review = self.local.request('review_agent', {'state': state, 'candidates': candidates}, timeout())
                        if review.get('choice') not in {c['id'] for c in candidates}:
                            raise ValueError('复核不在可用候选内。')
                        choice = review['choice']
                        log('route_review_finished', step=step, **review)
                    except Exception as exc:
                        log('route_review_failed', step=step, error=str(exc)[:500])
                if current and contract['operation'] not in ('text_stats', 'calculation') and choice in ('text_stats', 'retrieve', 'knowledge_qa') and supplied_text_transformation(subtask) and any(c['id']=='local_text' for c in candidates):
                    previous = choice
                    choice = 'local_text'
                    log('controller_override', step=step, original_choice=previous, choice=choice,
                        reason='原文变换必须处理当前绑定资料，不能用计数或重新检索替代。', method='supplied_text_source_policy')
                log('route_finalized', step=step, initial_choice=initial_choice, choice=choice, reviewed=choice != initial_choice)
                if choice == 'stop':
                    outcome['reason'] = '决策模块选择停止；保留已执行成果，未完成子任务见计划与失败记录。'
                    log('controller_stop', step=step, reason=outcome['reason'])
                    break
                if choice == 'replan':
                    replans += 1
                    queue = generate_plan({'remaining_plan': queue, 'recent_feedback': state['recent_feedback']})
                    failed.clear()
                    continue
                if choice == 'finish':
                    outcome = {'status': 'needs_review', 'execution_complete': True,
                               'reason': '计划内子任务已执行，逐项交付结果；计划覆盖与答案质量仍需核查。'}
                    log('agent_delivered', step=step, reason=outcome['reason'])
                    break
                try:
                    t = time.monotonic()
                    subtask = {'goal': current['goal'], 'input': text,
                               'parameters': {**params, 'query': params.get('query', current['goal'])}}
                    arguments = self.engine.prepare(choice, subtask)
                    log('invocation_started', step=step, subtask_id=current['id'], action=choice, parameters=arguments)
                    if choice == 'calculator':
                        result = {'expression': arguments['expression'], 'value': safe_calculate(arguments['expression'])}
                    elif choice == 'text_stats':
                        source = arguments['text']
                        result = {'characters': len(source), 'nonempty_lines': sum(bool(s.strip()) for s in source.splitlines()), 'whitespace_words': len(source.split())}
                    else:
                        operation = {'local_text': 'generate', 'retrieve': 'retrieve', 'knowledge_qa': 'knowledge_answer'}[choice]
                        payload = {**arguments, 'goal': current['goal'], 'task_contract': build_contract(subtask)}
                        result = self.local.request(operation, payload, timeout())
                    timeout()
                    accepted, reason = usable(result)
                    checked = {'status': 'needs_review' if accepted else 'blocked', 'semantic_verified': False, 'reason': reason}
                    log('invocation_finished', step=step, subtask_id=current['id'], action=choice, call_success=True,
                        duration_ms=round((time.monotonic()-t)*1000, 2), result=result, validation=checked, available_ram_mb=available_ram_mb())
                    if accepted:
                        outputs[current['id']] = {'goal': current['goal'], 'service': choice, 'result': result, 'validation': checked}
                        queue.pop(0)
                        failed.clear()
                    else:
                        failed.add(choice)
                        log('result_blocked', step=step, action=choice, reason=reason)
                except Exception as exc:
                    failed.add(choice)
                    log('invocation_failed', step=step, subtask_id=current['id'], action=choice, call_success=False,
                        duration_ms=round((time.monotonic()-t)*1000, 2), error=str(exc)[:500])
        except Exception as exc:
            outcome['reason'] = str(exc)[:500]
            log('run_interrupted', error=outcome['reason'])
        blocks = ['【' + key + '】' + v['goal'] + '\n' + result_text(v['result']) for key, v in outputs.items()]
        report = {'run_id': run_id, 'mode': 'agent', 'backend': 'anyjev', **outcome,
            'task_complete': False, 'semantic_accuracy': None,
            'completion_scope': 'model_proposed_plan_execution_only',
            'task_contract': {'operation': 'general_agent', 'planner': 'local Qwen', 'selector': 'AnyJev + Qwen', 'max_subtasks': 6},
            'plans': plans, 'input_bindings': bindings, 'subtask_results': outputs, 'pending_subtasks': queue,
            'result': {'text': '\n\n'.join(blocks) if blocks else outcome['reason'],
                'quality': {'status': 'unverified_agent_results', 'semantic_verified': False}},
            'decision_calls': decisions, 'replans': replans, 'route_reviews': reviews,
            'invocation_attempts': sum(e['event'] == 'invocation_started' for e in events),
            'successful_calls': sum(e['event'] == 'invocation_finished' for e in events),
            'remote_attempts': 0, 'capability_labels': labels, 'events': events,
            'total_ms': round((time.monotonic()-started)*1000, 2),
            'model_identity': 'independent AnyJev + Qwen; not commercial Jev'}
        folder = self.root / 'logs'
        folder.mkdir(exist_ok=True)
        path = folder / (run_id+'.json')
        path.write_text(json.dumps({'created_at': datetime.now(timezone.utc).isoformat(), **report}, ensure_ascii=False, indent=2), 'utf-8')
        report['log_file'] = str(path)
        return report
