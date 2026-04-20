# Project Overview

## Complete Fapplepie Downloader Package

This is a fully-featured video scraping and downloading solution with both standalone Python and Docker support.

## Files Included

### Core Application

- **scraper.py** (250+ lines)
  - Main Python application
  - Multi-page web scraping
  - Redirect resolution
  - Video downloading with aria2c
  - Smart caching system
  - Full CLI with argument parsing

### Wrapper Scripts

- **daily_download.sh** (45 lines)
  - Bash wrapper for cron execution
  - Automatic logging to timestamped files
  - Virtual environment activation
  - Log cleanup (keeps last 30 days)

- **entrypoint.sh** (60 lines)
  - Docker container startup script
  - Cron job setup
  - Multiple execution modes (cron/once)
  - Flexible scheduling

### Docker Configuration

- **Dockerfile** (47 lines)
  - Python 3.14 slim base image
  - All system dependencies
  - Python package installation
  - Health checks

- **docker-compose.yml** (60 lines)
  - Production-ready configuration
  - Volume persistence
  - Resource limits
  - Environment variables
  - Logging configuration

- **.dockerignore** (30 lines)
  - Optimized image size

### Configuration Files

- **requirements.txt**
  - Python package pinned versions
  - Reproducible installs

- **app/cache/processed_cache.json**
  - URL resolution cache
  - Download tracking
  - Persistent across runs

- **app/video_urls.txt**
  - Resolved video URLs
  - Output from scraping

### Documentation (Comprehensive)

#### Setup Guides

1. **README.md** (400+ lines)
   - Complete project documentation
   - Quick start guide
   - Usage examples
   - Troubleshooting
   - FAQ

2. **DOCKER_SETUP.md** (350+ lines)
   - Docker installation guide
   - docker-compose usage
   - Configuration options
   - Command reference
   - Production deployment
   - Multi-container setup

3. **CRONTAB_SETUP.md** (120 lines)
   - Cron scheduling guide
   - Timing reference table
   - Troubleshooting cron issues

4. **YT_DLP_OPTIMIZATION.md** (50 lines)
   - Download speed optimization
   - aria2c configuration
   - Performance tuning

#### Project Summaries

5. **DOCKER_SUMMARY.md** (200+ lines)
   - Quick Docker reference
   - Implementation details
   - Mode descriptions
   - Troubleshooting tips

6. **PROJECT_OVERVIEW.md** (This file)
   - Package contents
   - File descriptions
   - Getting started

## Features Summary

### Scraping

✅ Multi-page crawling (64+ pages)
✅ Automatic pagination detection
✅ h3 tag parsing for video links
✅ URL caching to avoid re-scraping

### Download

✅ aria2c integration for 16 parallel connections
✅ Video format flexibility with yt-dlp
✅ Download caching to avoid duplicates
✅ Error handling and retry logic

### Scheduling

✅ Cron job support
✅ Docker cron integration
✅ Multiple execution modes
✅ Flexible scheduling (hourly/daily/custom)

### Cache Management

✅ JSON-based cache file
✅ Resolved URL tracking
✅ Download history
✅ Manual cache clearing

### Logging

✅ Timestamped log files
✅ Automatic log rotation
✅ Docker container logging
✅ Error tracking

### Docker Support

✅ Single image supports multiple modes
✅ Resource limiting
✅ Volume persistence
✅ Health checks
✅ Production-ready

## Getting Started (3 Options)

### Option 1: Docker (Recommended - 2 minutes)

```bash
docker-compose up -d
# Done! Runs daily at 2 AM, downloads to ./downloads/
```

### Option 2: Shell Script (Cron - 5 minutes)

```bash
chmod +x daily_download.sh
crontab -e
# Add: 0 2 * * * /path/to/daily_download.sh
```

### Option 3: Python Direct (10 minutes)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 scraper.py --all
```

## Project Statistics

| Metric           | Value                            |
| ---------------- | -------------------------------- |
| Total Files      | 14                               |
| Python Code      | 250+ lines                       |
| Documentation    | 1000+ lines                      |
| Docker Files     | 4                                |
| Supported Python | 3.7+                             |
| Required Tools   | 4 (requests, bs4, yt-dlp, aria2) |

## Architecture

```
User Request
    ↓
