# Docker Setup Guide

## Quick Start

### Using Docker Compose (Recommended)

1. **Pull and start the pinned release container**:

```bash
docker-compose up -d
```

2. **View logs**:

```bash
docker-compose logs -f fapplepie-downloader
```

3. **Stop the container**:

```bash
docker-compose down
```

### Manual Docker Build

Use this path when developing or testing a local image instead of the published GHCR release.

1. **Build the image**:

```bash
docker build -t fapplepie-downloader .
```

2. **Run the container with cron (background)**:

```bash
docker run -d \
  --name fapplepie-downloader \
  -v $(pwd)/app/downloads:/app/downloads \
  -v $(pwd)/app/logs:/app/logs \
  -v $(pwd)/app/cache:/app/cache \
  -e CRON_SCHEDULE="0 2 * * *" \
  fapplepie-downloader
```

3. **Run once and exit**:

```bash
docker run --rm \
  -v $(pwd)/app/downloads:/app/downloads \
  -v $(pwd)/app/logs:/app/logs \
  -v $(pwd)/app/cache:/app/cache \
  fapplepie-downloader once
```

## Container Modes

### Cron Mode (Default)

Runs the scraper on a schedule inside the container:

```bash
docker-compose up -d
```

The default compose file uses the versioned release image from GitHub Container Registry:

```yaml
image: ghcr.io/wammerwilcox/fapplepie-downloader:1.0.0
```

### One-Time Execution Mode

Runs the script once and exits:

```bash
docker-compose run --rm fapplepie-downloader once
```

Or with environment variable:

```bash
docker run --rm -e RUN_ONCE=1 fapplepie-downloader
```

## Configuration

### Cron Schedule

Set the `CRON_SCHEDULE` environment variable to control when the script runs.

**docker-compose.yml**:

```yaml
environment:
  CRON_SCHEDULE: "0 2 * * *" # Daily at 2 AM
  # Optional: route scraper/download traffic via NordVPN SOCKS proxy
  # NORDVPN_PROXY: "socks5h://nl.socks.nordhold.net:1080"
  # NORDVPN_USER: "${NORDVPN_USER}" # NordVPN service username
  # NORDVPN_PASS: "${NORDVPN_PASS}" # NordVPN service password
  # SCRAPE_DIRECT_FALLBACK_ON_403: "1" # Retry scrape requests directly if proxied fapplepie requests get HTTP 403
```

**Command line**:

```bash
docker run -e CRON_SCHEDULE="0 */6 * * *" ...
```

### Optional Proxy Routing

To route downloader traffic through a proxy (for example NordVPN proxy):

```bash
docker run \
  -e NORDVPN_PROXY="socks5h://nl.socks.nordhold.net:1080" \
  -e NORDVPN_USER="your_service_user" \
  -e NORDVPN_PASS="your_service_pass" \
  -e NORDVPN_PROXY_SCOPE="fapplepie" \
  -e SCRAPE_DIRECT_FALLBACK_ON_403="1" \
  ...
```

Notes:

- If `NORDVPN_PROXY` is unset, the container uses direct network routing.
- `NORDVPN_PROXY_SCOPE`:
  - `fapplepie` (default): proxy only `fapplepie.com` traffic
  - `all`: proxy all outbound traffic
- `SCRAPE_DIRECT_FALLBACK_ON_403`:
  - `1` (default): retry `fapplepie.com` scrape requests directly if the proxied request returns `403`
  - `0`: keep scrape requests proxy-only and fail fast on proxied `403`
- `NORD_TOKEN` / `NORDVPN_TOKEN` are not proxy credentials.
  Use NordVPN service credentials for proxy auth.
- For `socks5://` or `socks5h://` proxies, downloads use yt-dlp's native
  downloader because aria2c `--all-proxy` does not accept SOCKS proxy format.
- The direct fallback only affects HTML scraping and fapplepie redirect resolution.
  Downloader proxy handling stays unchanged.

### Cron Schedule Examples

| Schedule       | Meaning          |
| -------------- | ---------------- |
| `0 2 * * *`    | Daily at 2 AM    |
| `0 3 * * *`    | Daily at 3 AM    |
| `0 */6 * * *`  | Every 6 hours    |
| `0 */12 * * *` | Every 12 hours   |
| `0 * * * *`    | Every hour       |
| `*/30 * * * *` | Every 30 minutes |

