#!/usr/bin/env bash

set -euo pipefail

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
LOG_DIR="${LOG_DIR:-${SCRIPT_DIR}/logs}"
LOG_FILE="${LOG_DIR}/daily_run_$(date +%Y%m%d_%H%M%S).log"
SCHEDULED_RUN_STATE_FILE="${LOG_DIR}/scheduled_run_state"
SCHEDULED_RUN_START_EPOCH=""
SCHEDULED_RUN_START_UTC=""

# Create logs directory if it doesn't exist
mkdir -p "${LOG_DIR}"

write_scheduled_run_state() {
    local state="$1"
    local exit_code="${2:-}"
    local state_tmp

    state_tmp="$(mktemp "${LOG_DIR}/.scheduled_run_state.XXXXXX")"
    {
        printf 'state=%s\n' "${state}"
        printf 'started_at_utc=%s\n' "${SCHEDULED_RUN_START_UTC}"
        printf 'started_epoch=%s\n' "${SCHEDULED_RUN_START_EPOCH}"
        printf 'updated_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        if [ -n "${exit_code}" ]; then
            printf 'exit_code=%s\n' "${exit_code}"
        fi
    } > "${state_tmp}"
    mv "${state_tmp}" "${SCHEDULED_RUN_STATE_FILE}"
}

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

if [ "${FAPPLEPIE_CRON_DISPATCHED:-0}" = "1" ]; then
    SCHEDULED_RUN_START_EPOCH="$(date -u +%s)"
    SCHEDULED_RUN_START_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    write_scheduled_run_state "running"
    log "SCHEDULER_DISPATCHED: cron started scheduled daily download wrapper"
fi

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

# Run the scraper with --all option (scrape and download). Cron sets
# APPLY_SCHEDULED_START_JITTER=1 so scheduled runs can delay before network work
# without slowing manual one-shot executions of this script.
SCRAPER_ARGS=(--all)
if [ "${APPLY_SCHEDULED_START_JITTER:-0}" = "1" ]; then
    SCRAPER_ARGS=(--scheduled "${SCRAPER_ARGS[@]}")
fi

log "Running: python3 scraper.py ${SCRAPER_ARGS[*]}"
set +e
python3 scraper.py "${SCRAPER_ARGS[@]}" 2>&1 | tee -a "${LOG_FILE}"
SCRAPER_EXIT_CODE=${PIPESTATUS[0]}
set -e

if [ $SCRAPER_EXIT_CODE -eq 0 ]; then
    log "SUCCESS: Scraper completed successfully"
else
    log "ERROR: Scraper failed with exit code $SCRAPER_EXIT_CODE"
fi

if [ -n "${SCHEDULED_RUN_START_EPOCH}" ]; then
    write_scheduled_run_state "completed" "${SCRAPER_EXIT_CODE}"
fi

log "Log saved to: ${LOG_FILE}"

# Cleanup old logs (keep last 30 days)
log "Cleaning up old logs..."
find "${LOG_DIR}" -name "daily_run_*.log" -type f -mtime +30 -delete

log "Daily video scraper run completed"
exit $SCRAPER_EXIT_CODE