┌─────────────────────────────────────┐
│      scraper.py (Main Logic)        │
│  - Scraping   (BeautifulSoup)       │
│  - Caching    (JSON file)           │
│  - Downloading (yt-dlp + aria2c)    │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│   Execution Wrapper                 │
│   ├─ daily_download.sh (Cron)       │
│   └─ entrypoint.sh (Docker)         │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│   Persistence Layer                 │
│   ├─ cache/processed_cache.json     │
│   ├─ video_urls.txt                 │
│   ├─ downloads/                     │
│   └─ logs/                          │
└─────────────────────────────────────┘
```

## Technology Stack

| Component     | Technology     | Purpose                  |
| ------------- | -------------- | ------------------------ |
| Scraping      | BeautifulSoup4 | HTML parsing             |
| HTTP          | requests       | Web requests             |
| Downloading   | yt-dlp         | Video extraction         |
| Speed         | aria2c         | Parallel downloads       |
| Caching       | JSON           | URL tracking             |
| Scheduling    | cron           | Periodic execution       |
| Container     | Docker         | Isolation & deployment   |
| Orchestration | Docker Compose | Configuration management |
| Logging       | File-based     | Audit trail              |

## Data Flow

```
fapplepie.com
    ↓ (scrape pages 1-64)
→ fapplepie.com URLs (30 per page)
    ↓ (resolve redirects)
→ app/cache/processed_cache.json
    ↓ (get resolved URLs)
→ app/video_urls.txt (1900+ URLs)
    ↓ (download with aria2c)
→ downloads/ (video files)
    ↓ (log execution)
→ logs/ (timestamped logs)
```

## Performance Characteristics

| Phase               | Time     | Notes                          |
| ------------------- | -------- | ------------------------------ |
| First Scrape        | 5-10 min | 1900 URLs, resolving redirects |
| First Download      | Variable | Depends on video count         |
| Subsequent Scrape   | 30 sec   | Only resolve new URLs (cached) |
| Subsequent Download | 1-2 min  | Skip already-downloaded        |

## Deployment Scenarios

### Home User

- Use Docker Compose
- Run daily at 2 AM
- ~500 MB memory usage
- 1-5 GB disk per 100 videos

### Small Server

- Use systemd + Docker
- Run every 6 hours
- Monitor with `docker stats`
- Backup weekly

### Shared Hosting

- Use Python + cron
- Run during off-peak hours
- Store on network drive
- Share cache file

### Cloud Deployment

- Use Docker image
- Deploy to ECS/ACI/GCP
- Use managed storage
- Integrate with pipelines

## Customization Points

Easy to modify:

- **Cron schedule** - Edit docker-compose.yml or crontab
- **Download format** - Change `%(title)s.%(ext)s` in scraper.py
- **aria2c settings** - Adjust `-x 16` for more/fewer connections
- **Cache location** - Change CACHE_FILE variable
- **Logging** - Modify log rotation in daily_download.sh
- **Video quality** - Add yt-dlp format selectors

## Maintenance

### Daily

- Check logs: `docker-compose logs`
- Verify new downloads

### Weekly

- Review cache size: `ls -lh app/cache/processed_cache.json`
- Check disk usage: `du -sh downloads/`

### Monthly

- Backup cache and downloads
- Clean old logs
- Update yt-dlp: `pip install --upgrade yt-dlp`

### Quarterly

- Review Docker image: `docker images`
- Pull release updates: `docker-compose pull && docker-compose up -d`

## Security Notes

- Cache file contains URL mappings (no sensitive data)
- Docker runs with minimal privileges
- No credentials stored (uses public URLs)
- Container can be restricted with AppArmor/SELinux

## Next Steps

1. **Quick Start**: Read README.md (5 min)
2. **Choose Method**: Docker (recommended) or Python
3. **Install**: Follow your chosen guide
4. **Run**: Execute script or start container
5. **Monitor**: Check logs and downloads
6. **Schedule**: Set up cron or rely on Docker

## Support Resources

All documentation is self-contained in the project:

- Stuck? → Check README.md troubleshooting
- Docker questions? → Read DOCKER_SETUP.md
- Cron issues? → See CRONTAB_SETUP.md
- Speed problems? → Check YT_DLP_OPTIMIZATION.md

## License

MIT License - Free to use, modify, and distribute

## Version

**v1.0** - Full feature release

- Complete scraping implementation
- Caching system
- Docker support
- Comprehensive documentation
