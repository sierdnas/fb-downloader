FROM python:3.12-slim

# ffmpeg for video processing/remuxing, curl for the healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

RUN mkdir -p /config /media/facebook /media/facebook-photos

ENV PYTHONUNBUFFERED=1 \
    CONFIG_DIR=/config \
    MEDIA_ROOT=/media/facebook \
    PHOTO_MEDIA_ROOT=/media/facebook-photos

EXPOSE 8686

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -f http://localhost:8686/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8686"]
