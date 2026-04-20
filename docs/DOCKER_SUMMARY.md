# Docker Implementation Summary

## What's Included

### Core Files

- **Dockerfile** - Container image definition with all dependencies
- **docker-compose.yml** - Easy deployment configuration
- **entrypoint.sh** - Smart container startup script
- **.dockerignore** - Excludes unnecessary files from image

### Documentation

- **DOCKER_SETUP.md** - Comprehensive Docker guide
- **README.md** - Complete project documentation
- **requirements.txt** - Python dependencies

## Quick Start

### Simplest Method (Recommended)

```bash
docker-compose up -d
```

This will:

1. Pull the pinned release image from GHCR if needed
2. Start it in background
3. Run scraper daily at 2 AM
4. Keep container running indefinitely

### Check Status

```bash
docker-compose logs -f
docker-compose ps
```

### Stop Everything

```bash
docker-compose down
```

## What the Dockerfile Does

1. **Base Image**: Uses `python:3.14-slim` (smaller, faster)
2. **System Dependencies**: Installs aria2, ffmpeg, cron
3. **Python Packages**: Installs requests, beautifulsoup4, yt-dlp
4. **Setup**: Creates directories, copies scripts, sets permissions
5. **Entrypoint**: Smart startup script for multiple modes

## Container Modes

### 1. Cron Mode (Default)

```bash
docker-compose up -d
```

Runs the script on schedule (default 2 AM daily) and keeps container running.

### 2. One-Time Mode

```bash
docker-compose run --rm fapplepie-downloader once
```

Executes script once, then exits.

### 3. Custom Command Mode

```bash
docker exec fapplepie-downloader python3 scraper.py --scrape
```

Run any custom command inside the running container.

## Volume Mounts

Three persistent volumes:

- **downloads/** - Where videos are saved
- **logs/** - Where execution logs are stored
- **app/cache/processed_cache.json** - Cache file (survives container restarts)

All files persist between container runs.

## Environment Variables

Customizable in `docker-compose.yml`:

```yaml
environment:
  CRON_SCHEDULE: "0 2 * * *" # When to run (2 AM daily)
  DOWNLOAD_DIR: /app/downloads # Download location
  LOG_DIR: /app/logs # Log location
```

## Resource Limits

Configured in docker-compose.yml:

- **CPU**: Limited to 2 cores (min 1)
- **Memory**: Limited to 2GB (min 512MB)

Adjust based on your system.

## Advantages of Docker

✅ **Isolation** - Doesn't affect your system
✅ **Reproducibility** - Same setup everywhere
✅ **Easy updates** - Pull the next pinned release image
✅ **Resource control** - CPU/memory limits
✅ **Logging** - Centralized container logs
✅ **Portability** - Works on Linux, Mac, Windows
✅ **Easy scheduling** - Built-in cron support
✅ **Cleanup** - Remove everything with one command

## Troubleshooting

### Container won't start

```bash
docker-compose logs
```

Shows error messages.

### Check if running

```bash
docker-compose ps
```

### View recent logs

```bash
docker-compose logs --tail=50
```

### Execute command in running container

```bash
docker-compose exec fapplepie-downloader ls /app/logs
```

### Rebuild from scratch

```bash
docker-compose -f docker-compose.dev.yml build --no-cache
docker-compose -f docker-compose.dev.yml up -d
```

The default `docker-compose.yml` uses the published GHCR release image. Use `docker-compose pull && docker-compose up -d` to refresh that deployment.

### Check downloads

```bash
docker-compose exec fapplepie-downloader ls -lh /app/downloads
```

## Production Deployment

### Using systemd

Create `/etc/systemd/system/fapplepie-downloader.service`:

```ini
[Unit]
Description=Fapplepie Downloader
Requires=docker.service
After=docker.service

[Service]
Type=simple
WorkingDirectory=/path/to/fapplepie-downloader
ExecStart=/usr/local/bin/docker-compose up
ExecStop=/usr/local/bin/docker-compose down
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:

```bash
systemctl daemon-reload
systemctl enable fapplepie-downloader
systemctl start fapplepie-downloader
```

### Using Docker Swarm

For distributed deployment across multiple machines.

### Cloud Deployment

Works with:

- Docker Cloud
- AWS ECS
- Azure Container Instances
- Google Cloud Run
- DigitalOcean App Platform

## Performance Notes

- **First run**: 5-10 minutes (scraping + resolving redirects)
- **Subsequent runs**: 30 seconds - 2 minutes (only new videos)
- **Download speed**: 10-50 MB/s with aria2c optimization
- **Memory usage**: ~200-500 MB typical
- **Disk space**: 1-5 GB per 100 videos

## Networking

The container runs in Docker's default network.

For external access:

```yaml
ports:
  - "8080:8080" # If you add a web interface later
```

## Health Check

Container includes health check (runs every hour):

```dockerfile
HEALTHCHECK --interval=1h --timeout=10s --retries=3
```

Check status:

```bash
docker inspect fapplepie-downloader | grep Health
```

## Logging Strategy

Three levels:

1. **Container logs** - Docker output

   ```bash
   docker-compose logs
   ```

2. **Application logs** - In `/app/logs/`

   ```bash
   docker-compose exec fapplepie-downloader tail -f /app/logs/daily_run_*.log
   ```

3. **Docker json-file driver** - Stores last 3 files, max 10MB each

## Backup Strategy

Backup these files:

```bash
# Cache
docker-compose exec fapplepie-downloader cp /app/cache/processed_cache.json /app/cache/processed_cache.json.backup

# Videos
tar -czf downloads_backup_$(date +%Y%m%d).tar.gz downloads/

# Logs
tar -czf logs_backup_$(date +%Y%m%d).tar.gz logs/
```

## Next Steps

1. Read DOCKER_SETUP.md for detailed information
2. Run `docker-compose up -d` to start
3. Check `docker-compose logs -f` to monitor
4. Verify downloads in `downloads/` directory
5. Check cache in `app/cache/processed_cache.json`

## Support Files Reference

- **README.md** - Full project documentation
- **DOCKER_SETUP.md** - Detailed Docker guide
- **CRONTAB_SETUP.md** - Alternative cron scheduling
- **YT_DLP_OPTIMIZATION.md** - Download speed details

All documentation is included in the repository.
