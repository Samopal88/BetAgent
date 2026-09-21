#!/usr/bin/env bash
set -e
cd /root/betagent

cp agent_handoff_v7.py agent_handoff_v7.py.bak.$(date +%Y%m%d_%H%M%S)
cp agent_handoff_v7.py.fixed agent_handoff_v7.py

python3 -m py_compile agent_handoff_v7.py
echo "OK: anti-duplicate guard installed"
