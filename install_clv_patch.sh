#!/usr/bin/env bash
set -e

cd /root/betagent

cp run_pipeline.py run_pipeline.py.bak.$(date +%Y%m%d_%H%M%S)
cp run_server.sh run_server.sh.bak.$(date +%Y%m%d_%H%M%S)

cp run_pipeline.py.fixed run_pipeline.py
cp run_server.sh.fixed run_server.sh

echo "ENABLE_CLV=1" >> .env || true

echo "Done."
echo "Check:"
echo "  python3 run_pipeline.py --help"
echo "  python3 run_pipeline.py --clv --clv-days 30"
