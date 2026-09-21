# Printer Butler

Live Flask dashboard for Xerox, Brother and Epson printers. It polls each device over its embedded web interface, IPP and SNMP, then streams the merged status to the browser.

## Docker Compose

```bash
mkdir -p config
cp config.yaml.example config/config.yaml
docker compose up --build -d
```

Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/). Printers are read from `config/config.yaml`, which is mounted into the container. If that file is missing, the bundled example is used so Compose can still start.

If a previous start failed with a mount error, Docker may have created a **directory** named `config.yaml`. Remove it first (`rm -rf config.yaml`).

```bash
docker compose down
```

## Local setup

```bash
cp config.yaml.example config.yaml
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Configuration

Printers are listed in `config.yaml` for a local run, or `config/config.yaml` for Docker (copy from `config.yaml.example`):

```yaml
printers:
  - name: PRN-PEDI-RECEP
    ip: 192.168.193.184
    brand: xerox
    location: Pediatrie recepce
```

Supported brands: `xerox`, `brother`, `epson`.

Optional keys:

- `community` — SNMPv2c community for one printer (defaults to `snmp.community`)
- `listen.host` / `listen.port`
- `poll_interval_seconds`
- `snmp.enabled`, `http.enabled`, `ipp.enabled`
- `alerts.nongenuine_toner_as_warning` — set `false` to ignore Brother non-genuine toner for health

The dashboard uses Server-Sent Events at `/api/stream`. A JSON snapshot is also available at `/api/printers`.

Point the app at another file with `PRINTER_BUTLER_CONFIG=/path/to/config.yaml`.
