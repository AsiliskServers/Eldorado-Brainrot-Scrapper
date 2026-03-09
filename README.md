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

## Mode multi-serveur (main + satellite)

Le noeud `main` (dashboard + orchestration) repartit les pages entre:
- scraping local
- scraping distant via le noeud `satellite`

Le noeud `satellite` expose uniquement:
- `POST /api/satellite/scrape-pages`

### Serveur main
- IP: `192.168.1.170`
- Port: `8787`

```powershell
$env:NODE_ROLE="main"
$env:HOST="192.168.1.170"
$env:PORT="8787"
$env:SATELLITE_ENABLED="true"
$env:SATELLITE_BASE_URL="http://82.67.180.129:30080"
.venv\Scripts\python .\scripts\run_dashboard.py
```

### Serveur satellite
- IP publique: `82.67.180.129`
- Port: `30080`

```powershell
$env:NODE_ROLE="satellite"
$env:HOST="0.0.0.0"
$env:PORT="30080"
.venv\Scripts\python .\scripts\run_dashboard.py
```
