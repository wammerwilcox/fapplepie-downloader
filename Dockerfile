FROM python:3.14-slim@sha256:5b3879b6f3cb77e712644d50262d05a7c146b7312d784a18eff7ff5462e77033

# Set working directory
WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_CACHE_DIR=1

# Install system dependencies (changes infrequently, cache this layer)
RUN apt-get update && apt-get install -y --no-install-recommends \
    aria2 \
    ffmpeg \
    curl \
    cron \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definitions first for better layer caching
COPY app/requirements.in /app/
COPY app/requirements.txt /app/
COPY VERSION /app/

# Create a virtual environment at /venv and install Python dependencies into it.
# This ensures the `daily_download.sh` script can source /venv/bin/activate
RUN python -m venv /venv && \
    /venv/bin/pip install --require-hashes -r requirements.txt

# Copy application files (changes frequently, put last)
COPY app/scraper.py /app/
COPY app/daily_download.sh /app/
COPY app/entrypoint.sh /app/

# Create necessary directories and make scripts executable
RUN mkdir -p /app/logs /app/downloads && \
    chmod +x /app/scraper.py /app/daily_download.sh /app/entrypoint.sh

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PATH="/venv/bin:${PATH}"
ENV DOWNLOAD_DIR=/app/downloads
ENV LOG_DIR=/app/logs

# Health check - verify cron daemon is running
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD pgrep -x cron >/dev/null || exit 1

# Set entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["cron"]
