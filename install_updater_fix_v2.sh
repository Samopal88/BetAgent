#!/usr/bin/env bash
set -e
cd /root/betagent

cp updater_results.py updater_results.py.bak.$(date +%Y%m%d_%H%M%S)
cp updater_results.py.fixed.v2 updater_results.py

python3 -m py_compile updater_results.py
echo "OK: updater_results.py v2 installed"

echo
echo "Run now:"
echo "  cd /root/betagent && python3 updater_results.py --settle"
