#!/usr/bin/env bash
set -e
cd /root/betagent

cp run_pipeline.py run_pipeline.py.bak.$(date +%Y%m%d_%H%M%S)
cp run_pipeline.py.fixed.v3 run_pipeline.py

python3 -m py_compile run_pipeline.py

touch .env
grep -q '^ENABLE_SETTLE=' .env || echo 'ENABLE_SETTLE=1' >> .env
grep -q '^ENABLE_NOTIFY=' .env || echo 'ENABLE_NOTIFY=1' >> .env
grep -q '^ENABLE_CLV=' .env || echo 'ENABLE_CLV=1' >> .env
grep -q '^ENABLE_SHADOW_FOOTBALL=' .env || echo 'ENABLE_SHADOW_FOOTBALL=1' >> .env
grep -q '^ENABLE_SHADOW_HOCKEY=' .env || echo 'ENABLE_SHADOW_HOCKEY=0' >> .env

echo "OK: run_pipeline.py v3 installed"
echo
echo "Now test:"
echo "  cd /root/betagent && python3 run_pipeline.py --run afternoon"
echo
echo "Flags in .env:"
echo "  ENABLE_SETTLE=1"
echo "  ENABLE_NOTIFY=1"
echo "  ENABLE_CLV=1"
echo "  ENABLE_SHADOW_FOOTBALL=1"
echo "  ENABLE_SHADOW_HOCKEY=0"
