#!/bin/bash

# Daily video scraper and downloader script
# Add to crontab with: 0 2 * * * /path/to/daily_download.sh

# Configuration
## Resolve script directory robustly so cron/sh doesn't break it.
# Use BASH_SOURCE when running under bash; otherwise fall back to $0.
if [ -n "${BASH_VERSION:-}" ]; then
    SOURCE="${BASH_SOURCE[0]}"
else
    SOURCE="$0"
fi
SCRIPT_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
# Compute parent dir by moving up from the script dir.
PARENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PATH="${PARENT_DIR}/venv"
LOG_DIR="${SCRIPT_DIR}/logs"
LOG_FILE="${LOG_DIR}/daily_run_$(date +%Y%m%d_%H%M%S).log"

# Create logs directory if it doesn't exist
mkdir -p "${LOG_DIR}"

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

# Activate virtual environment
if [ ! -d "${VENV_PATH}" ]; then
    log "ERROR: Virtual environment not found at ${VENV_PATH}"
    exit 1
fi

log "Starting daily video scraper..."
log "Script directory: ${SCRIPT_DIR}"

# Activate venv and run the scraper
cd "${SCRIPT_DIR}" || exit 1
source "${VENV_PATH}/bin/activate" || exit 1

# Run the scraper with --all option (scrape and download)
log "Running: python3 scraper.py --all"
python3 scraper.py --all >> "${LOG_FILE}" 2>&1
SCRAPER_EXIT_CODE=$?

if [ $SCRAPER_EXIT_CODE -eq 0 ]; then
    log "SUCCESS: Scraper completed successfully"
else
    log "ERROR: Scraper failed with exit code $SCRAPER_EXIT_CODE"
fi

log "Log saved to: ${LOG_FILE}"

# Cleanup old logs (keep last 30 days)
log "Cleaning up old logs..."
find "${LOG_DIR}" -name "daily_run_*.log" -type f -mtime +30 -delete

log "Daily video scraper run completed"
exit $SCRAPER_EXIT_CODE
