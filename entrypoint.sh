#!/bin/sh
set -e

if [ -d /app/config.yaml ]; then
  echo "printer-butler: /app/config.yaml is a directory." >&2
  echo "Docker created it because the host path was missing. On the host run:" >&2
  echo "  rm -rf config.yaml && mkdir -p config && cp config.yaml.example config/config.yaml" >&2
  exit 1
fi

export TZ="${TZ:-Europe/Prague}"

if [ -d /data ]; then
  export PRINTER_BUTLER_DB="${PRINTER_BUTLER_DB:-/data/pages.sqlite}"
fi

if [ -f /config/config.yaml ]; then
  export PRINTER_BUTLER_CONFIG=/config/config.yaml
elif [ -f /app/config.yaml ]; then
  export PRINTER_BUTLER_CONFIG=/app/config.yaml
else
  echo "printer-butler: no config found; using bundled example" >&2
  export PRINTER_BUTLER_CONFIG=/app/config.yaml.example
fi

exec "$@"
