#!/usr/bin/env bash
#
# Deploy the latest code to this machine (e.g. PythonAnywhere).
# Usage:  bash deploy.sh
#
# Run this in a PythonAnywhere Bash console, then press Reload in the Web tab
# (or let the GitHub Actions workflow do both automatically).
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Pulling latest code from GitHub"
git fetch origin master
git reset --hard origin/master

echo "==> Ensuring schema is up to date is automatic on app start (wsgi.py)"
echo "==> Done. Now click Reload in the PythonAnywhere Web tab."
