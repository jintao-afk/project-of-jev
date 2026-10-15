# Run with Windows PowerShell 5.1, the same host used by the CMD launcher.
param([switch]$Restart)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskChecks = @()
if ($PSVersionTable.PSVersion.Major -ne 5) { throw 'Run this regression using powershell.exe (Windows PowerShell 5.1).' }
$taskBom = [IO.File]::ReadAllBytes((Join-Path $taskRoot 'open.ps1'))
if ($taskBom[0] -ne 239 -or $taskBom[1] -ne 187 -or $taskBom[2] -ne 191) { throw 'open.ps1 must be UTF-8 with BOM for Windows PowerShell 5.1.' }
$taskChecks += 'UTF-8 BOM present'
foreach ($taskName in @('open.ps1','start.ps1','stop.ps1')) {
    $taskErrors = $null
    [Management.Automation.Language.Parser]::ParseFile((Join-Path $taskRoot $taskName),[ref]$null,[ref]$taskErrors) | Out-Null
    if ($taskErrors.Count) { throw ($taskName + ': ' + ($taskErrors | Out-String)) }
}
$taskChecks += 'PowerShell 5.1 syntax valid'
$taskConfiguration = Get-Content -LiteralPath (Join-Path $taskRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $taskConfiguration.version -or -not $taskConfiguration.offline_mode) { throw 'Expected offline project configuration.' }
$taskChecks += 'UTF-8 JSON readable'
if ($Restart) {
    $taskArchive = Join-Path $taskRoot ('logs/server-archives/launcher-check-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    New-Item -ItemType Directory -Path $taskArchive -Force | Out-Null
    foreach ($taskFile in @('logs/server.stdout.log','logs/server.stderr.log','server.local.json')) {
        $taskOriginal = Join-Path $taskRoot $taskFile
        if (Test-Path -LiteralPath $taskOriginal) { Copy-Item -LiteralPath $taskOriginal -Destination $taskArchive }
    }
    & (Join-Path $taskRoot 'stop.ps1')
    $taskChecks += 'Registered service stopped; logs archived'
}
$taskCmd = Join-Path $taskRoot '打开工作台.cmd'
& $env:ComSpec /d /c ('call "' + $taskCmd + '" -CheckOnly')
if ($LASTEXITCODE -ne 0) { throw ('CMD launcher returned ' + $LASTEXITCODE) }
$taskChecks += 'Actual CMD to Windows PowerShell to start.ps1 chain succeeded'
$taskStatus = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/v1/status' -TimeoutSec 5
$taskPage = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8765/' -TimeoutSec 5
if ($taskStatus.version -ne $taskConfiguration.version -or -not $taskStatus.offline_mode -or $taskPage.StatusCode -ne 200) { throw 'Service health mismatch.' }
$taskChecks += 'HTTP 200, expected version, offline mode'
$taskResult = [ordered]@{
    verified_at_utc=[DateTime]::UtcNow.ToString('o');powershell_version=$PSVersionTable.PSVersion.ToString();
    restarted=[bool]$Restart;checks=$taskChecks;homepage_status=[int]$taskPage.StatusCode;
    version=$taskStatus.version;offline_mode=$taskStatus.offline_mode;
    browser_open='not exercised; CheckOnly verifies launch without browser navigation'
}
$taskOutput = Join-Path $taskRoot ('logs/launcher-validation-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json')
$taskResult | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $taskOutput -Encoding UTF8
Write-Output ('PASS: ' + $taskChecks.Count + ' launcher checks; ' + $taskOutput)
