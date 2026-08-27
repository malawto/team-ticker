FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY poller.py .

# No user/UID baked in here. Which host user this container runs as is set
# per-deployment via the compose file's `user: "${PUID}:${PGID}"` (see
# docker-compose.yml for local dev, docker-compose.pi5-nas.yml for the real
# deploy) — the same image works correctly regardless of which UID/GID owns
# the bind-mounted /data directory on a given host, rather than a UID
# hardcoded at build time that only happens to be right by coincidence.

# Volume-mounted at runtime — not baked into the image filesystem.
ENV TICKER_JSON_PATH=/data/ticker.json
VOLUME ["/data"]

ENTRYPOINT ["python", "poller.py"]
