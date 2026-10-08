<#
.SYNOPSIS
  Campaign Edit —— 本地一键启动（Windows）

.EXAMPLE
  .\scripts\dev.ps1              同时启动前后端
  .\scripts\dev.ps1 -Mode backend 只启动后端
  .\scripts\dev.ps1 -Mode test    跑端到端冒烟测试
#>
[CmdletBinding()]
param(
  [ValidateSet('all', 'backend', 'frontend', 'test')]
  [string]$Mode = 'all'
)

$ErrorActionPreference = 'Stop'
$Root   = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'

function Get-Python {
  $candidates = @(
    (Join-Path $Backend '.venv\Scripts\python.exe'),
    (Join-Path $Backend '.venv\bin\python')
  )
  foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
  foreach ($c in @('python', 'python3')) {
    if (Get-Command $c -ErrorAction SilentlyContinue) { return $c }
  }
  throw '找不到 Python，请先安装 Python 3.11+'
}

function Initialize-Backend {
  $py = Join-Path $Backend '.venv\Scripts\python.exe'
  if (-not (Test-Path $py)) {
    Write-Host '==> 创建后端虚拟环境' -ForegroundColor Cyan
    & (Get-Python) -m venv (Join-Path $Backend '.venv')
    & $py -m pip install -r (Join-Path $Backend 'requirements.txt')
  }
  return $py
}

function Wait-ForApi {
  Write-Host '==> 等待后端就绪' -ForegroundColor Cyan
  for ($i = 0; $i -lt 40; $i++) {
    try {
      $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/v1/health' `
           -UseBasicParsing -TimeoutSec 3
      if ($r.StatusCode -eq 200) {
        Write-Host '    后端就绪: http://127.0.0.1:8000/docs' -ForegroundColor Green
        return $true
      }
    } catch { }
    Start-Sleep -Seconds 2
  }
  Write-Host '    后端启动超时' -ForegroundColor Red
  return $false
}

function Start-Backend {
  $py = Initialize-Backend
  Set-Location $Backend
  & $py -m uvicorn app.main:app --reload --port 8000
}

function Start-Frontend {
  Set-Location $Frontend
  if (-not (Test-Path 'node_modules')) {
    Write-Host '==> 安装前端依赖' -ForegroundColor Cyan
    npm install
  }
  npm run dev
}

switch ($Mode) {
  'backend'  { Start-Backend }
  'frontend' { Start-Frontend }
  'test'     {
    $py = Initialize-Backend
    Set-Location $Backend
    & $py scripts/smoke_test.py
  }
  'all' {
    $py = Initialize-Backend
    Write-Host '==> 启动后端（后台）' -ForegroundColor Cyan
    $job = Start-Job -ScriptBlock {
      param($dir, $python)
      Set-Location $dir
      & $python -m uvicorn app.main:app --reload --port 8000
    } -ArgumentList $Backend, $py

    if (-not (Wait-ForApi)) {
      Receive-Job $job
      Stop-Job $job; Remove-Job $job
      exit 1
    }

    Write-Host ''
    Write-Host '后端: http://127.0.0.1:8000/docs' -ForegroundColor Green
    Write-Host '前端: http://127.0.0.1:5173' -ForegroundColor Green
    Write-Host ''

    try { Start-Frontend }
    finally {
      Stop-Job $job -ErrorAction SilentlyContinue
      Remove-Job $job -Force -ErrorAction SilentlyContinue
    }
  }
}