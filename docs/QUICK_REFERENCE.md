# Quick Reference Card

## Start Options (Pick One)

### 🐳 Docker (Recommended - Simplest)

```bash
docker-compose up -d
```

Runs automatically every day at 2 AM.

### ⏰ Cron Job (Linux/Mac)

```bash
chmod +x daily_download.sh
crontab -e
# Add: 0 2 * * * /full/path/to/daily_download.sh
```

Runs at 2 AM daily via system cron.

### 🐍 Python Direct (Manual)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 scraper.py --all
```

Runs once, you control when.

---

## Common Commands

### Docker Commands

```bash
# Start
docker-compose up -d

# Stop
docker-compose down

# Check logs
docker-compose logs -f

# Run once
docker-compose run --rm fapplepie-downloader once

# Check downloads
docker-compose exec fapplepie-downloader ls /app/downloads

# Clear cache
docker-compose exec fapplepie-downloader python3 scraper.py --clear-cache
```

### Python Commands

```bash
# Scrape only
python3 scraper.py --scrape

# Download only
python3 scraper.py --download

# Both
python3 scraper.py --all

# Clear cache
python3 scraper.py --clear-cache

# Help
python3 scraper.py --help
```

### File Locations

```bash
# Downloaded videos
./app/downloads/

# Execution logs
./app/logs/

# URL cache
./app/cache/processed_cache.json

# Resolved URLs
./app/video_urls.txt
```

---

## Schedule Reference (Cron/Docker)

| When           | Cron           | Docker                          |
| -------------- | -------------- | ------------------------------- |
| Daily 2 AM     | `0 2 * * *`    | `CRON_SCHEDULE: "0 2 * * *"`    |
| Every 6 hours  | `0 */6 * * *`  | `CRON_SCHEDULE: "0 */6 * * *"`  |
| Every 12 hours | `0 */12 * * *` | `CRON_SCHEDULE: "0 */12 * * *"` |
| Every hour     | `0 * * * *`    | `CRON_SCHEDULE: "0 * * * *"`    |
| Every 30 min   | `*/30 * * * *` | `CRON_SCHEDULE: "*/30 * * * *"` |

---

## Troubleshooting Quick Fixes

### Downloads slow?

- Increase aria2c connections in scraper.py: change `-x 16` to `-x 32`

### Script hangs?

- Check internet: `ping google.com`
- Verify yt-dlp: `yt-dlp --version`

### Docker won't start?

```bash
docker-compose logs  # See error
docker-compose pull  # Refresh pinned release image
docker-compose up -d
```

### Can't find downloads?

```bash
# Docker
docker-compose exec fapplepie-downloader ls -la /app/downloads

# Python
ls -la downloads/
```

### Clear everything and start fresh?

```bash
python3 scraper.py --clear-cache
rm app/video_urls.txt
rm -rf app/downloads/* app/logs/* app/cache/*
python3 scraper.py --all
```

---

## Files Overview

| File                 | Purpose          | Edit?                          |
| -------------------- | ---------------- | ------------------------------ |
| scraper.py           | Main application | ⚠️ Advanced users only         |
| docker-compose.yml   | Docker config    | ✅ Change schedule/directories |
| daily_download.sh    | Cron wrapper     | ⚠️ Advanced users only         |
| app/cache/processed_cache.json | URL cache        | ❌ Auto-managed                |
| requirements.txt     | Python packages  | ❌ Leave as-is                 |
| README.md            | Full docs        | 📖 Read for details            |
| DOCKER_SETUP.md      | Docker guide     | 📖 Read if using Docker        |
| CRONTAB_SETUP.md     | Cron guide       | 📖 Read if using cron          |

---

## Performance Expectations

### First Run

- **Time**: 5-10 minutes (scraping + resolving)
- **Data**: 1,900+ video URLs
- **Network**: Heavy (resolving redirects)

### Subsequent Runs

- **Time**: 30 seconds - 2 minutes
- **Data**: Only new videos
- **Network**: Minimal (uses cache)

### Download Speed

- **Without optimization**: 2-5 MB/s
- **With aria2c**: 10-50+ MB/s

---

## Environment Variables

### Docker

Edit `docker-compose.yml`:

```yaml
environment:
  CRON_SCHEDULE: "0 2 * * *" # When to run
  DOWNLOAD_DIR: /app/downloads # Where to save
  LOG_DIR: /app/logs # Where logs go
```

### Python

Set before running:

```bash
export DOWNLOAD_DIR="/my/videos"
python3 scraper.py --all
```

---

## Help & Documentation

| Question                   | File                   |
| -------------------------- | ---------------------- |
| "How do I get started?"    | README.md              |
| "How do I use Docker?"     | DOCKER_SETUP.md        |
| "How do I set up cron?"    | CRONTAB_SETUP.md       |
| "How do I make it faster?" | YT_DLP_OPTIMIZATION.md |
| "What's in this project?"  | PROJECT_OVERVIEW.md    |
| "Quick Docker reference?"  | DOCKER_SUMMARY.md      |

---

## Critical Commands (Copy-Paste Ready)

```bash
# Start with Docker (most common)
cd ~/Documents/Apps/fapplepie-downloader
docker-compose up -d

# Check it's running
docker-compose logs -f

# View downloads
ls -lh downloads/

# Stop everything
docker-compose down

# Clear cache
docker-compose exec fapplepie-downloader python3 scraper.py --clear-cache

# Run once more
docker-compose run --rm fapplepie-downloader once
```

---

## Pro Tips

1. **Run during off-peak hours** (2-4 AM) to avoid network congestion
2. **Monitor disk space** - Budget 1-5 GB per 100 videos
3. **Backup cache weekly** - `cp app/cache/processed_cache.json backup.json`
4. **Keep logs** - Helpful for debugging issues
5. **Use Docker** - Simplest, most reliable option
6. **Pin versions** - Prevents breaking changes

---

## System Requirements

| Component | Minimum | Recommended |
| --------- | ------- | ----------- |
| RAM       | 256 MB  | 1 GB        |
| CPU       | 1 core  | 2 cores     |
| Disk      | 1 GB    | 5+ GB       |
| Network   | 1 Mbps  | 10 Mbps     |
| Python    | 3.7+    | 3.11+       |

---

## One-Line Starters

```bash
# Docker (no setup)
docker-compose up -d

# Python (with venv)
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt && python3 scraper.py --all

# Just scrape
python3 scraper.py --scrape

# Clear and start over
python3 scraper.py --clear-cache && python3 scraper.py --all
```

---

## Emergency Recovery

```bash
# If Docker breaks
docker-compose down -v  # Remove everything
docker-compose up -d    # Start fresh (keeps cache)

# If Python breaks
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# If cache corrupts
python3 scraper.py --clear-cache
python3 scraper.py --scrape

# If out of disk space
ls -lah downloads/ | sort -k5 -hr | head -20  # Find largest files
docker-compose exec fapplepie-downloader du -sh /app/downloads  # Check size
```

---

**Last Updated**: January 18, 2026
**Version**: 1.0
**Status**: Production Ready ✅
