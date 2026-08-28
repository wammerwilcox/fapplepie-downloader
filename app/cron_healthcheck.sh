#!/usr/bin/env bash

# Verify the cron daemon and detect a missed scheduled run. The state and
# startup markers are written atomically into LOG_DIR by the cron entrypoint
# and scheduled wrapper, respectively.
set -euo pipefail

if ! pgrep -x cron >/dev/null; then
    echo "ERROR: cron daemon is not running"
    exit 1
fi

max_age_seconds="${CRON_MISSED_RUN_MAX_AGE_SECONDS:-93600}"
if ! [[ "${max_age_seconds}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: CRON_MISSED_RUN_MAX_AGE_SECONDS must be an integer"
    exit 1
fi

if [ "${max_age_seconds}" -eq 0 ]; then
    exit 0
fi

log_dir="${LOG_DIR:-/app/logs}"
startup_marker="${log_dir}/cron_scheduler_started_at"
state_file="${log_dir}/scheduled_run_state"
now_epoch="$(date -u +%s)"

read_epoch() {
    local file="$1"
    local key="$2"
    awk -F= -v expected_key="${key}" '$1 == expected_key { print $2; exit }' "${file}"
}

if [ -f "${state_file}" ]; then
    last_dispatch_epoch="$(read_epoch "${state_file}" "started_epoch")"
    if [[ ! "${last_dispatch_epoch}" =~ ^[0-9]+$ ]]; then
        echo "ERROR: scheduled-run state is invalid: ${state_file}"
        exit 1
    fi
    reference_label="last scheduled dispatch"
    reference_epoch="${last_dispatch_epoch}"
fi

if [ -f "${startup_marker}" ]; then
    startup_epoch="$(read_epoch "${startup_marker}" "started_epoch")"
    if [[ ! "${startup_epoch}" =~ ^[0-9]+$ ]]; then
        echo "ERROR: cron scheduler marker is invalid: ${startup_marker}"
        exit 1
    fi
    if [ -z "${reference_epoch:-}" ] || [ "${startup_epoch}" -gt "${reference_epoch}" ]; then
        reference_label="scheduler startup without a dispatch"
        reference_epoch="${startup_epoch}"
    fi
fi

if [ -z "${reference_epoch:-}" ]; then
    echo "ERROR: cron scheduler startup marker is missing: ${startup_marker}"
    exit 1
fi

age_seconds=$((now_epoch - reference_epoch))
if [ "${age_seconds}" -gt "${max_age_seconds}" ]; then
    echo "ERROR: ${reference_label} is ${age_seconds}s old (maximum ${max_age_seconds}s)"
    exit 1
fi
