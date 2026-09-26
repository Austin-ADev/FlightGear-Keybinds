# Construit dist\FGKeybinds.exe (exécutable autonome Windows).
# Usage : powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m pip install -r requirements-dev.txt
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Les tests ont échoué" }
python tools\make_icon.py
python -m PyInstaller --noconfirm --clean FGKeybinds.spec
if ($LASTEXITCODE -ne 0) { throw "La construction a échoué" }
Write-Host "Exécutable : $PSScriptRoot\dist\FGKeybinds.exe"
