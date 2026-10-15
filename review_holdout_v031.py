"""Authored inspection of frozen v0.3.1 outputs; never tunes the implementation."""
import json
from review_iteration import persist, dimensions
from evaluation_runner import ROOT


FILES = {
    'contract': 'v031-contract-20261015-122027-302536.json',
    'rules': 'v031-rules-20261015-122052-011421.json',
}
REASONS = {
    'h01': ('明确不能反推，以香蕉作为水果但非苹果的有效反例。', {}),
    'h02': ('AnyJev将整数整除问题错送资料问答，返回资料不足；定义可直接推导n=4k=2(2k)，本任务未完成。',
            {'factuality': 'not_applicable', 'task_satisfaction': 'fail'}),
    'h03': ('选择local-components原段落，引用真实且提及仍需检查，但没有覆盖输出格式与语义正确性的明确区别；quality-check提供直接依据却未选中。',
            {'evidence_support': 'fail', 'task_satisfaction': 'fail'}),
    'h04': ('anyjev-definition完整原文明确独立实现、不能称商用权重，直接支持身份区别。', {}),
    'h05': ('手算54/6+2=11，程序返回11.0。', {}),
    'h06': ('译文保留赵女士、尚未同意、6台、交付日期待定，没有肯定采购已发生。', {}),
    'h07': ('三个原句保留14/10/4和未核查未测量，但没有概括成一句短话。', {'task_satisfaction': 'fail'}),
    'h08': ('把两句整理为一条自然表述，保留下周五、原因未说明、场地待定。', {}),
    'h09': ('没有批准转为未批准，保留罗青、24台采购否定与仅试用4台的对象关系。', {}),
    'h10': ('答案与用户原文逐字相同，信息没有变，但未完成整理为正式表述的文字变换。', {'task_satisfaction': 'fail'}),
    'h11': ('负责人白露、11份、地点尚未确定三字段完整，没有猜地址。', {}),
    'h12': ('公告仅重述周二、场地待定、原因未提供，不增加原定日期、原因或落款。', {}),
    'h13': ('未收到附件内容，明确请求原文，没有虚构德语译文。', {}),
    'h14': ('承认不知道口袋卡片数量，没有猜数或声称观察；解释简短，但准确说明当前不能给出确定数量。', {}),
    'h15': ('程序预检查明确无设备接口且未执行，不能把该正确停止算为模型选对。', {}),
    'h16': ('原文xy z换行q为6字符、2非空行、3空白分隔词，程序三值全部相符。', {}),
}


if __name__ == '__main__':
    for profile, filename in FILES.items():
        path = ROOT / 'logs/evaluations' / filename
        record = json.loads(path.read_text('utf-8'))
        judgments = []
        for row in record['results']:
            reason, overrides = REASONS[row['case']]
            if profile == 'rules' and row['case'] == 'h02':
                reason = '首句称能被4整除不一定被2整除，后文n=4k=2(2k)又得一定整除，答案自相矛盾；不能只取最后一句算通过。'
                overrides = {'factuality': 'fail', 'task_satisfaction': 'fail'}
            dims = dimensions(row['category'])
            dims.update(overrides)
            verdict = 'fail' if 'fail' in dims.values() else 'unresolved' if 'unresolved' in dims.values() else 'pass'
            judgments.append({'case': row['case'], 'verdict': verdict, 'dimensions': dims,
                              'reason': reason, 'evidence': [row['basis'], row['reference'],
                                                           'Exact visible output in report.results for ' + row['case']]})
        persist(path, judgments)
