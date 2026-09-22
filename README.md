# Printer Butler

Live Flask dashboard for Xerox, Brother and Epson printers. It polls each device over its embedded web interface, IPP and SNMP, then streams the merged status to the browser.

Current version: **1.1.0** (shown next to the title; updates with each poll after an app upgrade).

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

## Kiosk

Fullscreen compact view (hides summary, filters, IPs and serials):

[http://127.0.0.1:8080/?fullscreen=1](http://127.0.0.1:8080/?fullscreen=1)

Fit every printer card in the viewport (works with or without fullscreen; column count and scale adjust on resize and each poll):

[http://127.0.0.1:8080/?autoscale=1](http://127.0.0.1:8080/?autoscale=1)

Both together:

[http://127.0.0.1:8080/?fullscreen=1&autoscale=1](http://127.0.0.1:8080/?fullscreen=1&autoscale=1)

Bare `?fullscreen` / `?autoscale` and `1` / `true` / `yes` / `on` are accepted. Pair with a Chromium kiosk flag such as `--kiosk` if you want the browser chrome gone too.

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

The dashboard uses Server-Sent Events at `/api/stream`. A JSON snapshot is also available at `/api/printers`. `/healthz` reports `version`.

Point the app at another file with `PRINTER_BUTLER_CONFIG=/path/to/config.yaml`.