### Volume Mounts

| Host                     | Container                   | Purpose                |
| ------------------------ | --------------------------- | ---------------------- |
| `./app/downloads` | `/app/downloads` | Downloaded videos |
| `./app/logs`      | `/app/logs`      | Execution logs    |
| `./app/cache`     | `/app/cache`     | URL cache         |

## Viewing Logs

### Using docker-compose:

```bash
# Real-time logs
docker-compose logs -f fapplepie-downloader

# Last 100 lines
docker-compose logs --tail=100 fapplepie-downloader
```

### Using docker:

```bash
# Real-time logs
docker logs -f fapplepie-downloader

# Last 100 lines
docker logs --tail=100 fapplepie-downloader
```

### Logs inside container:

```bash
# List all logs
docker exec fapplepie-downloader ls -lh /app/logs/

# View latest log
docker exec fapplepie-downloader tail -f /app/logs/daily_run_*.log
```

## Commands

### View help

```bash
docker run fapplepie-downloader -h
```

### Manual scrape (one-time)

```bash
docker run --rm \
  -v $(pwd)/app/downloads:/app/downloads \
  -v $(pwd)/app/logs:/app/logs \
  -v $(pwd)/app/cache:/app/cache \
  fapplepie-downloader once
```

### Clear cache

```bash
docker run --rm \
  -v $(pwd)/app/cache:/app/cache \
  fapplepie-downloader python3 scraper.py --clear-cache
```

### Check downloaded count

```bash
docker exec fapplepie-downloader bash -c "ls /app/downloads | wc -l"
```

## Resource Management

The docker-compose.yml includes resource limits:

```yaml
deploy:
  resources:
    limits:
      cpus: "2"
      memory: 2G
    reservations:
      cpus: "1"
      memory: 512M
```

Adjust these based on your system:

- Increase CPU/memory if downloads are slow
- Decrease if you have limited resources

## Troubleshooting

### Container won't start

```bash
docker logs fapplepie-downloader
```

### Check if cron is running

```bash
docker exec fapplepie-downloader ps aux | grep cron
```

### Run script manually in container

```bash
docker exec fapplepie-downloader /app/daily_download.sh
```

### Check cache file

```bash
docker exec fapplepie-downloader cat /app/cache/processed_cache.json
```

### Rebuild container

For the default GHCR-backed compose file, pull the configured image again:

```bash
docker-compose pull
docker-compose up -d
```

For local development builds:

```bash
docker-compose -f docker-compose.dev.yml down
docker-compose -f docker-compose.dev.yml build --no-cache
docker-compose -f docker-compose.dev.yml up -d
```

## Updates

To update the script:

1. **Pull the latest compose file changes** (if using Git):

```bash
git pull
```

2. **Pull the pinned release image and restart**:

```bash
docker-compose pull
docker-compose up -d
```

## Production Considerations

### Use versioned release images

The checked-in `docker-compose.yml` uses a versioned GHCR image:

```yaml
image: ghcr.io/wammerwilcox/fapplepie-downloader:1.0.0
```

Renovate can update this version when a newer release image is available.

### Monitor container health

```bash
docker ps  # Check status
docker stats fapplepie-downloader  # Resource usage
```

### Backup downloads

```bash
tar -czf backup_$(date +%Y%m%d).tar.gz downloads/
```

### Database/Cache backup

```bash
cp app/cache/processed_cache.json app/cache/processed_cache.json.backup
```

## Multi-container Setup

To run multiple instances with different schedules:

```yaml
services:
  downloader-morning:
    image: ghcr.io/wammerwilcox/fapplepie-downloader:1.0.0
    environment:
      CRON_SCHEDULE: "0 6 * * *"
    volumes:
      - ./downloads-morning:/app/downloads
      - ./logs-morning:/app/logs

  downloader-evening:
    image: ghcr.io/wammerwilcox/fapplepie-downloader:1.0.0
    environment:
      CRON_SCHEDULE: "0 18 * * *"
    volumes:
      - ./downloads-evening:/app/downloads
      - ./logs-evening:/app/logs
```

## Published Image

Release images are published to GitHub Container Registry:

```bash
docker pull ghcr.io/wammerwilcox/fapplepie-downloader:1.0.0
```
