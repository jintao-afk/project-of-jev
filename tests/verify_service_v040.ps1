param([string]$BaseUrl = 'http://127.0.0.1:8765')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskStatus = Invoke-RestMethod -Uri ($BaseUrl + '/v1/status') -TimeoutSec 5
if ($taskStatus.version -ne '0.4.0' -or -not $taskStatus.offline_mode) { throw 'Expected offline v0.4.0 service.' }
$taskPage = Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + '/') -TimeoutSec 5
$taskRequest = Get-Content -LiteralPath (Join-Path $taskRoot 'examples/workflow_demo.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$taskRequest | Add-Member -NotePropertyName backend -NotePropertyValue anyjev
$taskBody = [Text.Encoding]::UTF8.GetBytes(($taskRequest | ConvertTo-Json -Depth 10))
$taskReport = Invoke-RestMethod -Uri ($BaseUrl + '/v1/run') -Method Post -ContentType 'application/json; charset=utf-8' -Body $taskBody -TimeoutSec 300
if (-not $taskReport.task_complete -or $taskReport.remote_attempts -ne 0) { throw ('Real workflow did not deliver: ' + $taskReport.reason) }
$taskJson = Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + '/v1/artifacts/' + $taskReport.run_id + '/report.json') -TimeoutSec 5
$taskArtifact = $taskJson.Content | ConvertFrom-Json
if ($taskArtifact.statistics.'baseline.csv'.rows -ne 16 -or $taskArtifact.statistics.'current.csv'.rows -ne 16 -or $taskArtifact.semantic_verified -ne $false) { throw 'Downloaded artifact contract mismatch.' }
$taskMarkdown = Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + '/v1/artifacts/' + $taskReport.run_id + '/report.md') -TimeoutSec 5
if ($taskMarkdown.StatusCode -ne 200 -or -not $taskMarkdown.Headers['Content-Disposition']) { throw 'Artifact download headers missing.' }
$taskFile = Join-Path $taskRoot ('workspace/runs/' + $taskReport.run_id + '/report.md')
if ($taskReport.run_id -notmatch '^[a-f0-9]{32}$') { throw 'Unexpected run identifier.' }
$taskOriginal = [IO.File]::ReadAllBytes($taskFile)
$taskTamperRefused = $false
try {
    [IO.File]::WriteAllBytes($taskFile, [Text.Encoding]::UTF8.GetBytes('changed-after-delivery'))
    try { Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + '/v1/artifacts/' + $taskReport.run_id + '/report.md') -TimeoutSec 5 | Out-Null }
    catch { $taskTamperRefused = [int]$_.Exception.Response.StatusCode -eq 409 }
} finally { [IO.File]::WriteAllBytes($taskFile, $taskOriginal) }
if (-not $taskTamperRefused) { throw 'Changed artifact was not refused.' }
$taskCalc = [Text.Encoding]::UTF8.GetBytes(' {"goal":"计算 (21+15)/6","backend":"anyjev","validation":{"expected_value":6}} ')
$taskCalcReport = Invoke-RestMethod -Uri ($BaseUrl + '/v1/run') -Method Post -ContentType 'application/json; charset=utf-8' -Body $taskCalc -TimeoutSec 120
if ($taskCalcReport.result.value -ne 6 -or -not $taskCalcReport.task_complete) { throw 'Existing single-call calculator regressed.' }
$taskResult = @{verified_at_utc=[DateTime]::UtcNow.ToString('o');version=$taskStatus.version;homepage_status=[int]$taskPage.StatusCode;offline=$taskStatus.offline_mode;workflow_request=$taskRequest;workflow_report=$taskReport;artifact_json_status=[int]$taskJson.StatusCode;artifact_markdown_status=[int]$taskMarkdown.StatusCode;tampered_artifact_refused=$taskTamperRefused;single_call_report=$taskCalcReport;browser_visual_check='not performed'}
$taskTarget = Join-Path $taskRoot ('reports/service-check-v040-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json')
$taskResult | ConvertTo-Json -Depth 70 | Set-Content -LiteralPath $taskTarget -Encoding UTF8
Write-Output ('PASS: real offline workflow, both artifact downloads, single-call calculator; ' + $taskTarget)
