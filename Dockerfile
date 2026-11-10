FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY app.py config.py monitor.py status.py history.py VERSION ./
COPY collectors ./collectors
COPY templates ./templates
COPY static ./static
COPY config.yaml ./config.yaml
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8080

ENV PRINTER_BUTLER_CONFIG=/app/config.yaml \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--worker-class", "gthread", "--workers", "1", "--threads", "8", "--timeout", "0", "app:app"]
