param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$taskLauncherFolder = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $taskLauncherFolder -Force | Out-Null
$taskLauncherLog = Join-Path $taskLauncherFolder 'launcher.log'
$taskUrl = 'http://127.0.0.1:8765/'
function Write-LauncherLog([string]$Message) {
    Add-Content -LiteralPath $taskLauncherLog -Encoding UTF8 -Value ('[' + [DateTimeOffset]::Now.ToString('o') + '] ' + $Message)
}
$taskLocationPushed = $false
try {
    Write-LauncherLog ('Starting launcher; PowerShell=' + $PSVersionTable.PSVersion + '; check_only=' + $CheckOnly)
    Push-Location -LiteralPath $PSScriptRoot
    $taskLocationPushed = $true
    & (Join-Path $PSScriptRoot 'start.ps1')
    Write-LauncherLog ('Service health check succeeded: ' + $taskUrl)
    if ($CheckOnly) {
        Write-Output '启动检查通过；检查模式未打开浏览器。'
    } else {
        Start-Process -FilePath $taskUrl -ErrorAction Stop
        Write-LauncherLog 'Requested default browser to open the local workbench.'
    }
} catch {
    try { Write-LauncherLog ('ERROR: ' + $_.Exception.ToString() + ' | ' + $_.ScriptStackTrace) } catch { }
    Write-Host ('工作台未能打开：' + $_.Exception.Message)
    Write-Host ('启动日志：' + $taskLauncherLog)
    Write-Host '服务日志：项目 logs/server.stderr.log；无需重新安装模型。'
    exit 1
} finally {
    if ($taskLocationPushed) { Pop-Location }
}
