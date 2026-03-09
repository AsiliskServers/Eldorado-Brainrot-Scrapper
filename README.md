# Eldorado Price Tracker (Scrapling)

Projet de suivi des prix Eldorado (brainrots).

## Installer

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
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

## Demarrage auto avec systemd (Debian 13)

Les fichiers systemd sont fournis dans:
- `deploy/systemd/eldorado-main.service`
- `deploy/systemd/eldorado-satellite.service`
- `deploy/systemd/main.env.example`
- `deploy/systemd/satellite.env.example`

### Configuration complete (copier/coller)

`/etc/systemd/system/eldorado-main.service`

```ini
[Unit]
Description=Eldorado Brainrot Scraper (Main Node)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/gestion/container/scrapper
EnvironmentFile=/etc/eldorado-scraper/main.env
ExecStart=/gestion/container/scrapper/.venv/bin/python /gestion/container/scrapper/scripts/run_dashboard.py
Restart=always
RestartSec=5
User=root
Group=root

[Install]
WantedBy=multi-user.target
```

`/etc/eldorado-scraper/main.env`

```bash
NODE_ROLE=main
HOST=192.168.1.170
PORT=8787
SATELLITE_ENABLED=true
SATELLITE_BASE_URL=http://82.67.180.129:30080
SATELLITE_TIMEOUT=900
SCRAPE_TIMEOUT=30
SCRAPE_IMPERSONATE=chrome
```

`/etc/systemd/system/eldorado-satellite.service`

```ini
[Unit]
Description=Eldorado Brainrot Scraper (Satellite Node)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/gestion/container/scrapper
EnvironmentFile=/etc/eldorado-scraper/satellite.env
ExecStart=/gestion/container/scrapper/.venv/bin/python /gestion/container/scrapper/scripts/run_dashboard.py
Restart=always
RestartSec=5
User=root
Group=root

[Install]
WantedBy=multi-user.target
```

`/etc/eldorado-scraper/satellite.env`

```bash
NODE_ROLE=satellite
HOST=0.0.0.0
PORT=30080
SCRAPE_TIMEOUT=30
SCRAPE_IMPERSONATE=chrome
```

### Installation systemd - Main (192.168.1.170)

```bash
cd /gestion/container/scrapper
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

sudo mkdir -p /etc/eldorado-scraper
sudo cp deploy/systemd/main.env.example /etc/eldorado-scraper/main.env
sudo cp deploy/systemd/eldorado-main.service /etc/systemd/system/eldorado-main.service

sudo systemctl daemon-reload
sudo systemctl enable --now eldorado-main.service
sudo systemctl status eldorado-main.service
```

### Installation systemd - Satellite (82.67.180.129:30080)

```bash
cd /gestion/container/scrapper
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

sudo mkdir -p /etc/eldorado-scraper
sudo cp deploy/systemd/satellite.env.example /etc/eldorado-scraper/satellite.env
sudo cp deploy/systemd/eldorado-satellite.service /etc/systemd/system/eldorado-satellite.service

sudo systemctl daemon-reload
sudo systemctl enable --now eldorado-satellite.service
sudo systemctl status eldorado-satellite.service
```

Logs live:

```bash
sudo journalctl -u eldorado-main.service -f
sudo journalctl -u eldorado-satellite.service -f
```
