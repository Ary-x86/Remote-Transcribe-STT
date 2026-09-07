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

# Run unprivileged; /data is a volume so it has to be writable by this user.
RUN useradd --system --create-home --uid 10001 transcribe \
 && mkdir -p /data/audio \
 && chown -R transcribe:transcribe /data /srv
USER transcribe

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
