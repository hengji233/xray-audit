#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-../xray-audit}"
REPO_URL="${2:-git@github.com:zcl19/xray-audit.git}"

if [ ! -d "tools/xray_audit" ]; then
  echo "Run this script from Xray-core repository root."
  exit 1
fi

mkdir -p "${TARGET_DIR}"
rsync -av --delete tools/xray_audit/ "${TARGET_DIR}/"

cd "${TARGET_DIR}"
if [ ! -d .git ]; then
  git init
  git branch -M main
fi

git add .
if ! git diff --cached --quiet; then
  git commit -m "chore: bootstrap xray-audit from tools/xray_audit snapshot"
fi

git remote remove origin >/dev/null 2>&1 || true
git remote add origin "${REPO_URL}"

echo "Snapshot prepared at ${TARGET_DIR}."
echo "Next: git push -u origin main"
