$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectDir
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "Install uv first." }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "Install ffmpeg first." }
uv venv --python 3.11 .venv-vcpack
if ($LASTEXITCODE) { throw "Could not create Python environment" }
uv pip install --python .venv-vcpack/Scripts/python.exe -e ".[builder]"
if ($LASTEXITCODE) { throw "Could not install builder" }
New-Item -ItemType Directory -Force .tools/micromamba | Out-Null
if (-not (Test-Path .tools/micromamba/Library/bin/micromamba.exe)) {
    Invoke-WebRequest https://micro.mamba.pm/api/micromamba/win-64/2.9.0 -OutFile .tools/micromamba.tar.bz2
    tar -xjf .tools/micromamba.tar.bz2 -C .tools/micromamba Library/bin/micromamba.exe
    if ($LASTEXITCODE) { throw "Could not extract micromamba" }
}
$Mamba = Join-Path $ProjectDir '.tools/micromamba/Library/bin/micromamba.exe'
& $Mamba create -y -r "$ProjectDir/.tools/mamba" -p "$ProjectDir/.tools/aligner" -c conda-forge python=3.11 montreal-forced-aligner=3.3.9
if ($LASTEXITCODE) { throw "Could not create aligner environment" }
foreach ($Kind in @('acoustic', 'dictionary', 'g2p')) {
    & $Mamba run -p "$ProjectDir/.tools/aligner" python "$ProjectDir/scripts/mfa_entry.py" model download $Kind english_us_arpa
    if ($LASTEXITCODE) { throw "Could not download $Kind model" }
}
Write-Host 'Ready. Launch phonomenal_splicer_frontend.exe --builder.'
