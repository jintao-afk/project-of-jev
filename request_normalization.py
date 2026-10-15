"""Conservative parameter extraction. It supplies parameters, never chooses a service."""
import re

def normalize_request(request: dict) -> tuple[dict, list[dict]]:
    task = {**request, 'parameters': dict(request.get('parameters', {}))}
    derived = []
    if 'expression' not in task['parameters']:
        for source in ('input', 'goal'):
            text = task.get(source, '').strip().translate(str.maketrans('×÷（）', '*/()'))
            text = re.sub(r'^(?:请)?(?:帮我)?(?:计算|算一下|求值)\s*[:：]?\s*', '', text)
            text = re.sub(r'\s*(?:等于多少|是多少|的结果)?[?？。=]?\s*$', '', text)
            if len(text) <= 200 and re.fullmatch(r'[\d\s()+*/%.\-]+', text) and re.search(r'\d', text) and re.search(r'[+*/%\-]', text):
                task['parameters']['expression'] = text
                derived.append({'parameter': 'expression', 'source': source, 'value': text,
                                'method': 'restricted_expression_parser'})
                break
    return task, derived
