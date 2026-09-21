#!/usr/bin/env bash
set -e
cd /root/betagent

cp updater_results.py updater_results.py.bak.$(date +%Y%m%d_%H%M%S)
cp updater_results.py.fixed updater_results.py

python3 -m py_compile updater_results.py
echo "OK: updater_results.py fixed installed"

echo
echo "Run:"
echo "  python3 updater_results.py --settle"
