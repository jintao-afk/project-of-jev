# 研究方法借鉴与落地：证据反馈、失败记忆、受限修复

日期：2026-10-16。基于离线 R1 0.6.0，新增报告协议 `evidence-repair-v2`。
实际决策实现是独立 AnyJev + Qwen3-1.7B，文字处理共用已有权重；不是商用 Jev。
本轮不引入新框架依赖、不下载模型、不启用远端，也不开展有效性对比。

## 研究出处与采用范围

1. **CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing，ICLR 2024**。
   [论文](https://arxiv.org/abs/2305.11738) · [作者实现](https://github.com/microsoft/ProphetNet/tree/master/CRITIC)。
   借鉴工具检查产生外部反馈，再由模型决定后续动作。我们实现本地算术参考、原文有限事实检查和摘录来源检查，并把具体差异交回决策模块。
   不使用其联网检索实验流程，不声称复现论文，也不沿用论文的性能结论。
2. **Reflexion: Language Agents with Verbal Reinforcement Learning，NeurIPS 2023**。
   [论文](https://papers.nips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954cd888628510e90-Abstract-Conference.html) · [作者实现](https://github.com/noahshinn/reflexion)。
   借鉴保留失败经验供后续尝试参考。本轮使用程序生成、可追溯的结构化失败记录，不让小模型自由编造失败原因。
   记忆仅限本任务及续办阶段，不跨任务训练或积累，不能称为完整 Reflexion 或强化学习实现。
3. **LangGraph 状态持久化**。
   [官方文档](https://docs.langchain.com/oss/python/langgraph/persistence)。沿用已有阶段检查点，并增加失败记忆保存和加载验证。
   未迁移到 LangGraph，未新增每个节点的崩溃恢复。本轮仍是阶段级保存，进程在阶段中途退出时不保证恢复该阶段内的每一步。

以上为方法启发，由本项目独立编写实现，没有复制上游代码。原始论文的方法与本地工程约束分别标注；以后如直接引入代码，需随具体版本保留其许可证与版权声明。

## 已实现

- **证据反馈**：新模块 research_control.py 在模型调用之外执行检查。四则算式用 Fraction 表达的独立参考值与生产结果比较，容差为相对/绝对 1e-12；不覆盖的整除和取模明确标记 not_checked。文字计数记录每个字段的期望和实际值。
- **原文检查**：改写等任务复用并在控制器侧执行有限的数字、时间、未知状态等检查，不相信返回的 quality 标签。等值小数格式如 3 和 3.000000 不当成新增事实。仍不具备完整实体、否定、数量关系或语气等价检查。
- **摘录核验**：已声明为摘录模式的输出，逐条检查用户原句或登记知识条目，并重建允许的整份摘录文本；真正的来源引用不能为额外生成的结论提供自动背书。此检查不证明相关性、充分性或资料本身正确。
- **失败记忆**：保存服务、原目标、输入与调用参数指纹、具体失败原因、run_id；最多 48 条。重规划或续办不会清空这些记录。同目标、同输入、同参数的失败调用被排除；补充不同原文形成新指纹。仅有工作进程恢复、输入仍完全相同的情况不会自动放行，需新建任务重试。
- **受限修复**：重规划不再重新生成需求列表，而是固定未完成目标、保持顺序及原算式/查询约束，只让 Qwen 准备受限参数。已绑定输入和显式依赖不可更换；尚未绑定的用户编号任务仍由输入选择步骤决定来源。记录旧步骤到新步骤的 repairs 映射，拒绝新增目标、用计数替代翻译等已识别的任务类型替换。
- **停止边界**：只剩一个候选时由程序处理并记录 controller_single_candidate，不伪造一次模型判断。预算、最多六个唯一子任务和一次重规划约束未放宽；四项待办可能因总子任务预算而无法整体重规划。
- **记录**：完整检查放在 result_checked 与 invocation_finished；模型收到有上限的反馈预览。调用成功、检查阻断、模型动作和程序筛选分别记录。semantic_accuracy 保持 null。

“重规划”在本版是受约束的参数与后续服务修复，不是自由生成新的任务树。自动初始拆分仍是实验性能力，尚不能保证完整覆盖原始自然语言目标。

## 验证与剩余失败

68 项 Python 自动检查通过，其中本轮新增 10 项，覆盖错误数值、浮点容差、未覆盖运算、改写状态改变、伪造引用、引用后额外断言、失败记忆续办、重复调用排除，以及验证器异常不得冒充调用失败。
日志：logs/research-tests-final-20261016.txt。测试替身不计为真实模型表现。

首次真实开发运行发现单候选调用 AnyJev 会报错，已修复并保留原日志。该运行期间源文件有增量修改，其结束时记录的源码哈希不能用作精确运行版本证明；最终重新运行会单独保存启动时哈希并检查运行期间源码未变。
初次运行还观察到：改写把确定人数写为“预计”，未被有限事实检查拦截；总结请求可能被模型提前停止。此类问题不能以字符串包含或输出非空计为语义通过。

最终运行结果见本文件末尾及 evaluation_data/research-adaptation-20261016.json 中的日志索引。

## 复现与使用

```powershell
cd 'D:\1 jev\jev-edge-prototype'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# 真实验证启动独立模型进程，避免与工作台推理争用显存：
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\stop.ps1
.\.venv\Scripts\python.exe .\verify_research.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

工作台使用“多步协调 / 本地决策”。完整 JSON 中查看 controller_protocol、failure_memory、plans.repairs 与 result_checked。
环境仍依赖 D:\Anaconda；日志和私有任务记录保存在 D 盘并被 Git 忽略。新脚本只使用新开发请求，不读取冻结最终测试集。

## Git 交接

本阶段修改 agent.py、task_store.py、tests/test_agent.py、tests/test_feedback.py；新增 research_control.py、tests/test_research_control.py、verify_research.py、本说明和轻量清单。
修改前字节保存在 evaluation_data/snapshots/pre-research-20261016/；未修改历史评价或已有冻结清单，未做全项目复制备份。
沿用当前 .gitignore 排除模型、环境、缓存、运行日志和私有资料。工作区还有以前阶段未提交内容，用户提交前须一并审阅。

```powershell
git status --short
git diff --stat
git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check
git ls-files --others --exclude-standard
```

建议提交说明：`借鉴CRITIC与Reflexion完善证据反馈和受限任务修复`
代理未执行 git add、commit、tag、push 或账户配置。

## 最终真实运行记录

日志：`logs/research-smoke-20261016-120608-234193.json`。启动时源码哈希已记录，`source_unchanged_during_run=true`。五项开发请求，远端调用均为零；未将它们计为独立测试集或语义准确率。

| 开发请求 | 实际结果 | 耗时 |
| --- | --- | --- |
| 两道算式 | 返回 9 和 0.30000000000000004，分别与独立有理数参考 9、3/10 在声明容差内一致 | 14.59 秒，含冷加载 |
| 正式通知改写 | 返回内容，但把确定人数写为“预计参加人数”，人工复核发现语气改变，有限检查未发现；仍为 needs_review | 2.38 秒 |
| 总结后计数 | 模型在调用前选择停止，未完成；不算通过 | 0.91 秒 |
| 本地资料问答 | 返回登记原文，来源对应及无额外生成文本检查通过；不据此证明完整语义质量 | 1.37 秒 |
| 注入文字服务异常 | AnyJev 选择 replan；新计划保留原翻译目标与输入，失败记录仍在。程序排除重复调用，只剩停止，安全停止；不是恢复成功 | 1.42 秒 |

耗时为本机开发观测，不能当作稳定延迟基准。详细输入、输出、选择、错误、内存与模型资源字段在完整日志及阶段成果内。
下一步最值得处理的是“不必要停止”与“语气/数量关系保留”；当前更严格的候选筛选也可能改变模型选项分数，应在后续独立开发数据中研究，而不通过放宽验证来掩盖。
