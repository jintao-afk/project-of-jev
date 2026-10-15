# 2026-10-15 · Windows 双击入口兼容修复

已修复原项目中的 `打开工作台.cmd`、`open.ps1`、`start.ps1`。保持 v0.3.1 决策实现与模型不变；完全离线，所有改动、日志和备份在 D 盘。

## 实际原因

1. CMD 调用系统自带 Windows PowerShell 5.1。新增的 open.ps1 是无 BOM 的 UTF-8 中文脚本，5.1 按本地 ANSI 解码，实际复现了字符串未终止、缺少括号等语法错误。之前仅在 PowerShell 7 下做语法检查，遗漏了真正双击使用的宿主兼容性。
2. 修正脚本编码后，继续复现 start.ps1 用未指定编码的 Get-Content 读取 config.json。5.1 同样将中文主题字段误解码，ConvertFrom-Json 报 Invalid array passed in。配置文件本身有效，不需要改模型或重装。
3. 原 CMD 没有处理 PowerShell 解析失败的退出码，因此错误窗口可能直接关闭，用户看不到原因。

## 修复

- open.ps1 使用 UTF-8 BOM；CMD 使用 ASCII 内容和 CRLF，并明确调用 Windows 系统 PowerShell。
- start.ps1 读取配置与服务登记文件时显式使用 UTF8，不改变 config.json 内容。
- CMD 在失败时显示日志位置并暂停；open.ps1 将宿主版本、开始、健康检查与异常追加到 logs/launcher.log。
- 增加 -CheckOnly，仅验证服务启动和健康检查，不触发浏览器导航。正常双击仍在服务就绪后请求默认浏览器打开工作台。

## 真实验证

采用 Windows PowerShell **5.1.26100.9711**，不是 PowerShell 7：

- 已运行服务时，实际 CMD → Windows PowerShell 5.1 → open.ps1 → start.ps1 链路通过。
- 归档服务日志，停止本项目已登记服务，再从同一 CMD 入口重新启动；6项回归检查通过。
- 页面 HTTP 200，状态接口确认 v0.3.1、offline_mode=true。
- 记录：logs/launcher-validation-20261015-123828.json；测试：tests/test_windows_launcher.ps1。
- 测试采用 -CheckOnly，没有自动打开浏览器，也没有做浏览器视觉验收。没有通过其他浏览器或间接执行绕过先前浏览器工具的本机 URL 策略拒绝。

复现方式（项目根目录）：

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\tests\test_windows_launcher.ps1 -Restart
```

日常使用直接双击 `打开工作台.cmd`。失败窗口现在会停留，具体异常同时保存在 `logs/launcher.log`。

## 历史与冻结

修改前文件保存在 `.repair-backups/launcher-fix-20261015-123647`。原研究评价、标注、release-v031.json 和旧交付包保持原样。

本补丁改变冻结清单中的三个启动文件，严格的原 v0.3.1 留出复现会因此提示哈希不匹配；不得重写旧冻结清单掩盖变化。若要精确复现历史快照，可保留现补丁后临时恢复上述三个备份，完成后恢复补丁。此次没有更改 core.py、local_models.py、task_contract.py、answer_quality.py、config.json 或 ui.html，不能把启动修复当作模型质量提升。

原完整更新包中的入口仍是历史版本；需要重新分发时，应同时应用 `jev-v0.3.1-launcher-fix-20261015.zip`。当前项目已经直接修复，不需要再次解压或安装。
