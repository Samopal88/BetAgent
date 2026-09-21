# BetAgent

BetAgent is a multi-sport analytics platform for collecting odds and results, enriching fixtures, evaluating rule-based and ML strategies, producing analytical signals, settling outcomes and delivering notifications through Telegram, FastAPI and an administrative dashboard.

## Quick start

```bash
git clone https://github.com/Samopal88/BetAgent.git
cd BetAgent
bash scripts/install.sh
python scripts/betagent.py doctor
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
python scripts/betagent.py doctor
```

Copy and configure `.env` before enabling external integrations. See [INSTALLATION.md](INSTALLATION.md) and [CONFIGURATION.md](CONFIGURATION.md).

## Disclaimer

BetAgent is an analytics and research tool. It is not a bookmaker, does not place wagers on behalf of users and does not guarantee profit. Sports betting involves a risk of financial loss and is for adults only.
