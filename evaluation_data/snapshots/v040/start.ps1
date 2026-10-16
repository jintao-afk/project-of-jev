param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw '请先运行 setup.ps1 准备项目环境。' }
$taskStatePath = Join-Path $PSScriptRoot 'server.local.json'
$taskExpectedVersion = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json).version
if (Test-Path -LiteralPath $taskStatePath) {
    $taskState = Get-Content -LiteralPath $taskStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $taskExisting = Get-Process -Id $taskState.pid -ErrorAction SilentlyContinue
    if ($taskExisting -and $taskExisting.StartTime.ToUniversalTime().Ticks -eq ([datetime]$taskState.start_time_utc).ToUniversalTime().Ticks) {
        $taskExistingStatus = Invoke-RestMethod -Uri ($taskState.url + '/v1/status') -TimeoutSec 3
        if ($taskExistingStatus.version -eq $taskExpectedVersion) {
            Write-Output ('服务已运行：' + $taskState.url + '，版本 ' + $taskExistingStatus.version)
            return
        }
        throw '登记服务与当前代码版本不一致，请先运行 stop.ps1 后重启。'
    }
}
$env:PYTHONIOENCODING = 'utf-8'
$env:HF_HOME = Join-Path $PSScriptRoot '.cache/huggingface'
$env:XDG_CACHE_HOME = Join-Path $PSScriptRoot '.cache'
$env:TORCH_HOME = Join-Path $PSScriptRoot '.cache/torch'
$env:PIP_CACHE_DIR = Join-Path $PSScriptRoot '.cache/pip'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$taskLogs = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $taskLogs -Force | Out-Null
$taskAppArgument = '"' + (Join-Path $PSScriptRoot 'app.py') + '"'
$taskServer = Start-Process -FilePath $taskPython -ArgumentList @($taskAppArgument,'serve','--port',$Port) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskLogs 'server.stdout.log') -RedirectStandardError (Join-Path $taskLogs 'server.stderr.log') -PassThru
@{pid=$taskServer.Id;start_time_utc=$taskServer.StartTime.ToUniversalTime().ToString('o');url="http://127.0.0.1:$Port"} | ConvertTo-Json | Set-Content -LiteralPath $taskStatePath -Encoding utf8
$taskReady = $false
for ($taskAttempt = 0; $taskAttempt -lt 20; $taskAttempt++) {
    if ($taskServer.HasExited) { throw '项目启动进程已经退出，请检查 logs/server.stderr.log。' }
    try {
        $taskStatus = Invoke-RestMethod -Uri ("http://127.0.0.1:$Port/v1/status") -TimeoutSec 1
        if ($taskStatus.version -eq $taskExpectedVersion) { $taskReady = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (-not $taskReady) { throw '启动未通过版本健康检查；不能把启动入口当成服务已经可用。' }
Write-Output "服务已验证：http://127.0.0.1:$Port；版本 $taskExpectedVersion；停止时运行 stop.ps1。"
