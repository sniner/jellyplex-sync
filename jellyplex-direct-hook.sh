#!/bin/bash
#
# jellyplex-direct-hook.sh
#
# Radarr Custom Script to sync specific movies to Jellyfin immediately on import/upgrade.
# Refactored from Cron-based trigger to synchronous execution.
#

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Jellyfin Configuration (Pass these as Environment Variables or set here)
# SECURITY NOTE: It is recommended to use HTTPS for JELLYFIN_URL and set JELLYFIN_API_KEY via environment variables.
JELLYFIN_URL="${JELLYFIN_URL:-http://localhost:8096}"
JELLYFIN_API_KEY="${JELLYFIN_API_KEY:-}"

# Docker Configuration
SYNC_IMAGE="ghcr.io/plex-migration-homelab/jellyplex-sync:latest"

# Logging
# Uses /config/logs (Standard Radarr internal path) which maps to /mnt/user/appdata/radarr/logs on host
LOG_FILE="${LOG_FILE:-/config/logs/jellyplex-sync.log}"

# Mount Point Logic
# This is the path ON THE HOST that contains your media library.
# The script runs 'docker run' via the socket, so it needs the HOST path.
# Legacy script used: /mnt/user/Media
MOUNT_SOURCE="${MOUNT_SOURCE:-/mnt/user/Media}"

# ==============================================================================
# LOGIC
# ==============================================================================

log() {
    # Ensure log directory exists
    mkdir -p "$(dirname "$LOG_FILE")"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 1. Validation and Setup
# -----------------------

# Handle Test Event
if [[ "${radarr_eventtype}" == "Test" ]]; then
    log "Test event received. Connection successful."
    exit 0
fi

# Ensure we have a movie path
if [[ -z "${radarr_movie_path}" ]]; then
    log "ERROR: No movie path provided (radarr_movie_path is empty)."
    exit 1
fi

log "=== Starting Jellyplex Sync (Direct Hook) ==="
log "Event: ${radarr_eventtype}"
log "Movie: ${radarr_movie_title} (${radarr_movie_path})"

# 2. Smart Path Logic
# -------------------
# Detect library type (movies vs movies-4k) based on path.
# Sets source/target for Docker and local paths for permissions.

if [[ "${radarr_movie_path}" == *"/movies-4k/"* ]]; then
    SOURCE_LIB="movies-4k"
    TARGET_LIB="jellyfin/movies-4k"
    # Replace /movies-4k/ with /jellyfin/movies-4k/ for local operations
    LOCAL_TARGET_PATH="${radarr_movie_path/movies-4k/jellyfin\/movies-4k}"
else
    # Default to standard movies
    SOURCE_LIB="movies"
    TARGET_LIB="jellyfin/movies"
    # Replace /movies/ with /jellyfin/movies/ for local operations
    LOCAL_TARGET_PATH="${radarr_movie_path/movies/jellyfin\/movies}"
fi

log "Library Detected: ${SOURCE_LIB}"
log "Sync Source (Container): /mnt/${SOURCE_LIB}"
log "Sync Target (Container): /mnt/${TARGET_LIB}"

# 3. Direct Execution (Docker)
# ----------------------------
# Runs the sync container immediately.
# -v "${MOUNT_SOURCE}:/mnt" maps Radarr's /Cumflix to Container's /mnt
# --partial passes the raw Radarr path for the Python script to resolve

log "Executing Docker Sync..."

docker run --rm \
    --user 99:100 \
    -v "${MOUNT_SOURCE}:/mnt" \
    "$SYNC_IMAGE" \
    --verbose \
    --delete \
    --create \
    --partial "${radarr_movie_path}" \
    "/mnt/${SOURCE_LIB}" \
    "/mnt/${TARGET_LIB}" 2>&1 | tee -a "$LOG_FILE"

SYNC_EXIT_CODE=${PIPESTATUS[0]}

if [[ $SYNC_EXIT_CODE -ne 0 ]]; then
    log "ERROR: Sync failed with exit code $SYNC_EXIT_CODE"
    exit $SYNC_EXIT_CODE
fi

log "Sync completed successfully."

# 4. Permissions (Unraid/Host)
# ----------------------------
# Ensures the target folder has correct ownership (Safety net)

if [[ -d "$LOCAL_TARGET_PATH" ]]; then
    log "Setting ownership on $LOCAL_TARGET_PATH..."
    if chown -R 99:100 "$LOCAL_TARGET_PATH"; then
        log "Ownership set successfully."
    else
        CHOWN_EXIT=$?
        log "ERROR: Failed to set ownership on $LOCAL_TARGET_PATH (Exit Code: $CHOWN_EXIT). Check permissions."
        # We don't exit here as the sync itself was successful, but we log the error.
    fi
else
    log "ERROR: Target path $LOCAL_TARGET_PATH not found after sync. The sync may have failed or path substitution is incorrect."
    exit 2
fi

# 5. Jellyfin Notification
# ------------------------
# Converts path to Jellyfin format and triggers scan
# Logic: s|^/Cumflix/movies-4k/|/media/jellyfin/movies-4k/|

JELLYFIN_PATH=$(echo "$radarr_movie_path" | sed 's|^/Cumflix/movies-4k/|/media/jellyfin/movies-4k/|; s|^/Cumflix/movies/|/media/jellyfin/movies/|')

# JSON Escape the path (escape backslashes and double quotes)
JELLYFIN_PATH_ESCAPED=$(echo "$JELLYFIN_PATH" | sed 's/\\/\\\\/g; s/"/\\"/g')

log "Notifying Jellyfin: $JELLYFIN_PATH"

if [[ -n "$JELLYFIN_API_KEY" ]]; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST "${JELLYFIN_URL}/Library/Media/Updated" \
        -H "X-Emby-Token: ${JELLYFIN_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "{\"Updates\":[{\"Path\":\"${JELLYFIN_PATH_ESCAPED}\",\"UpdateType\":\"Created\"}]}")

    if [[ "$HTTP_CODE" == "204" ]] || [[ "$HTTP_CODE" == "200" ]]; then
        log "Jellyfin scan triggered successfully (HTTP $HTTP_CODE)"
    else
        log "WARNING: Jellyfin scan failed (HTTP $HTTP_CODE)"
    fi
else
    log "Skipping notification (No API Key set)"
fi

log "=== Hook Complete ==="
exit 0
