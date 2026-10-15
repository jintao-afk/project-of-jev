"""Build the delivery index from exact, preserved experimental records."""
import json
from datetime import datetime, timezone
from evaluation_runner import ROOT, digest
from review_iteration import DEVELOPMENT
from review_holdout_v031 import FILES


def read(name):
    path = ROOT / 'logs/evaluations' / name
    raw = json.loads(path.read_text('utf-8'))
    reviewed = json.loads(path.with_name(path.stem + '-reviewed.json').read_text('utf-8'))
    return {'file': str(path.relative_to(ROOT)), 'sha256': digest(path), 'raw': raw, 'review': reviewed}


if __name__ == '__main__':
    dev = {name: read(file) for name, file in DEVELOPMENT.items()}
    final = {name: read(file) for name, file in FILES.items()}
    frozen_path = ROOT / 'evaluation_data/release-v031.json'
    frozen = json.loads(frozen_path.read_text('utf-8'))
    mismatches = [name for name, value in frozen['implementation_sha256'].items() if digest(ROOT / name) != value]
    if mismatches:
        raise RuntimeError('Frozen files changed: ' + str(mismatches))
    backup = ROOT / '.repair-backups/v031-20261015-120456'
    historical = {name: digest(ROOT / name) == digest(backup / name)
                  for name in ('evaluation_data/release.json', 'evaluation_data/final.json')}
    selected = [*dev.values(), *final.values()]
    for item in selected:
        if item['raw']['remote_attempts'] or item['raw']['semantic_accuracy'] is not None:
            raise ValueError('Remote call or original semantic score was modified.')
        if item['review']['report_sha256'] != item['sha256']:
            raise ValueError('Review hash mismatch.')
    columns = ['cases', 'initial_decision_cases', 'initial_route_matches', 'reviewed_cases',
               'controller_adjustments', 'final_route_matches', 'successful_calls',
               'verified_complete_cases', 'text_service_generations', 'generation_recovery_cases',
               'latency_ms', 'resource_observations', 'remote_attempts']
    def compact(item):
        return {'record': item['file'], 'sha256': item['sha256'],
                **{key: item['raw'].get(key) for key in columns},
                **{key: item['review'][key] for key in ('semantic_pass', 'semantic_fail', 'semantic_unresolved', 'factuality')}}
    summary = {'version': '0.3.1', 'created_at': datetime.now(timezone.utc).isoformat(),
               'model_identity': 'Independent AnyJev + Qwen3-1.7B; not commercial Jev weights',
               'development': {k: compact(v) for k, v in dev.items()},
               'holdout': {k: compact(v) for k, v in final.items()},
               'frozen_manifest_sha256': digest(frozen_path), 'frozen_mismatches': mismatches,
               'historical_release_and_holdout_unchanged': historical,
               'independent_review_limit': 'Codex evidence-based authored review; not Qwen self-rating, human double labeling or external blind evaluation.',
               'service_check': 'reports/service-check-v031-20261015-122357.json',
               'validation': {'targeted_unit_tests': 20, 'frontend_replay_checks': 22,
                              'browser_visual_check': 'not performed; earlier localhost browser policy denial not bypassed'}}
    (ROOT / 'reports/progress-20261015-v031.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    lines = ['# 2026-10-15 · 离线通用框架 v0.3.1', '',
             '已在原D盘项目完成修改并启动v0.3.1。完全离线，继续使用已有AnyJev 0.3.0 + Qwen3-1.7B与BGE权重；没有换模型、下载、远端调用或在C盘建立项目。当前实现独立于商用Jev，不能将本地结果归为商用Jev效果。', '',
             '## 本版交付', '',
             '1. `task_contract.py`用有限显式规则提取操作、材料要求、输出形式、未知字段状态及否定动作；契约及规则方法进入日志和界面。契约不是模型独立决策，也不是完整语义解析。新增同义表述识别仍是程序规则，未隐藏为模型收益。',
             '2. 按字段区分未提供/未说明、未确定、未公布、未测量、未核查；改写检查否定动作与同句数量，避免另一个句子的否定掩盖原断言极性变化。增加明确日期被弱化为暂定的信号检查。它们会漏报或误报，不能证明主体完整、动作等价或通用事实性；跨语言翻译没有完整状态对齐。',
             '3. 改写/写作触发保护后最多重新生成一次，保留两次真实草稿、检查、token和耗时。仍失败时保留原文或拒交，不把安全退回计为完成。`needs_review`本身不触发重试。',
             '4. 停止选择与可用能力冲突时，即使集中度高也允许复核；每请求总共最多一次路线复核，复核仍可选择停止。AnyJev首次概率提示未加入契约，原始选择、复核、程序调整分别统计。缺材料或明确不支持操作可由程序预检查停止；没有调用模型时不补造首次选择。',
             '5. 工作台增加可展开的任务要求与保留状态、重写说明、真实生成次数，以及缺材料状态。新增`打开工作台.cmd`和`open.ps1`，先健康检查启动再打开页面。服务日志启动前归档。', '',
             '## 验证结果与真实边界', '',
             '新开发16条先在未修改的v0.3.0上实际运行，再运行新版、规则及两项消融。开发内容覆盖通用任务，并使用换一种表达、说得正式一些、用更短的话表达等措辞。原始旧版基线不是新代码开关模拟。', '',
             '| 开发方案 | 实际首次决策数 | 首次匹配 | 复核次数 | 程序调整 | 最终路由匹配 | 综合质量通过/失败/未决 |',
             '|---|---:|---:|---:|---:|---:|---|']
    labels = {'baseline-v030': '原v0.3.0', 'contract': 'v0.3.1 AnyJev', 'rules': 'v0.3.1规则',
              'no-stop-review': '关闭停止复核', 'no-preservation': '关闭字段状态/否定绑定检查'}
    for name, item in dev.items():
        raw, review = item['raw'], item['review']
        count = raw.get('initial_decision_cases', sum(r['initial_choice'] is not None for r in raw['results']))
        lines.append(f"| {labels[name]} | {count}/16 | {raw['initial_route_matches']}/{count} | {raw['reviewed_cases']} | {raw['controller_adjustments']} | {raw['final_route_matches']}/16 | {review['semantic_pass']} / {review['semantic_fail']} / {review['semantic_unresolved']} |")
    lines += ['', '开发解释：新版6次停止复核使最终路由由消融的11/16变为16/16，但综合质量只从8/16变为10/16。c10提取与c16限制回答获得质量收益；c04仍原样返回、c06反例错误、c08未压缩，c12原本正确停止而复核没有额外质量收益。不能把6次复核或路由提升当成6条正确答案。', '',
              '字段检查消融的可见输出与当前方案相同，本组真实生成未证明其独立增益。相关识别与误用场景有单元测试证据，不能替代真实模型质量效果。旧版c01“原因及地点尚未明确”有状态歧义，保留未决，未强行计错；旧版综合比例因此保持null。', '',
              '开发c05暴露真实退化：旧版通知可接受，新版生成把确定日期写成“暂定为下周四”，重写后仍重复，最终拒交。拦住了状态变化，但任务失败且多一次生成；未报告为补救成功。', '',
              '随后冻结实现，再运行新的16条留出。它们覆盖问答、资料、计算、翻译、总结、改写、提取、写作、缺资料、未知事实、操作限制与统计；不进入推理提示，冻结后未根据失败改代码、提示或阈值。', '',
              '| 新留出方案 | 首次匹配/实际决策 | 预检查无模型决策 | 复核 | 程序调整 | 最终路由 | 成功调用 | 确定性验收 | 五维综合质量 |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name, item in final.items():
        raw, review = item['raw'], item['review']
        lines.append(f"| {labels[name]} | {raw['initial_route_matches']}/{raw['initial_decision_cases']} | {raw['preflight_or_other_no_decision_cases']} | {raw['reviewed_cases']} | {raw['controller_adjustments']} | {raw['final_route_matches']}/16 | {raw['successful_calls']} | {raw['verified_complete_cases']} | {review['semantic_pass']}/16 |")
    lines += ['', '**新留出没有证明AnyJev优于规则。** 两者综合通过均12/16；AnyJev最终路由15/16、规则16/16，仍是不同指标。全部远端请求0。原始记录semantic_accuracy继续为null；另存绑定哈希的五维逐条标注，不用来源列表、字符串或非空输出代替语义正确。', '',
              '标注由Codex对实际输出据作者材料、逻辑定义、独立手算及本地代码/知识库逐条核查，不是被测Qwen自评分；它不是人工双标或外部盲测。开发与留出均较小且由开发者编写，不能外推真实部署正确率。', '',
              '## 留出仍失败的四条', '',
              '- h02：AnyJev把“4整除是否推出2整除”送到项目资料问答，返回资料不足；规则虽然选对文本服务，却先说不一定、后面又代数证明一定，答案矛盾。错误路线与错误回答分别记录。',
              '- h03：所引local-components是真实原文，但未覆盖格式合格与语义正确的明确区别，相关的quality-check未被选择。引用真实不等于证据充分。',
              '- h07：14/10/4及未核查未测量均保留，但三句逐句摘录，没有完成一句短话。',
              '- h10：预算未提供、会议时间未确定保持不变，但逐字返回，没有完成正式改写。', '',
              '留出AnyJev事实性12通过、0失败、4不适用；规则12通过、1失败、3不适用。停止/无法回答没有事实性答案，不能把不适用算正确，更不能据此宣称消除幻觉。', '',
              '## 耗时与资源', '']
    for name, item in final.items():
        raw = item['raw']; latency = raw['latency_ms']; resource = raw['resource_observations']
        lines.append(f"- {labels[name]}：整体中位{latency['median']:.3f}ms、最大{latency['max']:.2f}ms；工作进程Torch累积显存分配峰值{resource['worker_peak_cuda_allocated_mb']}MB；可用RAM最小快照{resource['minimum_available_ram_mb']}MB。")
    lines += ['', '上述包含不同路线与冷启动，顺序运行、未控制负载和温度，不能据此宣称速度优势。Torch峰值不是整卡总显存、功耗或目标设备性能。生成次数按成功返回的服务内轨迹统计，包括证据选择与重写，另记录路线复核；若工作进程被中断，未返回的内部生成次数不可知，不应把0当作证明没有生成。', '',
              '## 测试、服务与交付入口', '',
              '- `logs/validation-v031-20261015.log`：20项针对性单元测试通过，包含字段状态交换、否定转移与数量绑定、单次重写成功/失败、不得无限重试、高分停止复核仍可停止、预检查没有伪造模型选择。合成模型替身的测试成功不是实际模型重写成功。',
              '- `logs/ui-validation-2026-10-15T04-19-08-703Z.json`：22项源代码与已保存真实响应的最小DOM重放通过，不是浏览器端到端测试。',
              '- `reports/service-check-v031-20261015-122357.json`：2026-10-15 12:23:57（上海）实际HTTP核对页面200、v0.3.1、离线、两模型文件就绪；实际AnyJev计算(21+15)/6=6并确定性验收，真实通知返回仍为needs_review，远端0。',
              '- 本轮未做浏览器视觉验收；先前本机浏览器访问被工具策略拒绝，没有换浏览器或间接执行绕过。新增双击入口做了PowerShell语法检查，启动服务与HTTP路径另作实测，未自动触发浏览器打开。', '',
              '日常使用：双击项目根目录`打开工作台.cmd`，或在项目根目录运行`./start.ps1`，访问http://127.0.0.1:8765/。若代码版本与运行服务不一致，先`./stop.ps1`再启动。无需重新安装或下载模型。', '',
              '## 复现', '',
              '先停止页面服务，避免另一个评价进程重复加载Qwen。以下命令均在D盘项目根目录执行，完成后重新start.ps1。', '',
              '```powershell', '$env:PYTHONIOENCODING="utf-8"', r'.\stop.ps1',
              r'.\.venv\Scripts\python.exe -m unittest discover -s tests -v', r'node tests\ui_replay.cjs',
              r'.\.venv\Scripts\python.exe run_iteration.py --profile contract',
              r'.\.venv\Scripts\python.exe run_iteration.py --profile rules',
              r'.\.venv\Scripts\python.exe run_iteration.py --profile no-stop-review',
              r'.\.venv\Scripts\python.exe run_iteration.py --profile no-preservation',
              r'.\.venv\Scripts\python.exe run_iteration.py --profile contract --dataset evaluation_data/holdout-v031.json --freeze evaluation_data/release-v031.json',
              r'.\.venv\Scripts\python.exe run_iteration.py --profile rules --dataset evaluation_data/holdout-v031.json --freeze evaluation_data/release-v031.json',
              r'.\start.ps1', '```', '',
              '留出命令只复现当前冻结版；下一版若利用这些失败开发，必须降级为回归集并另建留出。freeze_iteration.py采用独立文件且不允许覆盖；旧release.json没有重写。旧evaluate/final命令仍对应历史v0.3.0冻结版，不能在v0.3.1上绕过哈希校验重跑。', '',
              '## 保留、已知记录问题与索引', '',
              '修改前实现备份：`.repair-backups/v031-20261015-120456`。原v0.3.0 release.json和final.json与备份哈希一致；原模型评价与逐条标注没有覆盖。当前UI不同于原v0.3.0冻结UI，若完整复现历史版需恢复对应代码及原UI备份，不仅恢复ui.html。', '',
              '记录问题：旧前端重放脚本写死logs/ui-validation-20261014.json，本轮首次重放覆盖了该UI验证摘要，无法恢复原字节；原reports/ui-refresh-20261014.json仍保留当时20项通过的汇总。已将脚本改为带唯一时间戳且禁止覆盖。此问题不涉及原始模型评价、标注或冻结数据。', '',
              '主数据与哈希索引：`reports/progress-20261015-v031.json`。原始开发/留出报告及对应-reviewed.json：', '']
    lines += ['- `' + item['file'] + '`' for item in selected]
    lines += ['', '## 下一步共性问题', '',
              '最值得研究的是“复核预算应该花在哪里”：当前只复核停止或低分，未覆盖高分但与任务能力不符的非停止路线；一般问答生成也会自相矛盾。下一版可在新的开发/留出划分上研究契约与所选能力不一致、答案内部矛盾、证据覆盖缺项三类可观察信号，比较其单位额外调用带来的质量收益。不能用同一模型再打一个高分代替验证，也不应以不断追加规则或扩大模型掩盖收益来源。']
    (ROOT / 'reports/progress-20261015-v031.md').write_text('\n'.join(lines) + '\n', 'utf-8')
    with (ROOT / '推进记录.md').open('a', encoding='utf-8') as stream:
        stream.write('\n## 2026-10-15：任务契约与有限复核 v0.3.1\n\n已增加显式任务契约、字段未知状态与否定绑定检查、最多一次草稿重写及一次停止冲突复核；保持原模型、离线和D盘路径。20项单元测试、22项前端重放通过，真实HTTP服务已验证v0.3.1与页面200。新留出AnyJev和规则均综合12/16，未证明模型决策优于规则；原始语义字段仍null，五维依据标注另存。开发真实重写仍失败、字段保护消融无可见差异均如实记录。报告、原始输入输出、失败及复现方式见[本轮报告](reports/progress-20261015-v031.md)。旧UI重放摘要被固定文件名意外覆盖的问题也在报告披露，已修复输出唯一命名；历史模型评价、标注及冻结数据保留。\n')
    print(ROOT / 'reports/progress-20261015-v031.md')
