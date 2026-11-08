FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AIRS_STATE_DB=/var/lib/airs-agent/state.db

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app

RUN useradd --system --uid 10001 --home-dir /var/lib/airs-agent airs \
    && install -d -o airs -g airs -m 0700 /var/lib/airs-agent

USER airs
CMD ["python", "-m", "app.main"]
