#!/bin/bash
#
# jellyplex-cron.sh
#
# Host-side cron script to process the synchronization queue.
# Reads the queue file created by the Radarr hook, performs partial syncs
# using Docker, and notifies Jellyfin.
#
# Schedule recommendation: */5 * * * * (Every 5 minutes)
#

set -euo pipefail

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Path to the queue file (Must match the location written by Radarr hook, but from Host perspective)
QUEUE_FILE="${QUEUE_FILE:-/mnt/user/Media/.temp/.jellyplex-queue}"
LOCK_FILE="/tmp/jellyplex-cron.lock"
# Lock file shared with Radarr hook (must be accessible by both)
QUEUE_LOCK_FILE="${QUEUE_LOCK_FILE:-/tmp/jellyplex-queue.lock}"
LOG_FILE="${LOG_FILE:-/mnt/user/appdata/radarr/logs/jellyplex-sync.txt}"

# Docker Configuration
SYNC_IMAGE="ghcr.io/plex-migration-homelab/jellyplex-sync:latest"
# Host path to mount into the container as /mnt
MOUNT_SOURCE="${MOUNT_SOURCE:-/mnt/user/Media}"

# Jellyfin Configuration
JELLYFIN_URL="${JELLYFIN_URL:-http://localhost:8096}"
JELLYFIN_API_KEY="${JELLYFIN_API_KEY:-}"

# Radarr Configuration
# The internal path Radarr uses for the root media folder (Default: /media)
RADARR_ROOT="${RADARR_ROOT:-/media}"

# Library Configuration (Configurable patterns)
# 4K Library
LIB_4K_PATTERN="${LIB_4K_PATTERN:-/movies-4k/}"
SOURCE_4K="${SOURCE_4K:-movies-4k}"
TARGET_4K="${TARGET_4K:-jellyfin/movies-4k}"

# Standard Library
SOURCE_STD="${SOURCE_STD:-movies}"
TARGET_STD="${TARGET_STD:-jellyfin/movies}"

# Warn if Jellyfin API key is not set
if [[ -z "$JELLYFIN_API_KEY" ]]; then
    echo "[$(date)] WARNING: JELLYFIN_API_KEY is not set. Jellyfin notifications will not be sent." >> "$LOG_FILE"
fi

# ==============================================================================
# LOGIC
# ==============================================================================

# Exit if no queue file exists
[[ -f "$QUEUE_FILE" ]] || exit 0

# Prevent concurrent runs
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "[$(date)] Sync already in progress, skipping." >> "$LOG_FILE"
    exit 0
fi

echo "[$(date)] === Starting Batch Sync ===" >> "$LOG_FILE"

# Atomically move queue to processing file
PROCESSING_FILE="${QUEUE_FILE}.processing"
(
    flock -x 201
    # Double-check file still exists after acquiring lock
    if [[ -f "$QUEUE_FILE" ]]; then
        mv "$QUEUE_FILE" "$PROCESSING_FILE" 2>/dev/null || true
    fi
) 201>"$QUEUE_LOCK_FILE"

if [[ ! -f "$PROCESSING_FILE" ]]; then
    echo "[$(date)] No queue file to process." >> "$LOG_FILE"
    exit 0
fi

# Deduplicate paths
PATHS=$(sort -u "$PROCESSING_FILE")

# Check if we have paths
if [[ -z "$PATHS" ]]; then
    rm -f "$PROCESSING_FILE"
    exit 0
fi

FAILED_COUNT=0
SYNCED_PATHS=()
FAILED_PATHS=()

# Process each unique movie
while IFS= read -r movie_path; do
    [[ -z "$movie_path" ]] && continue

    echo "[$(date)] Processing: $movie_path" >> "$LOG_FILE"

    # Smart Path Logic: Detect library type
    if [[ "$movie_path" == *"${LIB_4K_PATTERN}"* ]]; then
        SOURCE_LIB="$SOURCE_4K"
        TARGET_LIB="$TARGET_4K"
    else
        SOURCE_LIB="$SOURCE_STD"
        TARGET_LIB="$TARGET_STD"
    fi

    # Execute Docker Sync
    # We pass --partial "$movie_path" so the container only syncs that specific folder.
    # We temporarily disable 'set -e' to catch Docker errors without crashing the script.
    set +e
    docker run --rm \
        --user 99:100 \
        -v "${MOUNT_SOURCE}:/mnt" \
        "$SYNC_IMAGE" \
        --verbose \
        --delete \
        --create \
        --update-filenames \
        --partial "$movie_path" \
        "/mnt/${SOURCE_LIB}" \
        "/mnt/${TARGET_LIB}" >> "$LOG_FILE" 2>&1
    
    EXIT_CODE=$?
    set -e

    if [[ $EXIT_CODE -ne 0 ]]; then
        echo "[$(date)] ERROR: Sync failed for $movie_path (Exit: $EXIT_CODE)" >> "$LOG_FILE"
        ((FAILED_COUNT++))
        FAILED_PATHS+=("$movie_path")
    else
        SYNCED_PATHS+=("$movie_path")
    fi

