param(
    [string]$CondaEnv = "intership",
    [string]$Config = "config\settings.yaml",
    [switch]$EnableLstm,
    [int]$LstmEpochs = 20,
    [int]$LstmWindow = 28,
    [int]$LstmBatchSize = 128,
    [switch]$LstmNoBatchProgress,
    [switch]$BuildOnly
)

$ErrorActionPreference = "Stop"

Write-Host "Using conda env: $CondaEnv"
Write-Host "Tip: the environment name is 'intership', not 'inter'. You can also run without activating it."

conda run --no-capture-output -n $CondaEnv python -c "import sys; print(sys.executable)" | Out-Host

if ($EnableLstm) {
    Write-Host "Checking optional PyTorch LSTM dependency..."
    conda run --no-capture-output -n $CondaEnv python -c "import torch; print('PyTorch', torch.__version__, '| CUDA available:', torch.cuda.is_available())" | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "PyTorch is not installed, so LSTM cannot train." -ForegroundColor Red
        Write-Host "Install the Windows CPU build with:"
        Write-Host "conda run --no-capture-output -n $CondaEnv python -m pip install torch --index-url https://download.pytorch.org/whl/cpu"
        exit 1
    }
}

Write-Host "[1/2] Build real local serving JSON from raw CSV files"
$buildArgs = @(
    "scripts\build_local_serving_from_raw.py",
    "--config", $Config
)
if ($EnableLstm) {
    $buildArgs += @(
        "--lstm",
        "--lstm-epochs", $LstmEpochs,
        "--lstm-window", $LstmWindow,
        "--lstm-batch-size", $LstmBatchSize
    )
    if ($LstmNoBatchProgress) {
        $buildArgs += "--lstm-no-batch-progress"
    }
}
conda run --no-capture-output -n $CondaEnv python @buildArgs
if ($LASTEXITCODE -ne 0) {
    throw "Local data/model pipeline failed with exit code $LASTEXITCODE"
}

if ($BuildOnly) {
    Write-Host "Build finished. Start the web app later with:"
    Write-Host "conda run -n $CondaEnv python -m src.web.app"
    exit 0
}

$portOpen = Test-NetConnection -ComputerName 127.0.0.1 -Port 5000 -InformationLevel Quiet
if ($portOpen) {
    Write-Host "[2/2] Flask already appears to be running."
    Write-Host "Open http://127.0.0.1:5000"
    exit 0
}

Write-Host "[2/2] Start Flask web app at http://127.0.0.1:5000"
conda run --no-capture-output -n $CondaEnv python -m src.web.app
