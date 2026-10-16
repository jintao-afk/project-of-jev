"""Assemble a reviewable stage handoff from preserved real workflow records."""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from evaluate_workflow import ROOT, IMPLEMENTATION, digest


FILES = {
    'dev_anyjev': 'workflow-dev-anyjev-20261015-135526-149962.json',
    'dev_rules': 'workflow-dev-rules-20261015-135551-019836.json',
    'final_anyjev': 'workflow-final-anyjev-20261015-140141-196798.json',
    'final_rules': 'workflow-final-rules-20261015-140200-919101.json',
}


if __name__ == '__main__':
    freeze = json.loads((ROOT / 'evaluation_data/release-v040.json').read_text('utf-8'))
    mismatches = [name for name in IMPLEMENTATION if digest(ROOT / name) != freeze['implementation_sha256'][name]]
    if mismatches:
        raise RuntimeError('Frozen runtime changed: ' + str(mismatches))
    records = {key: json.loads((ROOT / 'logs/evaluations' / name).read_text('utf-8')) for key, name in FILES.items()}
    service_name = 'service-check-v040-20261015-140535.json'
    service = json.loads((ROOT / 'reports' / service_name).read_text('utf-8-sig'))
    run_id = service['workflow_report']['run_id']
    for suffix in ('md', 'json'):
        shutil.copy2(ROOT / 'workspace/runs' / run_id / ('report.' + suffix), ROOT / 'reports' / ('example-dataset-report-v040.' + suffix))
    provenance = {'method': 'CSV extracted from existing real model evaluation reports; development demonstration only', 'files': {}}
    for name, source in {'baseline.csv': 'v031-baseline-v030-20261015-120656-396458.json', 'current.csv': 'v031-contract-20261015-121826-442178.json'}.items():
        provenance['files'][name] = {'csv_sha256': digest(ROOT / 'workspace/inbox/demo' / name),
            'source': 'logs/evaluations/' + source, 'source_sha256': digest(ROOT / 'logs/evaluations' / source),
            'fields': ['case', 'status', 'total_ms', 'invocation_attempts', 'successful_calls', 'remote_attempts']}
    (ROOT / 'workspace/inbox/demo/provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), 'utf-8')
    reviews = []
    for key in ('dev_anyjev', 'dev_rules'):
        row = next(r for r in records[key]['results'] if r['case'] == 'd-advisory')
        suggestion = next(e['result']['checks'] for e in row['report']['events'] if e['event'] == 'invocation_finished' and e['action'] == 'suggest')
        # Authored judgment of the exact inspected output, not a generic semantic scorer.
        assert suggestion == ['需要核查的问题']
        reviews.append({'case': 'd-advisory', 'backend': records[key]['backend'],
            'record': FILES[key], 'record_sha256': digest(ROOT / 'logs/evaluations' / FILES[key]),
            'actual_checks': suggestion, 'reviewer': 'Codex evidence-based inspection, not tested Qwen',
            'verdict': 'fail', 'scope': 'usefulness and task satisfaction of optional suggestions',
            'reason': '模型复制结构示例中的占位文字，没有提出针对缺失行、非法数值或状态含义的可执行核查问题；结构合格不等于建议有效。'})
    (ROOT / 'reports/workflow-advisory-review-v040.json').write_text(json.dumps(reviews, ensure_ascii=False, indent=2), 'utf-8')
    def metrics(record):
        rows = record['results']
        events = [e for row in rows for e in row['report']['events']]
        peaks = [e.get('resources', e.get('result', {}).get('resources', {})).get('cuda_peak_allocated_mb') for e in events]
        return {'cases': record['cases'], 'contract_passes': record['declared_contract_passes'],
                'delivered': record['delivered_cases'], 'remote_attempts': record['remote_attempts'],
                'reviews': sum(r['report']['route_reviews'] for r in rows),
                'decisions': sum(e['event'] == 'decision' for e in events),
                'states_with_multiple_actions': sum(e['event'] == 'candidates_filtered' and e['actionable_count'] > 1 for e in events),
                'peak_worker_cuda_mb': max([v for v in peaks if v is not None], default=None),
                'latencies_ms': {r['case']: r['report']['total_ms'] for r in rows}}
    summary = {'version': '0.4.0', 'base_commit': '7abcec5', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
               'model_identity': 'independent AnyJev + Qwen, not commercial Jev',
               'experiments': {key: {'record': 'logs/evaluations/' + FILES[key], 'record_sha256': digest(ROOT / 'logs/evaluations' / FILES[key]), **metrics(data)} for key, data in records.items()},
               'frozen_runtime_mismatches': mismatches, 'unit_tests_passed': 29, 'ui_replay_checks_passed': 27,
               'real_service_check': 'reports/' + service_name, 'semantic_accuracy': None,
               'scope': 'CSV/report mathematical contract only; not a general semantic correctness or planning benchmark.'}
    (ROOT / 'reports/progress-20261015-v040.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    lines = ['# 2026-10-15 · v0.4.0 多步文件任务初版', '',
        '本阶段在用户已提交并推送的7abcec5基础上完成开发。没有代用户提交、打标签、修改账号或推送，也没有复制整个项目做新备份。代码、权重、环境、缓存、输出继续在D盘；没有更换或下载模型。当前运行是独立AnyJev 0.3.0 + Qwen3-1.7B，并非商用Jev权重。', '',
        '## 本次跨过的边界', '',
        '工作台现在能接收一项有输入目录和明确字段的工作任务，实际读取本地CSV，选择后续动作，计算统计、检查阈值、比较两份资料，写出Markdown/JSON成果，再重新读取核验并交付下载链接。原问答、翻译、改写、检索、计算与统计模式保留。', '',
        'Jev决策模块仍负责选择下一步；程序筛选可用动作、绑定参数与文件范围、执行与验收。AnyJev使用已有Qwen实例进行概率读出，模型建议也复用同一权重。文件任务依赖由程序声明，不能称为任意目标的自主规划。', '',
        '## 实际使用', '',
        '1. 访问http://127.0.0.1:8765/，刷新至v0.4.0；双击打开工作台.cmd仍走已修复的PowerShell 5.1启动链路。',
        '2. 点击“试运行：分析历史运行数据并交付报告”，再点“运行任务”。示例读取demo下两份真实历史记录，检查total_ms严格大于2000的记录。',
        '3. 完成后可下载分析报告和结构化结果，查看实际选择/复核/执行轨迹。报告中的状态计数不代表答案正确率。',
        '4. 使用自己的数据时，在workspace/inbox内另建目录，放入1至2份UTF-8 CSV，填写目录和数值字段；状态字段、阈值可选。生成内容只写workspace/runs/<任务ID>，不修改输入文件。', '',
        '本次真实成果示例：reports/example-dataset-report-v040.md与同名JSON。数据来源与原记录SHA256见workspace/inbox/demo/provenance.json。示例只是数据处理演示，原两版记录冷热/负载不同，不能据此证明性能因果优势。', '',
        '## 真实闭环与决策边界', '',
        '开发演示AnyJev完成11次实际动作：检查目录、读取两份数据、分别统计与阈值检查、比较、写报告、重读验证、交付。原始第6步选择停止，经一次生成式复核改为第二份统计；原始选择没有改写成正确选择。规则对照也完成11步。开发演示11个选择状态中，7个有多个非停止动作，4个只有一个非停止动作；这些单一路径不能用来宣称模型复杂规划效果。', '',
        '文件任务最多16步、总300秒、单次模型调用120秒，每请求最多一次停止复核，复核仍可停止。动作失败进入状态并排除重复执行；成果损坏最多重写一次再核验，源文件变化则停止。没有任意Shell、删除、设备控制或远端动作。只在已核验交付后提供下载，交付后字节改变返回HTTP 409。', '',
        '状态、错误、完整结果、耗时与模型进程资源单独记录；可选模型建议只作为未验证检查事项。结构化CSV/report条件通过可计该范围完成；包含模型建议时仍needs_review，不代表自然语言所有要求或建议正确。', '',
        '## 开发与新留出结果', '',
        '先运行4项开发任务，再用release-v040.json冻结实际实现和另写的4项小型留出。旧release.json、release-v031.json、原始评价和标注继续保留。最终结果出来后未按失败修改冻结实现或提示。', '',
        '| 数据 | 选择方式 | 已交付报告 | 声明合同检查通过 | 停止复核次数 | 远端请求 |', '|---|---|---:|---:|---:|---:|']
    for key in ('dev_anyjev', 'dev_rules', 'final_anyjev', 'final_rules'):
        m = metrics(records[key])
        lines.append(f"| {'开发' if key.startswith('dev') else '留出'} | {'AnyJev' if key.endswith('anyjev') else '规则'} | {m['delivered']}/{m['cases']} | {m['contract_passes']}/{m['cases']} | {m['reviews']} | {m['remote_attempts']} |")
    lines += ['', '每组均含预期不应交付的负例。留出两项正常文件任务都交付；h-no-files正确说明缺材料。h-missing-column中AnyJev仅检查了目录便停止，没有实际读取确认字段缺失，按严格依据标准失败；规则读取后给出缺字段证据而通过。提前停止未伪造统计，但不算完成诊断。', '',
        '数值参考由独立Fraction有理数计算核对，区别于生产代码Decimal统计；检查有效数值、缺失/非法行、均值/中位数、阈值完整明细、两表差值与文件SHA256。它仍仅覆盖声明的数学和来源条件，不是完整语义评价，所有原始semantic_accuracy仍为null。开发者自建4项留出不是外部盲测，不能宣称通用准确率或AnyJev优于规则。', '',
        '可选模型建议有真实质量失败：两种方案均输出占位文字“需要核查的问题”，没有针对实际数据提出有用事项。虽然JSON结构检查通过，独立依据核查将建议质量记fail，见reports/workflow-advisory-review-v040.json。默认不勾选该选项。不能把这个needs_review结果当作建议已经有效。', '',
        '## 耗时与资源', '']
    for key in ('final_anyjev', 'final_rules'):
        m = metrics(records[key])
        lines.append('- ' + ('AnyJev' if key.endswith('anyjev') else '规则') + '留出逐项耗时(ms)：' + json.dumps(m['latencies_ms'], ensure_ascii=False) + '；工作进程Torch累积显存分配峰值：' + str(m['peak_worker_cuda_mb']) + 'MB。')
    lines += ['', '纯表格规则任务不加载Qwen；AnyJev需为每步付出读出开销，冷启动与不同调用路径也包含在以上时间内。这组简单任务没有展示模型调度的效率优势。Torch峰值不是整卡总显存或功耗，不能外推目标端侧设备。', '',
        '## 验证与可复现命令', '',
        '- 29项针对性单元测试通过，覆盖原能力保护、新CSV数值/缺失/非法/结构检查、一次舍入、路径越界、报告损坏后有限修复、源文件变化禁止交付与预算停止。故障注入使用测试替身，不冒充真实模型补救。',
        '- 27项前端源码与保存真实响应的DOM重放通过，新增任务模式、结构化参数、恢复单次模式、下载链接和验收范围。夹具已纳入tests/fixtures，不再依赖忽略日志才能运行。不是浏览器端到端或视觉验收；先前浏览器工具策略拒绝未被绕过。',
        '- Windows PowerShell 5.1实际CMD启动链路6项检查通过；HTTP真实AnyJev任务、两种成果下载、交付后篡改拒绝、旧计算工具返回6均通过：reports/' + service_name + '。', '',
        '评价前停止服务，避免两个Qwen工作进程重复占用显存；完成后恢复start.ps1。', '', '```powershell',
        r'.\stop.ps1', r'.\.venv\Scripts\python.exe -m unittest discover -s tests -v', r'node tests\ui_replay.cjs',
        r'.\.venv\Scripts\python.exe run_workflow.py --backend anyjev',
        r'.\.venv\Scripts\python.exe run_workflow.py --backend rules',
        r'.\.venv\Scripts\python.exe evaluate_workflow.py --split dev --backend anyjev',
        r'.\.venv\Scripts\python.exe evaluate_workflow.py --split dev --backend rules',
        r'.\.venv\Scripts\python.exe evaluate_workflow.py --split final --backend anyjev',
        r'.\.venv\Scripts\python.exe evaluate_workflow.py --split final --backend rules', r'.\start.ps1', '```', '',
        '最终命令仅固定版复现；freeze_workflow.py采用独立文件且禁止覆盖。若下一版利用失败开发，必须降级原留出并建立新留出。结果原始记录及哈希索引见reports/progress-20261015-v040.json。', '',
        '## 初版完成度与下一步', '',
        '已打通一个受限但能交付文件成果的闭环，仍未覆盖任意文件/任意目标、通用语义验收、Harness原生适配、远端升级验证、遥感或养老完整场景。两种任务模式的动作注册尚未统一成可独立扩展的插件协议，不能称整张设计图已全部实现。', '',
        '下一阶段最值得解决：把不同任务的能力登记与状态表示统一，选择确有模型/工具替代空间的任务，研究何时多花一次读出/复核能增加质量、何时按规则直接执行更合适。然后接一个小型遥感数据质量或养老记录任务验证复用；避免为了增加候选而添加无实际作用的路径。', '',
        '## Git阶段交接', '',
        '本阶段可由用户自行提交与推送，建议说明：增加离线多步文件分析与可核查报告交付v0.4.0。模型、环境、缓存、运行输出与用户输入目录不提交；demo只白名单跟踪三个演示文件和来源清单。助手未执行git add、commit、tag、push或账号/远端配置。']
    (ROOT / 'reports/progress-20261015-v040.md').write_text('\n'.join(lines) + '\n', 'utf-8')
    with (ROOT / '推进记录.md').open('a', encoding='utf-8') as stream:
        stream.write('\n## 2026-10-15：多步文件任务初版 v0.4.0\n\n在已提交的7abcec5基础上，接通受限CSV文件分析闭环：AnyJev逐步选择，程序执行读取、统计、阈值、对比、报告生成与交付核验；实际演示11步完成，保留原始停止与复核变化。29项单元测试、27项前端重放、PowerShell5.1入口与真实HTTP任务/下载/篡改拒绝/旧计算检查通过。小型留出两种方案都交付两项正常任务，声明合同AnyJev3/4、规则4/4，不能证明模型调度更优；提前停止和模型建议空泛仍为失败。保持离线与原模型，未代用户提交Git。详情见[本轮报告](reports/progress-20261015-v040.md)。\n')
    print(ROOT / 'reports/progress-20261015-v040.md')
