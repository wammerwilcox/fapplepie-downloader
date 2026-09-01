FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6

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
    unzip \
    && rm -rf /var/lib/apt/lists/*

ARG DENO_VERSION=2.3.0
ARG TARGETARCH
RUN case "${TARGETARCH}" in \
        amd64) deno_arch="x86_64" ;; \
        arm64) deno_arch="aarch64" ;; \
        *) echo "Unsupported Deno architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    curl -fsSL \
    "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-${deno_arch}-unknown-linux-gnu.zip" \
    -o /tmp/deno.zip && \
    unzip -q /tmp/deno.zip -d /usr/local/bin && \
    chmod +x /usr/local/bin/deno && \
    rm /tmp/deno.zip

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
COPY app/cron_healthcheck.sh /app/

# Create necessary directories and make scripts executable
RUN mkdir -p /app/logs /app/downloads && \
    chmod +x /app/scraper.py /app/daily_download.sh /app/entrypoint.sh /app/cron_healthcheck.sh

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PATH="/venv/bin:${PATH}"
ENV DOWNLOAD_DIR=/app/downloads
ENV LOG_DIR=/app/logs
ENV YT_DLP_JS_RUNTIMES=deno

# Health check - verify cron and scheduled dispatch freshness
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD /app/cron_healthcheck.sh

# Set entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["cron"]
