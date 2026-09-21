#!/usr/bin/env python3
"""Cross-platform installer and launcher for BetAgent."""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(str(part) for part in command))
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def ensure_env_file() -> tuple[Path, str | None]:
    env_path = ROOT / ".env"
    if not env_path.exists():
        shutil.copy2(ROOT / ".env.example", env_path)

    lines = env_path.read_text(encoding="utf-8").splitlines()
    generated_panel_password: str | None = None

    def set_if_blank(key: str, value: str) -> None:
        nonlocal lines
        prefix = f"{key}="
        for index, line in enumerate(lines):
            if line.startswith(prefix):
                if not line[len(prefix):].strip():
                    lines[index] = prefix + value
                return
        lines.append(prefix + value)

    set_if_blank("JWT_SECRET", secrets.token_urlsafe(48))
    panel_password = secrets.token_urlsafe(18)
    before = next((line for line in lines if line.startswith("PANEL_PASS=")), "")
    if before == "PANEL_PASS=":
        set_if_blank("PANEL_PASS", panel_password)
        generated_panel_password = panel_password

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_path, generated_panel_password


def install(args: argparse.Namespace) -> None:
    if sys.version_info < (3, 10):
        raise SystemExit("BetAgent requires Python 3.10 or newer")

    if not VENV_PYTHON.exists():
        print(f"Creating virtual environment: {VENV}")
        venv.EnvBuilder(with_pip=True).create(VENV)

    run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"])
    requirements = "requirements-dev.txt" if args.dev else "requirements.txt"
    run([str(VENV_PYTHON), "-m", "pip", "install", "-r", requirements])

    if args.playwright:
        run([str(VENV_PYTHON), "-m", "playwright", "install", "chromium"])

    for directory in ("logs", "reports", "run_summaries", "tests_output", "data", "ml_output"):
        (ROOT / directory).mkdir(exist_ok=True)

    env_path, panel_password = ensure_env_file()
    print(f"Configuration: {env_path}")
    if panel_password:
        print(f"Generated PANEL_PASS: {panel_password}")
        print("Save this password now; it is stored only in your local .env file.")
    print("Installation complete. Run: python scripts/betagent.py doctor")


def load_env() -> dict[str, str]:
    env = os.environ.copy()
    env_path = ROOT / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip())
    return env


def doctor(_: argparse.Namespace) -> None:
    failures: list[str] = []
    print(f"Project: {ROOT}")
    print(f"Python:  {VENV_PYTHON if VENV_PYTHON.exists() else 'missing .venv'}")

    if not VENV_PYTHON.exists():
        failures.append("virtual environment is missing; run install first")
    else:
        imports = (
            "bs4,fastapi,flask,lightgbm,numpy,pandas,playwright,psycopg2,"
            "pydantic,dotenv,jwt,telegram,yaml,requests,sklearn,uvicorn"
        )
        result = subprocess.run(
            [str(VENV_PYTHON), "-c", f"import {imports}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            failures.append("dependency import failed: " + result.stderr.strip().splitlines()[-1])

    env = load_env()
    required = ("PANEL_PASS", "JWT_SECRET")
    for key in required:
        if not env.get(key):
            failures.append(f"{key} is empty")

    optional_groups = {
        "admin Telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
        "client Telegram": ("CLIENT_BOT_TOKEN",),
        "LLM analysis": ("LLM_API_KEY",),
        "subscriber API": ("DATABASE_URL",),
    }
    for label, keys in optional_groups.items():
        configured = all(env.get(key) for key in keys)
        print(f"{label:20} {'configured' if configured else 'not configured (optional)'}")

    if failures:
        print("Doctor: FAILED")
        for failure in failures:
            print(" -", failure)
        raise SystemExit(1)
    print("Doctor: PASS")


def launch(component: str, extra: list[str]) -> None:
    if not VENV_PYTHON.exists():
        raise SystemExit("Run the installer first")
    env = load_env()
    commands = {
        "api": [str(VENV_PYTHON), "-m", "uvicorn", "api.app:app", "--host", "127.0.0.1", "--port", "8001"],
        "panel": [str(VENV_PYTHON), "web_panel.py"],
        "bot": [str(VENV_PYTHON), "tg_bot.py"],
        "client-bot": [str(VENV_PYTHON), "bot/client_bot.py"],
        "pipeline": [str(VENV_PYTHON), "run_pipeline.py"],
    }
    run(commands[component] + extra, env=env)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install, verify and run BetAgent")
    sub = parser.add_subparsers(dest="command", required=True)

    install_parser = sub.add_parser("install", help="create .venv and install dependencies")
    install_parser.add_argument("--dev", action="store_true", help="include test and audit tools")
    install_parser.add_argument("--playwright", action="store_true", help="download Chromium for browser parsers")
    install_parser.set_defaults(handler=install)

    doctor_parser = sub.add_parser("doctor", help="check dependencies and base configuration")
    doctor_parser.set_defaults(handler=doctor)

    for component in ("api", "panel", "bot", "client-bot", "pipeline"):
        component_parser = sub.add_parser(component, help=f"run {component}")
        component_parser.add_argument("args", nargs=argparse.REMAINDER)
        component_parser.set_defaults(handler=lambda ns, c=component: launch(c, ns.args))

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
