# Eldorado Price Tracker (Scrapling)

Projet de suivi des prix Eldorado (brainrots).

## Installer

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Lancer en local

```powershell
.venv\Scripts\python .\scripts\run_dashboard.py
```

Ouvrir ensuite:
- `http://127.0.0.1:8787`

## Lancer avec Docker

```powershell
docker compose up --build -d
```
