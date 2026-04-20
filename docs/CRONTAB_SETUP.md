# Crontab Setup Instructions

## Quick Setup

1. **Make the script executable** (already done):

```bash
chmod +x fapplepie-downloader/daily_download.sh
```

2. **Add to crontab**:

```bash
crontab -e
```

3. **Add one of these lines**:

### Run daily at 2 AM:

```
0 2 * * * fapplepie-downloader/daily_download.sh
```

### Run daily at 3 AM:

```
0 3 * * * fapplepie-downloader/daily_download.sh
```

### Run every 6 hours:

```
0 */6 * * * fapplepie-downloader/daily_download.sh
```

### Run every 12 hours:

```
0 */12 * * * fapplepie-downloader/daily_download.sh
```

## What the Script Does

- ✅ Activates the Python virtual environment
- ✅ Runs `scraper.py --all` (scrapes new videos and downloads them)
- ✅ Uses the cache to avoid re-processing known videos
- ✅ Logs all output with timestamps to `logs/` directory
- ✅ Automatically cleans up logs older than 30 days
- ✅ Sends email notifications (if configured)

## Viewing Logs

Check the latest run:

```bash
tail -f fapplepie-downloader/logs/daily_run_*.log
```

List all logs:

```bash
ls -lh fapplepie-downloader/logs/
```

## Troubleshooting

### Check if cron is running your job:

```bash
log stream --predicate 'process == "cron"' --level debug
```

### Verify crontab is set:

```bash
crontab -l
```

### Test the script manually:

```bash
fapplepie-downloader/daily_download.sh
```

## Cron Timing Reference

| Time             | Cron Expression |
| ---------------- | --------------- |
| 2 AM daily       | `0 2 * * *`     |
| 3 AM daily       | `0 3 * * *`     |
| Every 6 hours    | `0 */6 * * *`   |
| Every 12 hours   | `0 */12 * * *`  |
| Every hour       | `0 * * * *`     |
| Every 30 minutes | `*/30 * * * *`  |

## Note

The script will:

- Only download videos not already in the cache
- Only resolve redirects for new URLs
- Create a `logs/` directory automatically
- Keep detailed logs of each run with timestamps
