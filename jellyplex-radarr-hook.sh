#!/bin/bash
#
# jellyplex-radarr-hook.sh
#
# Radarr Custom Script to queue movies for synchronization.
# Writes the movie path to a queue file which is processed by a cron job.
# This avoids mounting the Docker socket in Radarr and handles batching efficiently.
#

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Directory where the queue file will be stored.
# This must be a path accessible to both Radarr (this script) and the Host Cron script.
# Typically a shared media folder.
QUEUE_DIR="${QUEUE_DIR:-/Cumflix}"
QUEUE_FILE="${QUEUE_DIR}/.jellyplex-queue"

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

# Atomic write to queue file
(
    flock -x 200
    echo "${radarr_movie_path}" >> "$QUEUE_FILE"
) 200>"/tmp/jellyplex-queue.lock"

log "Added to queue: ${radarr_movie_path}"
exit 0
