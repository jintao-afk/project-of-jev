# 阶段版本管理

每完成一个可验收阶段，先报告修改、验证结果和遗留问题，再整理提交范围与建议说明。由用户本人使用自己的 Git 账号提交和推送；助手不代为暂存、提交、打标签或配置账号与远端。当前默认采用 Git 阶段版本，不另行复制整个项目。

Git 跟踪代码、配置、测试、文档、模型锁定清单和版本化评价数据。模型权重、环境、缓存、原始日志、旧修复备份和生成的 ZIP 不纳入 Git，它们继续保存在 D 盘原位置。历史修复备份保留。

`.gitattributes`关闭换行转换，保持脚本BOM与冻结评价所需的原始字节。模型锁定清单和依赖版本清单属于轻量元数据，可随代码提交。

本地提交用于检查改动和回退代码，仍保存在本机。只有在用户授权并配置远端后才推送；本阶段不创建远端仓库、不上传项目。额外的完整文件备份按明确需求另行处理。

常用只读检查：`git status`、`git log --oneline -5`、`git show --stat HEAD`。恢复代码前应先保留当前改动；不要使用未经确认的强制重置或清理命令，也不要为复现旧评价覆盖其冻结清单。

## 已保存基线与本阶段交接

用户已将首个提交`7abcec5`推送到`https://github.com/jintao-afk/project-of-jev.git`，当前分支`main`跟踪`origin/main`。账号、暂存、提交与推送继续由用户本人操作。下面首次提交说明保留为历史记录。

当前工作区已推进至离线研究初版R1（v0.6.0），包含此前v0.4.0/v0.5.0改进及统一CSV调用、阶段报告、历史和续接。助手尚未代用户提交。建议提交说明：`交付Jev离线研究初版R1，统一调用与报告续接`。evaluation_data/snapshots/v040和v050分别保存19份与20份轻量源码证据及清单，用于保留旧评价对应字节，不含模型或环境，也不是完整项目备份。提交前检查`git diff --stat`和`git diff --cached --stat`，仅保留白名单demo资料；workspace中的个人输入、运行输出及持久任务历史已忽略。不要重复初始化仓库或重新配置远端。

## 首次提交记录

建议说明：`保存离线框架v0.3.1及Windows启动兼容修复`。

主要内容：离线决策与调用框架、任务契约和有限结果保护、阶段评价数据与报告、工作台、PowerShell 5.1启动修复及针对性测试。报告同时保留真实失败和评价局限，不能把本次提交当作质量全部通过。

首次提交前曾建立空Git目录，助手的暂存/提交请求未获准。后由用户本人完成提交和远端配置。日常操作前请用`git status`确认实际状态。

在自己的PowerShell或Git Bash中进入项目，检查后提交：

```powershell
cd 'D:\1 jev\jev-edge-prototype'
git status
git add .
git diff --cached --stat
git commit -m "保存离线框架v0.3.1及Windows启动兼容修复"
```

检查暂存清单时，`models`下应只有`models/model-lock.json`；模型权重、`.venv`、`.cache`、`logs`、`.repair-backups`和ZIP不应出现。远端推送请使用你自己的仓库地址和分支，先用`git remote -v`、`git branch --show-current`核对，不假定项目已经连接你的Git账号或仓库。

原始运行日志不入Git，测试与依据标注仍可能引用当前D盘日志中的记录；Git代码快照不是包含权重和全部实验输入输出的独立安装包。现有原始记录继续保留在本机。

本阶段可复核命令：

```powershell
git status
git diff --stat
git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check
git ls-files --others --exclude-standard workspace
```

最后一项应只列白名单demo资料。CRLF检查选项仅作用于本次命令，不修改Git配置或文件换行。确认范围后由用户本人暂存、提交和推送。
