# AnyJev + Qwen 执行反馈闭环初版

日期：2026-10-16。在离线 R1 0.6.0 上增量实现，报告协议 `result-feedback-v1`。
实现是独立 AnyJev + Qwen，不是商用 Jev。未更换或下载权重，未接入远端。

## 实现

每次正常返回或执行失败后，控制器保存真实结果和检查结论，下一控制轮把这些信息、待办子任务、剩余时间/轮数/重规划次数和可用内存交给 AnyJev。
模型通过现有 Qwen 权重为后续动作评分。可用结果允许继续或停止；失败/阻断允许重新筛选其他服务、请求资料、有限重规划或停止。
失败服务在当前子任务内被排除，阻断结果不能成为后续输入。重规划仍限一次、总子任务六项、控制轮数和总时限保持原约束。
缺少明确原文在执行前由程序直接暂停；超时和预算耗尽由程序直接停止，不等待模型批准。

新增事件：`result_checked`、`feedback_candidates`、`feedback_decision`、`feedback_applied`。
反馈原始选择、最终选择、是否复核和程序调整分别记录。原服务路由的 `reviewed` 字段也改为记录实际复核，而不再把程序调整算成复核。
工作台“选择与过程”显示反馈决策。完整状态、候选和分数保留在 JSON 中；分数不是正确率。

文字统计增加输入计数一致性检查，范围仅为声明的三个计数字段。其他服务保留既有质量保护和 CSV 内部数值验证。
`needs_review` 仍是有结果但待核查，不当作调用失败；新增反馈不提供独立语义判定，`semantic_accuracy` 仍为 null。
模型可在有结果后选择停止，已返回成果会保留；仍不能因此宣称整体任务完成。

## 检查与真实运行

- 58 项 Python 自动检查通过，含 7 项新增反馈边界测试。日志：`logs/feedback-tests-final-20261016.txt`。
- 67 项既有 UI DOM 回放检查通过。日志：`logs/feedback-ui-tests-20261016.txt`。未完成真实浏览器视觉检查。
- 开发真实推理记录：`logs/feedback-smoke-20261016-114227.json`。
  - `(35+13)/6` 和 `17*3-4` 返回 8、47，各次反馈选择继续；包含冷加载共约 36.19 秒。
  - 原文 `The meeting is on Friday. The room is not yet confirmed.` 翻译后计数，反馈两次继续，约 3.19 秒。结果保留“周五”和“尚未确认”，但额外加了“原文翻译：”前缀；计数为实际返回的全部 20 个字符。
  - 未给原文的翻译请求暂停等待输入；除零请求停止。
- 故障注入 + 真实模型选择：`logs/feedback-smoke-20261016-114347.json`。一次文字调用被测试脚本故意抛出异常，模型选择 replan；Qwen 输出重复子任务被程序拒绝，约 14.61 秒后停止。没有恢复成功，也没有伪造交付。
- 上述均为开发记录，不是冻结测试集，不计算准确率。确定性算式参考值与开发者检查的翻译事实不等于独立盲评。
- 日志保留输入、输出、错误、耗时、可用 RAM 及模型返回的资源字段；未测系统功耗，不将进程分配器峰值称为整机资源峰值。

## 运行与复现

在项目目录使用 PowerShell：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node .\tests\ui_replay.cjs
.\.venv\Scripts\python.exe .\verify_feedback.py
.\.venv\Scripts\python.exe .\verify_feedback.py --fault-only
```

工作台：http://127.0.0.1:8765/ 。选择“多步协调”和本地决策。运行后展开“选择与过程”查看执行结果反馈决策。
直接脚本会启动独立推理工作进程；避免和工作台同时运行模型任务，以免争用显存。项目环境仍依赖 D:\Anaconda，不是独立机器镜像。

## 剩余限制与下一步

闭环控制已实现，恢复成功率未建立。模型重规划可能重复、遗漏或改变要求，结构检查不证明需求覆盖；改写/翻译事实性仍需人工核查。
下一步优先约束重规划对未完成原始要求的对应关系，并验证“换服务”是否仍完成原任务，而非用一个可执行的替代任务掩盖失败。
本轮不调冻结测试集、不做规则有效性对比、不降低阈值。

## Git 交接

本轮改动：agent.py、local_models.py、ui.html、tests/test_agent.py；新增 tests/test_feedback.py、verify_feedback.py、本说明及轻量清单。
修改前四个源文件精确字节保留于 evaluation_data/snapshots/pre-feedback-20261016/，历史清单和评价未改写；不是全项目备份。
沿用现有忽略规则排除模型、环境、缓存、日志和私有任务记录。工作区还包含此前 R1 未提交内容，提交前请一并审阅。

建议提交说明：`接通AnyJev执行反馈决策闭环，保留失败与验证边界`

```powershell
git status --short
git diff --stat
git diff --check
git ls-files --others --exclude-standard
```

由用户本人审阅后暂存、提交和推送；本次未执行任何 Git 写操作。
