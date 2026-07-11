param(
    [string]$CondaEnv = "intership"
)

$ErrorActionPreference = "Stop"

Write-Host "Installing the optional PyTorch CPU package into conda env: $CondaEnv"
conda run --no-capture-output -n $CondaEnv python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) {
    throw "PyTorch installation failed with exit code $LASTEXITCODE"
}

Write-Host "Verifying PyTorch..."
conda run --no-capture-output -n $CondaEnv python -c "import torch; print('PyTorch', torch.__version__, '| CUDA available:', torch.cuda.is_available())"
