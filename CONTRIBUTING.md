# Contributing

1. Create a branch from `main`.
2. Keep secrets and generated datasets out of commits.
3. Run `python -m pytest -q`, `python -m compileall -q .` and `python scripts/check_public.py`.
4. Describe the affected pipeline stage, data source and rollback plan in the pull request.
5. Do not change strategy thresholds or settlement semantics without reproducible evidence and a shadow/backtest comparison.

Small focused pull requests are preferred. Preserve compatibility with Python 3.11 and 3.12.
