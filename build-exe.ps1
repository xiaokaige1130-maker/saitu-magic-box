Set-Location $PSScriptRoot

$appName = "筛图魔术盒"

python -m pip install -r requirements.txt
python -m pip install pyinstaller

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --windowed `
  --name $appName `
  launcher.py

Write-Host "EXE: $PSScriptRoot\dist\$appName\$appName.exe"
