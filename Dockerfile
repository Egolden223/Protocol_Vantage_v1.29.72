FROM python:3.12-slim

WORKDIR /app

# curl_cffi wheels ; deps système minimales
RUN apt-get update && apt-get install -y --no-install-recommends     ca-certificates     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt     && python -c "from curl_cffi import requests; print('curl_cffi OK')"     && python -c "import bs4, lxml, requests, fastapi, pydantic; print('deps OK')"

COPY app ./app
COPY static ./static


RUN mkdir -p /data
ENV DATABASE_PATH=/data/vantage.db
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3   CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
