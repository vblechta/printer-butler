# Printer Butler

Live Flask dashboard for Xerox, Brother and Epson printers. It polls each device over its embedded web interface, IPP and SNMP, then streams the merged status to the browser.

Current version: **1.4.0** (shown next to the title; updates with each poll after an app upgrade).

## Docker Compose

```bash
mkdir -p config
cp config.yaml.example config/config.yaml
docker compose up --build -d
```

Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/). Printers are read from `config/config.yaml`, which is mounted into the container. If that file is missing, the bundled example is used so Compose can still start. Page-count history is stored in `data/pages.sqlite` (`./data` mounted at `/data`).

The container timezone defaults to `Europe/Prague`. Set `TZ` to override it. "Today" follows that timezone.

The Compose file uses host networking so SNMP and IPP talk to printers on the LAN. Docker bridge NAT often drops Xerox SNMP replies, which shows up as missing page counts and empty cards for printers that have no IPP (such as PRN-AMBU-RECEP).

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

## Page history

Click a printer's page count to open its statistics. A sample is stored as soon as the printer reports a counter, then every 6 hours (`history.sample_interval_hours`). Printers that do not report a page count have no history and no clickable number.

The dialog shows:

- **Today** — pages since local midnight
- **Last week** — trailing 7 days
- **Last month** — trailing 30 days
- **Average day**, **average month**, and **average year** — the print rate since the first stored reading, scaled to those periods

Week and month charts are one bar per day for those same windows. The year chart is the last 12 calendar months. Last week and last month stay blank until a reading exists from the start of that window. Days and months before the first sample are hatched, not drawn as zero. A counter that drops (replacement or reset) does not subtract pages.

`GET /api/printers/<name>/pages` returns the same statistics as JSON.

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
- `ui.hide_supplies_above_percent` — hide toner/ink/drum bars above this remaining percent (`100` shows all)
- `history.sample_interval_hours` — how often to store each printer's page count (default `6`)
- `history.database` — SQLite file (default `data/pages.sqlite`, or `/data/pages.sqlite` in Docker)

Supply bars use a fixed order on every printer: black, cyan, magenta, yellow, then the matching drums. Drum bars use a striped fill of the same color.

The dashboard uses Server-Sent Events at `/api/stream`. A JSON snapshot is also available at `/api/printers`. Page statistics are at `/api/printers/<name>/pages`. `/healthz` reports `version`.

Point the app at another file with `PRINTER_BUTLER_CONFIG=/path/to/config.yaml`.
