param(
    [string]$CondaRoot = "$env:LOCALAPPDATA\miniconda3",
    [string]$EnvName = "aligner"
)

$ErrorActionPreference = "Stop"

$installer = Join-Path $env:TEMP "Miniconda3-latest-Windows-x86_64.exe"
$condaExe = Join-Path $CondaRoot "Scripts\conda.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    & $condaExe @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $condaExe $($Args -join ' ')"
    }
}

if (-not (Test-Path $condaExe)) {
    Write-Host "Downloading Miniconda installer..."
    Invoke-WebRequest `
        -Uri "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe" `
        -OutFile $installer

    Write-Host "Installing Miniconda to $CondaRoot ..."
    Start-Process `
        -FilePath $installer `
        -ArgumentList "/InstallationType=JustMe", "/RegisterPython=0", "/S", "/D=$CondaRoot" `
        -Wait
}

if (-not (Test-Path $condaExe)) {
    throw "conda.exe was not found after Miniconda installation."
}

$envExists = & $condaExe env list | Select-String -Pattern "^\s*$EnvName\s"
if (-not $envExists) {
    Write-Host "Creating Conda environment '$EnvName' ..."
    Invoke-Checked -Args @("create", "-y", "-n", $EnvName, "--override-channels", "-c", "conda-forge", "python=3.11")
}

Write-Host "Installing phonomenal optional alignment dependencies ..."
Invoke-Checked -Args @("run", "-n", $EnvName, "python", "-m", "pip", "install", "--upgrade", "pip")
Invoke-Checked -Args @("run", "-n", $EnvName, "python", "-m", "pip", "install", "-e", ".[align]")

Write-Host "Installing Montreal Forced Aligner ..."
Invoke-Checked -Args @("install", "-y", "-n", $EnvName, "--override-channels", "-c", "conda-forge", "montreal-forced-aligner")

Write-Host "Downloading MFA acoustic model english_us_arpa ..."
Invoke-Checked -Args @("run", "-n", $EnvName, "mfa", "model", "download", "acoustic", "english_us_arpa")

Write-Host ""
Write-Host "Bootstrap complete."
Write-Host "Use this MFA command for the CLI:"
Write-Host "$condaExe run -n $EnvName mfa"
