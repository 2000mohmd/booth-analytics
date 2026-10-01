<# Run the stack natively (no Docker/WSL VM). Same code, same models, same thresholds.
   .\scripts\run-native.ps1 setup [-Gpu]   one-time: venv + deps (+ dashboard npm install)
   .\scripts\run-native.ps1 start [-MaxFps 3] [-Cpu]   start services (-Cpu uses configs/models.local.yaml)
   .\scripts\run-native.ps1 stop #>
param([Parameter(Mandatory)][ValidateSet('setup','start','stop')]$Action, [switch]$Gpu, [switch]$Cpu, [double]$MaxFps = 0)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot)
$py = '.venv\Scripts\python.exe'; $pids = 'data\native.pids'

switch ($Action) {
  'setup' {
    if (-not (Test-Path $py)) { python -m venv .venv }
    # requirements.txt pins onnxruntime-gpu for the Docker/CUDA image; a non-NVIDIA machine needs the CPU wheel.
    $req = Get-Content requirements.txt | Where-Object { $_ -notmatch '^onnxruntime-gpu' -or $Gpu }
    if (-not $Gpu) { $req += 'onnxruntime' }
    $req += 'onnx<2', 'onnxslim'   # needed by export_models.py; ultralytics' own auto-install can hang
    $req | Set-Content data\requirements.native.txt
    & $py -m pip install -r data\requirements.native.txt
    if (-not (Test-Path configs\booth.yaml)) { Copy-Item configs\booth.example.yaml configs\booth.yaml }
    if (-not (Test-Path models\yolov8n.onnx)) { & $py scripts\export_models.py }
    Push-Location services\dashboard; npm install; Pop-Location
  }
  'start' {
    if (Test-Path $pids) { Write-Error 'already running - run stop first' }
    New-Item -ItemType Directory -Force data\logs | Out-Null
    $env:PYTHONPATH = (Get-Location).Path
    if ($Cpu) { $env:MODELS_CONFIG = 'configs/models.local.yaml' }
    if ($MaxFps -gt 0) { $env:MAX_FPS = $MaxFps }
    $procs = @(
      @('metrics_engine', $py, '-m services.metrics_engine.main'),
      @('api',            $py, '-m uvicorn services.api.main:app --host 127.0.0.1 --port 8000'),
      @('alerting',       $py, '-m services.alerting.main'),
      @('ingestion',      $py, '-m services.ingestion.main'),
      @('dashboard',      'npm.cmd', 'run dev --prefix services/dashboard')
    ) | ForEach-Object {
      (Start-Process $_[1] $_[2] -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput "data\logs\$($_[0]).out.log" -RedirectStandardError "data\logs\$($_[0]).err.log").Id
    }
    $procs | Set-Content $pids
    'Started. Dashboard: http://localhost:5173  API: http://localhost:8000  Logs: data\logs'
  }
  'stop' {
    if (Test-Path $pids) {
      Get-Content $pids | ForEach-Object { cmd /c "taskkill /PID $_ /T /F >nul 2>&1" }
      Remove-Item $pids
    }
  }
}
