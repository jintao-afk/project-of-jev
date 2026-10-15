$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskStatus = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/v1/status' -TimeoutSec 5
if ($taskStatus.version -ne '0.3.1' -or -not $taskStatus.offline_mode) { throw '本机服务不是预期离线版本。' }
$taskPage = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/' -TimeoutSec 5
$taskRequests = @(
    @{goal='计算 (21+15)/6';backend='anyjev';allow_remote=$false;network_available=$false;validation=@{expected_value=6}},
    @{goal='润色为简洁通知。';input='讲座推迟至周六。原因未提供。';backend='anyjev';allow_remote=$false;network_available=$false}
)
$taskRows = @()
foreach ($taskRequest in $taskRequests) {
    $taskBody = [Text.Encoding]::UTF8.GetBytes(($taskRequest | ConvertTo-Json -Depth 10))
    $taskResult = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/v1/run' -Method Post -ContentType 'application/json; charset=utf-8' -Body $taskBody -TimeoutSec 180
    if ($taskResult.remote_attempts -ne 0 -or -not $taskResult.task_contract) { throw '离线或契约集成检查失败。' }
    $taskRows += @{request=$taskRequest;response=$taskResult}
}
if ($taskRows[0].response.result.value -ne 6 -or -not $taskRows[0].response.task_complete) { throw '真实接口计算检查失败。' }
if ($taskRows[1].response.status -ne 'needs_review') { throw '普通文字结果不应被计为完整语义完成。' }
$taskRecord = @{
    verified_at_utc=[DateTime]::UtcNow.ToString('o');url='http://127.0.0.1:8765/';
    version=$taskStatus.version;offline_mode=$taskStatus.offline_mode;
    decision_model_ready=$taskStatus.decision_model_ready;retrieval_model_ready=$taskStatus.retrieval_model_ready;
    homepage_status=[int]$taskPage.StatusCode;current_ui_served=$taskPage.Content.Contains('本次任务要求与检查');
    mode='real HTTP integration smoke; not browser visual QA or independent quality sample';runs=$taskRows
}
$taskTarget = Join-Path $taskRoot ('reports/service-check-v031-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json')
$taskRecord | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $taskTarget -Encoding utf8
Write-Output ('真实接口检查通过，页面HTTP ' + $taskPage.StatusCode + '，版本 ' + $taskStatus.version + '，远端调用0。')
Write-Output $taskTarget
