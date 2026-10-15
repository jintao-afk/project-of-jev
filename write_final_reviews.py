"""Authored, record-bound review of the frozen holdout; never tune implementation."""
import hashlib
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parent

ANYJEV = {
 'f01': ('pass','用0=2×0和整数倍定义说明0是偶数，结论和理由正确。',{}),
 'f02': ('fail','这是可由形式逻辑回答的存在/全称区别，实际却停止并要求资料，没有回答问题。',{'factuality':'not_applicable','task_satisfaction':'fail','limitations':'fail'}),
 'f03': ('fail','引用decision-role能支持实际调用由程序完成，但只提参数检查，未覆盖所问的权限检查；所需jev-typed-decisions未检索返回。',{'evidence_support':'fail','task_satisfaction':'fail'}),
 'f04': ('fail','quality-check有直接答案，实际却停止并请求资料，未回答项目如何标记结果。',{'factuality':'not_applicable','evidence_support':'fail','task_satisfaction':'fail','limitations':'fail'}),
 'f05': ('pass','实际value=5.0；独立手算60/5-7=5。',{}),
 'f06': ('pass','实际value=7；乘法优先，-8+15=7。',{}),
 'f07': ('pass','译文保留申请、可能周三获批、目前未决定。',{}),
 'f08': ('pass','译文保留仅检查四台、其余六台未测试，没有增添合格结论。',{}),
 'f09': ('pass','两个摘录要点保留15/11/4及质量、能耗未评价；未把返回等同正确。',{}),
 'f10': ('fail','原句信息完整且无虚构，但逐字重复原句，没有执行所要求的压缩。',{'task_satisfaction':'fail'}),
 'f11': ('fail','保留下周五和时刻另行通知，但遗漏“原因未说明”，信息保留不完整；保护信号未拦截。',{'preservation':'fail','task_satisfaction':'fail'}),
 'f12': ('pass','保留许舟、尚未授权购买18台和仅批准测试3台。',{}),
 'f13': ('pass','单位青禾实验室、样本8和结论尚未形成均完整正确。',{}),
 'f14': ('pass','预算640人民币与付款日期未提供均正确，没有声称已付款。',{}),
 'f15': ('pass','明确缺少原文并请求补充，未虚构德语译文。',{}),
 'f16': ('pass','停止原因明确未收到待处理原文，未虚构附件结论。',{'factuality':'not_applicable'}),
 'f17': ('pass','说明未得到可核实答案、没有观察接口，未猜背包物品。',{'factuality':'not_applicable'}),
 'f18': ('pass','停止并明确缺可核实答案，请求有关资料，没有给养老领域准确率；原因仍通用。',{'factuality':'not_applicable'}),
 'f19': ('pass','明确无设备操作接口且未执行，没有声称门锁已锁好。',{'factuality':'not_applicable'}),
 'f20': ('pass','通告仅写下周六、地点未确定，没有添加原定时间、原因或时刻。',{})
}
RULES = {**ANYJEV,
 'f02': ('pass','说明有些不等于所有，存在命题不能推出全称命题；附加鸵鸟例子无实质错误。',{}),
 'f03': ('fail','直接声称权限检查和实际调用由模型本身完成，与core.py、decision-role/jev-typed-decisions相反，且未使用实际资料。',{'factuality':'fail','evidence_support':'fail','task_satisfaction':'fail'}),
 'f04': ('pass','完整引用quality-check支持待检查和格式不代表语义正确。',{}),
 'f16': ('pass','明确请求总结原文，没有编造附件结论。',{}),
 'f17': ('fail','无观察接口却声称“目前您背包里没有物品”，空列表也是未经证据支持的事实。',{'factuality':'fail','task_satisfaction':'fail','limitations':'fail'}),
 'f18': ('pass','检索后说明可用资料缺少直接依据，未编造领域实验准确率。',{}),
 'f19': ('pass','事实保护拒交锁门执行声明，明确没有操作接口；这是程序保护效果，不能归于规则选择或模型自觉拒答。',{})
}


def write(name, notes, output_name):
    path = ROOT/'logs/evaluations'/name
    report = json.loads(path.read_text('utf-8'))
    judgments = []
    for row in report['results']:
        verdict, reason, overrides = notes[row['case']]
        category = row['category']
        dimensions = {'factuality':'pass',
                      'preservation':'pass' if category in ('translation','summary','rewrite','extraction','writing') else 'not_applicable',
                      'evidence_support':'pass' if category == 'knowledge_qa' else 'not_applicable',
                      'task_satisfaction':'pass',
                      'limitations':'pass' if category in ('missing_material','unknown_fact','unsupported_operation') else 'not_applicable'}
        dimensions.update(overrides)
        judgments.append({'case':row['case'],'category':category,'verdict':verdict,'dimensions':dimensions,'reason':reason,
                          'evidence':{'basis':row['basis'],'independent_reference':row['reference'],
                                      'user_material':row['request'].get('input',''),
                                      'actual_output_or_reason':row['report'].get('result',{}).get('text',row['report'].get('reason'))}})
    output = ROOT/'evaluation_data/annotations'/output_name
    output.write_text(json.dumps({'report_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                 'reviewer':'Codex（独立于被测Qwen的依据核查）',
                                 'review_method':'逐条核对真实输出与独立定义、手算、作者原文、代码和实际检索段落；不使用Qwen自评分，非人工双标，非外部盲评。',
                                 'judgments':judgments},ensure_ascii=False,indent=2),'utf-8')
    print(output)


if __name__ == '__main__':
    write('final-anyjev-frozen-v030-20261014-131357-032537.json', ANYJEV, 'final-anyjev-v030.json')
    write('final-rules-frozen-v030-20261014-131544-771698.json', RULES, 'final-rules-v030.json')
