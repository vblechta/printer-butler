FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py config.py monitor.py status.py VERSION ./
COPY collectors ./collectors
COPY templates ./templates
COPY static ./static
COPY config.yaml.example ./config.yaml

EXPOSE 8080

ENV PRINTER_BUTLER_CONFIG=/app/config.yaml \
    PYTHONUNBUFFERED=1

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--worker-class", "gthread", "--workers", "1", "--threads", "8", "--timeout", "0", "app:app"]
