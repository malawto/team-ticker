FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY poller.py .

RUN useradd --create-home --uid 1000 appuser
USER appuser

# Volume-mounted at runtime — not baked into the image filesystem.
ENV TICKER_JSON_PATH=/data/ticker.json
VOLUME ["/data"]

ENTRYPOINT ["python", "poller.py"]
