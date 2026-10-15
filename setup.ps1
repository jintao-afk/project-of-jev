param([switch]$DownloadModels, [ValidateSet('huggingface','modelscope')][string]$ModelSource='huggingface')
$ErrorActionPreference = 'Stop'
$taskProject = $PSScriptRoot
$taskPython = 'D:/Anaconda/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = (Get-Command python -ErrorAction Stop).Source }
$taskEnvPython = Join-Path $taskProject '.venv/Scripts/python.exe'
$env:PIP_CACHE_DIR = Join-Path $taskProject '.cache/pip'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:HF_HOME = Join-Path $taskProject '.cache/huggingface'
$env:XDG_CACHE_HOME = Join-Path $taskProject '.cache'
$env:TORCH_HOME = Join-Path $taskProject '.cache/torch'
if (-not (Test-Path -LiteralPath $taskEnvPython)) {
    & $taskPython -m venv --system-site-packages (Join-Path $taskProject '.venv')
    if ($LASTEXITCODE -ne 0) { throw '创建项目环境失败。' }
}
# Reuse the installed CUDA-enabled torch without modifying the Anaconda environment.
& $taskEnvPython -m pip install --no-deps 'anyjev==0.3.0'
if ($LASTEXITCODE -ne 0) { throw '安装 AnyJev 失败。' }
& $taskEnvPython (Join-Path $taskProject 'record_environment.py')
if ($LASTEXITCODE -ne 0) { throw '依赖准备状态不满足初版要求。' }
if ($DownloadModels) {
    & $taskEnvPython (Join-Path $taskProject 'download_models.py') --source $ModelSource
    if ($LASTEXITCODE -ne 0) { throw '模型下载未完成。再次运行可以续传。' }
}
Write-Output '准备完成。用 start.ps1 打开本机服务；首次推理尚需运行确认。'
