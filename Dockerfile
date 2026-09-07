FROM python:3.14-slim

# ffmpeg does all the audio work: probing, downsampling, silence detection,
# and splitting long recordings.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/
COPY docker-entrypoint.sh /usr/local/bin/

# The entrypoint starts as root only long enough to make /data writable, then
# drops to this account. Staying root the whole way would be simpler and worse.
RUN useradd --system --create-home --uid 10001 transcribe \
 && mkdir -p /data/audio \
 && chown -R transcribe:transcribe /data /srv \
 && chmod +x /usr/local/bin/docker-entrypoint.sh

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