done <<< "$PATHS"

# Re-queue failed items so they aren't lost
if [[ ${#FAILED_PATHS[@]} -gt 0 ]]; then
    echo "[$(date)] Re-queuing ${#FAILED_PATHS[@]} failed items..." >> "$LOG_FILE"
    (
        flock -x 201
        for fail_path in "${FAILED_PATHS[@]}"; do
            echo "$fail_path" >> "$QUEUE_FILE"
        done
    ) 201>"$QUEUE_LOCK_FILE"
fi

# Cleanup processing file
rm -f "$PROCESSING_FILE"

# Fix permissions on target directories (Safety net)
echo "[$(date)] Setting permissions..." >> "$LOG_FILE"
TARGET_DIRS=(
    "${MOUNT_SOURCE}/${TARGET_STD}"
    "${MOUNT_SOURCE}/${TARGET_4K}"
)

for target_dir in "${TARGET_DIRS[@]}"; do
    if [[ -d "$target_dir" ]]; then
        chown -R 99:100 "$target_dir" 2>/dev/null
    fi
done

# Jellyfin Notification
if [[ -n "$JELLYFIN_API_KEY" && ${#SYNCED_PATHS[@]} -gt 0 ]]; then
    echo "[$(date)] Notifying Jellyfin..." >> "$LOG_FILE"

    JSON_UPDATES=""
    for raw_path in "${SYNCED_PATHS[@]}"; do
        # Robust Path Substitution logic
        # 1. Try to replace specific library paths first
        # 2. Fallback to replacing the root folder if the specific library match fails
        JELLYFIN_PATH=$(echo "$raw_path" | sed \
            "s|${RADARR_ROOT}/${SOURCE_4K}/|/media/${TARGET_4K}/|; \
             s|${RADARR_ROOT}/${SOURCE_STD}/|/media/${TARGET_STD}/|; \
             s|^${RADARR_ROOT}/|/media/|")

        # Escape for JSON
        JELLYFIN_PATH_ESCAPED=$(echo "$JELLYFIN_PATH" | sed 's/\\/\\\\/g; s/"/\\"/g')

        if [[ -n "$JSON_UPDATES" ]]; then
            JSON_UPDATES="${JSON_UPDATES},"
        fi
        JSON_UPDATES="${JSON_UPDATES}{\"Path\":\"${JELLYFIN_PATH_ESCAPED}\",\"UpdateType\":\"Created\"}"
    done

    # Send request and capture HTTP status code
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST "${JELLYFIN_URL}/Library/Media/Updated" \
        -H "X-Emby-Token: ${JELLYFIN_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "{\"Updates\":[${JSON_UPDATES}]}")

    # Check result
    if [[ "$HTTP_CODE" == "204" ]]; then
        echo "[$(date)] SUCCESS: Jellyfin accepted update notification." >> "$LOG_FILE"
    else
        echo "[$(date)] WARNING: Jellyfin notification failed (HTTP $HTTP_CODE). Check API Key or URL." >> "$LOG_FILE"
    fi

else
    if [[ -z "$JELLYFIN_API_KEY" ]]; then
        echo "[$(date)] Skipping Jellyfin notification (No API Key set)" >> "$LOG_FILE"
    elif [[ ${#SYNCED_PATHS[@]} -eq 0 ]]; then
        echo "[$(date)] No items successfully synced, skipping notification." >> "$LOG_FILE"
    fi
fi

echo "[$(date)] Batch sync complete: ${#SYNCED_PATHS[@]} synced, $FAILED_COUNT failed." >> "$LOG_FILE"
exit $((FAILED_COUNT > 0 ? 1 : 0))