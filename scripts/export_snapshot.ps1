param(
  [string]$TargetDir = "..\xray-audit",
  [string]$RemoteUrl = "git@github.com:zcl19/xray-audit.git"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path "tools/xray_audit")) {
  throw "Run this script from Xray-core repository root."
}

New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

if (Get-Command rsync -ErrorAction SilentlyContinue) {
  rsync -av --delete "tools/xray_audit/" "$TargetDir/"
} else {
  robocopy "tools\xray_audit" $TargetDir /MIR | Out-Null
}

Push-Location $TargetDir
try {
  if (-not (Test-Path ".git")) {
    git init
    git branch -M main
  }

  git add .
  git diff --cached --quiet
  if ($LASTEXITCODE -ne 0) {
    git commit -m "chore: bootstrap xray-audit from tools/xray_audit snapshot"
  }

  git remote remove origin 2>$null
  git remote add origin $RemoteUrl

  Write-Host "Snapshot prepared at $TargetDir"
  Write-Host "Next: git push -u origin main"
}
finally {
  Pop-Location
}
