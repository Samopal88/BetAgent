import base64
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PANEL_USER", "test-user")
os.environ.setdefault("PANEL_PASS", "test-password")
os.environ.setdefault("JWT_SECRET", "test-only-secret-that-is-long-enough")
os.environ.setdefault("BETAGENT_DB", str(ROOT / "tests_output" / "test.db"))


def test_python_sources_compile():
    result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_pipeline_cli_help():
    result = subprocess.run(
        [sys.executable, "run_pipeline.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout


def test_validator_accepts_consistent_recommendation():
    from validator import validate_recommendation

    recommendation = {
        "decision": "BET",
        "market": "home",
        "odds": 2.0,
        "market_probability": 0.50,
        "our_probability": 0.56,
        "ev": 0.12,
        "signal_type": "Strong",
        "confidence": 7,
        "lineup_data_available": True,
        "confirmed_facts": ["fact one", "fact two"],
        "market_error": "home price is above the model fair price",
    }
    payload = {"open_exposure_pct": 0.10, "loss_streak_72h_same_sport": 0}
    valid, notes = validate_recommendation(recommendation, payload, bankroll=100000)
    assert valid is True
    assert notes[-1] == "VALID"
    assert 0 < recommendation["stake_pct"] <= 0.10


def test_run_summary_can_be_saved(tmp_path):
    from pipeline_stability import RunSummary, run_task

    summary = RunSummary("test", dry_run=True)
    run_task("ok", lambda: {"signals_created": 2}, summary=summary)
    summary.save(str(tmp_path))
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["summary"]["succeeded"] == 1
    assert payload["summary"]["counters"]["signals_created"] == 2


def test_fastapi_health_endpoint():
    from fastapi.testclient import TestClient
    from api.app import app

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_web_panel_requires_auth_and_renders():
    from web_panel import app

    client = app.test_client()
    assert client.get("/").status_code == 401
    username = os.environ.get("PANEL_USER", "test-user")
    password = os.environ.get("PANEL_PASS", "test-password")
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    response = client.get("/", headers={"Authorization": f"Basic {token}"})
    assert response.status_code == 200
    assert b"BETAGENT" in response.data
