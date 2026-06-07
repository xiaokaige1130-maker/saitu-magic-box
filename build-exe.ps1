Set-Location $PSScriptRoot

$appName = "晒图魔方"

python -m pip install -r requirements.txt
python -m pip install pyinstaller

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --name $appName `
  --add-data "app\templates;app\templates" `
  --add-data "app\static;app\static" `
  launcher.py

Write-Host "EXE: $PSScriptRoot\dist\$appName\$appName.exe"
