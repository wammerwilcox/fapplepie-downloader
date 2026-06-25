# Docker Setup Guide

## Quick Start

### Using Docker Compose (Recommended)

1. **Pull and start the versioned release container**:

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

The default compose file on this branch uses the versioned beta image from GitHub Container Registry:

```yaml
image: ghcr.io/wammerwilcox/fapplepie-downloader:2.0.0-beta.7
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
- `NORDVPN_PROXY_DOWNLOAD_DOMAINS` is a comma-separated list of downloader
  hosts that should use the configured proxy even when `NORDVPN_PROXY_SCOPE` is
  `fapplepie`. For example, `xhamster.com` also matches subdomains such as
  `de.xhamster.com`.
- `SCRAPE_DIRECT_FALLBACK_ON_403`:
  - `1` (default): retry `fapplepie.com` scrape requests directly if the proxied request returns `403`
  - `0`: keep scrape requests proxy-only and fail fast on proxied `403`
- `NORD_TOKEN` / `NORDVPN_TOKEN` are not proxy credentials.
  Use NordVPN service credentials for proxy auth.
- For `socks5://` or `socks5h://` proxies, downloads use yt-dlp's native
  downloader because aria2c `--all-proxy` does not accept SOCKS proxy format.
- The direct fallback only affects HTML scraping and fapplepie redirect resolution.
  Downloader proxy handling is controlled by `NORDVPN_PROXY_SCOPE` and
  `NORDVPN_PROXY_DOWNLOAD_DOMAINS`.

### YouTube Cookies and JavaScript Runtime

Current yt-dlp YouTube extraction needs a JavaScript runtime for signature
challenges. The Docker image installs Deno and sets:

```yaml
environment:
  YT_DLP_JS_RUNTIMES: "deno"
```

Age-gated YouTube videos also need signed-in cookies. The compose files mount
`./app/secrets` at `/app/secrets`; place a Netscape-format cookie jar there and
point yt-dlp at it. This mount must be read/write because yt-dlp saves cookie
jar updates when it exits:

```yaml
environment:
  YT_DLP_COOKIES_FILE: /app/secrets/youtube.cookies.txt
```

To export or refresh cookies from Chrome without installing yt-dlp locally:

1. On the host machine, open Chrome and sign in to YouTube with the account that
   can view the video.
2. Install a trusted Chrome extension that exports cookies in Netscape
   `cookies.txt` format. Avoid extensions that upload cookies to a remote
   service.
3. Use the extension on `youtube.com` to export cookies, and save the file as
   `app/secrets/youtube.cookies.txt` in this repository.
4. Confirm the file exists at `app/secrets/youtube.cookies.txt`.

If yt-dlp is already installed on the host, this command can do the same export:

```bash
mkdir -p app/secrets
yt-dlp --cookies-from-browser chrome \
  --cookies app/secrets/youtube.cookies.txt \
  --skip-download "https://www.youtube.com/"
```

If the command says Chrome's cookie database is locked, fully quit Chrome and
run it again.

Use the browser that has the active YouTube login. The pinned yt-dlp supports
`brave`, `chrome`, `chromium`, `edge`, `firefox`, `opera`, `safari`,
`vivaldi`, and `whale`. For a specific Chrome profile, use the yt-dlp browser
profile syntax, for example `chrome:Profile 1`. Cookie files are secrets and are
ignored by Git.

### Polite Timing

Images that include probe mode also support pacing controls for scraper traffic.
Scheduled cron runs apply start jitter before network work begins; manual `once`
commands, direct `scraper.py` commands, and manual `daily_download.sh` runs start
immediately.

```yaml
environment:
  SCRAPE_START_DELAY_SECONDS: "0"
  SCRAPE_START_DELAY_JITTER_SECONDS: "1800"
  SCRAPE_DELAY_SECONDS: "1.0"
  SCRAPE_DELAY_JITTER_SECONDS: "0"
  SCRAPE_REDIRECT_DELAY_SECONDS: "1.0"
  SCRAPE_REDIRECT_DELAY_JITTER_SECONDS: "1.0"
```

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

| Host              | Container        | Purpose           |
| ----------------- | ---------------- | ----------------- |
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

### Probe scraper (local development image)

Probe mode requires an image built from a version that includes `--probe`.

```bash
docker compose -f docker-compose.dev.yml run --rm fapplepie-downloader python3 scraper.py --probe
docker exec fapplepie-downloader-dev python3 scraper.py --probe
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

2. **Pull the pinned beta image and restart**:

```bash
docker-compose pull
docker-compose up -d
```

## Production Considerations

### Use versioned beta images

The checked-in `docker-compose.yml` uses a versioned GHCR beta image:

```yaml
image: ghcr.io/wammerwilcox/fapplepie-downloader:2.0.0-beta.7
```

For multi-architecture deployments that should select the platform automatically, use the tag without an architecture-specific digest.

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
    image: ghcr.io/wammerwilcox/fapplepie-downloader:2.0.0-beta.7
    environment:
      CRON_SCHEDULE: "0 6 * * *"
    volumes:
      - ./downloads-morning:/app/downloads
      - ./logs-morning:/app/logs

  downloader-evening:
    image: ghcr.io/wammerwilcox/fapplepie-downloader:2.0.0-beta.7
    environment:
      CRON_SCHEDULE: "0 18 * * *"
    volumes:
      - ./downloads-evening:/app/downloads
      - ./logs-evening:/app/logs
```

## Published Image

Beta images are published to GitHub Container Registry:

```bash
docker pull ghcr.io/wammerwilcox/fapplepie-downloader:2.0.0-beta.7
```
