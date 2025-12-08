#!/bin/bash
#
# jellyplex-radarr-hook.sh
#
# Radarr Custom Script to queue movies for synchronization.
# Writes the movie path to a queue file which is processed by a cron job.
# This avoids mounting the Docker socket in Radarr and handles batching efficiently.
#
# Race Condition Prevention:
#   - Uses flock on a shared lock file to coordinate with the cron job
#   - Atomic append ensures partial writes don't corrupt the queue
#

set -euo pipefail

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Directory where the queue file will be stored.
# This must be a path accessible to both Radarr (this script) and the Host Cron script.
# Typically a shared media folder.
QUEUE_DIR="${QUEUE_DIR:-/Cumflix}"
QUEUE_FILE="${QUEUE_DIR}/.jellyplex-queue"
# Lock file shared with cron script - must be accessible by both processes
QUEUE_LOCK_FILE="${QUEUE_LOCK_FILE:-/tmp/jellyplex-queue.lock}"

LOG_FILE="${LOG_FILE:-/config/logs/jellyplex-hook.log}"

# ==============================================================================
# LOGIC
# ==============================================================================

log() {
    mkdir -p "$(dirname "$LOG_FILE")"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Handle Test Event
if [[ "${radarr_eventtype}" == "Test" ]]; then
    log "Test event received. Connection successful."
    exit 0
fi

# Only process relevant events
if [[ ! "${radarr_eventtype}" =~ ^(Download|Upgrade|Rename)$ ]]; then
    log "Ignoring event type: ${radarr_eventtype}"
    exit 0
fi

# Ensure we have a movie path
if [[ -z "${radarr_movie_path}" ]]; then
    log "ERROR: No movie path provided (radarr_movie_path is empty)."
    exit 1
fi

log "Queuing movie: ${radarr_movie_title} (${radarr_eventtype})"

# Atomic write to queue file using shared lock
# This coordinates with the cron job to prevent race conditions during queue move
(
    flock -x 200
    # Ensure queue directory exists
    mkdir -p "$QUEUE_DIR"
    echo "${radarr_movie_path}" >> "$QUEUE_FILE"
) 200>"$QUEUE_LOCK_FILE"

log "Added to queue: ${radarr_movie_path}"
exit 0
