FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY poller.py .

# Trust any extra CA certs for this specific deployment (e.g. a local mkcert
# CA, needed to push an Uptime Kuma heartbeat or similar over HTTPS to a
# self-signed internal service). extra-ca-certs/ is empty except a
# placeholder in the repo — this is a no-op for anyone else deploying this
# generic tool without that need; a real deployment drops its own .crt
# file(s) in there (gitignored, same as .env) before building.
COPY extra-ca-certs/ /usr/local/share/ca-certificates/
RUN update-ca-certificates
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# No user/UID baked in here. Which host user this container runs as is set
# per-deployment via the compose file's `user: "${PUID}:${PGID}"` (see
# docker-compose.yml for local dev, docker-compose.prod.yml for the real
# deploy) — the same image works correctly regardless of which UID/GID owns
# the bind-mounted /data directory on a given host, rather than a UID
# hardcoded at build time that only happens to be right by coincidence.

# Volume-mounted at runtime — not baked into the image filesystem.
ENV TICKER_JSON_PATH=/data/ticker.json
VOLUME ["/data"]

ENTRYPOINT ["python", "poller.py"]
