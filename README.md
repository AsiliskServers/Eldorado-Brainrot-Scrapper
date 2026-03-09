# Eldorado Price Tracker (Scrapling)

Projet de suivi des prix Eldorado (brainrots).

## Installer

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Lancer en local

```bash
source .venv/bin/activate
python scripts/run_dashboard.py
```

Ouvrir ensuite:
- `http://127.0.0.1:8787`

## Lancer avec Docker

```bash
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

```bash
source .venv/bin/activate
export NODE_ROLE="main"
export HOST="192.168.1.170"
export PORT="8787"
export SATELLITE_ENABLED="true"
export SATELLITE_BASE_URL="http://82.67.180.129:30080"
python scripts/run_dashboard.py
```

### Serveur satellite
- IP publique: `82.67.180.129`
- Port: `30080`

```bash
source .venv/bin/activate
export NODE_ROLE="satellite"
export HOST="0.0.0.0"
export PORT="30080"
python scripts/run_dashboard.py
```
