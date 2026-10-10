FROM python:3.12-slim

# One dependency (the Postgres driver); the HTTP server is the standard library's.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py
COPY static /app/static

WORKDIR /app
USER nobody
EXPOSE 8050
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8050/healthz', timeout=4)"]
CMD ["python", "-u", "app.py"]
